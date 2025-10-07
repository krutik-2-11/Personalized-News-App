# focused.py
from __future__ import annotations
import os
import re
import html
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from urllib.parse import quote_plus, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, request, render_template, session, redirect, url_for, jsonify
import requests
import feedparser

log = logging.getLogger("news.focused")

# ---------- LLM (optional) ----------
USE_LLM = bool(os.environ.get("OPENAI_API_KEY"))
try:
    from llm_summarizer import summarize_with_llm, summarize_with_llm_finance
except Exception as e:
    log.warning("LLM summarizer unavailable: %s", e)
    USE_LLM = False

# ---------- Config ----------
UA = os.environ.get("FEED_USER_AGENT", "PersonalizedNews/1.0 (+https://example.com)")
FEED_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
}
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 8))
QUERY_DAYS      = int(os.environ.get("QUERY_DAYS", 7))
MAX_RESULTS     = int(os.environ.get("MAX_QUERY_RESULTS", 25))
MAX_RESOLVE     = int(os.environ.get("MAX_RESOLVE_REDIRECTS", 6))   # resolve only a few for speed
MAX_WORKERS     = int(os.environ.get("MAX_WORKERS", 6))
NEWS_TTL        = int(os.environ.get("FOCUSED_NEWS_TTL", 600))      # 10 min
REDIRECT_TTL    = int(os.environ.get("REDIRECT_TTL", 86400))        # 24 hr
SUMMARY_TTL     = int(os.environ.get("SUMMARY_TTL", 1800))          # 30 min
PAGES_FOR_LLM   = int(os.environ.get("PAGES_FOR_LLM", 3))           # expand N pages for LLM

# Strong finance sources (whitelist)
FINANCE_DOMAINS = {
    "reuters.com","bloomberg.com","wsj.com","ft.com","cnbc.com","marketwatch.com",
    "businesswire.com","prnewswire.com","sec.gov",
    "investors.businesswire.com","ir.aboutamazon.com","ir.microsoft.com","ir.apple.com"
}
# General high-quality sources
TRUSTED_DOMAINS = {
    "apnews.com","bbc.co.uk","bbc.com","nytimes.com","washingtonpost.com","theguardian.com",
    "arstechnica.com","theverge.com","techcrunch.com"
}
# De-prioritize retail/advice/opinion for finance briefs
EXCLUDE_OPINION_DOMAINS = {
    "investopedia.com","ibtimes.com","thestreet.com","fool.com","investors.com"  # IBD
}

FINANCE_KEYWORDS = [
    "earnings","revenue","guidance","outlook","forecast","margin","EBIT","EBITDA",
    "free cash flow","FCF","buyback","dividend","downgrade","upgrade","price target",
    "rating","M&A","acquisition","merger","antitrust","regulator","SEC","FTC",
    "strike","layoffs","restructuring","spin-off","catalyst"
]

bp = Blueprint("focused", __name__)

# ---------- Caches ----------
_NOW = lambda: int(time.time())
NEWS_CACHE: Dict[str, Dict[str, Any]]     = {}
REDIRECT_CACHE: Dict[str, Dict[str, Any]] = {}
SUMMARY_CACHE: Dict[str, Dict[str, Any]]  = {}

def _stale(ts: int | None, ttl: int) -> bool:
    return True if not ts else (_NOW() - ts) > ttl

# ---------- Helpers ----------
TAG_RE  = re.compile(r"<[^>]+>")
WS_RE   = re.compile(r"\s+")
HREF_RE = re.compile(r'href="([^"]+)"')

def strip_html(s: str) -> str:
    if not s: return ""
    s = html.unescape(s)
    s = TAG_RE.sub(" ", s)
    s = s.replace("\xa0"," ").replace("&nbsp;"," ")
    return WS_RE.sub(" ", s).strip()

def first_publisher_href(fragment: str) -> str | None:
    """Prefer a non-aggregator href if the RSS summary contains multiple links."""
    if not fragment: return None
    hrefs = HREF_RE.findall(fragment)
    for h in hrefs:
        if "news.google.com" not in (h or ""):
            return h
    return hrefs[0] if hrefs else None

def to_aware(dt: datetime | None) -> datetime:
    if not dt: return datetime(1970,1,1,tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def parse_entry_date(entry: Dict[str, Any]) -> datetime | None:
    for key in ("published","updated","created"):
        val = entry.get(key)
        if val:
            try:
                from dateutil import parser as dateparser
                return dateparser.parse(val)
            except Exception:
                pass
    for key in ("published_parsed","updated_parsed"):
        if entry.get(key):
            try:
                return datetime.fromtimestamp(time.mktime(entry[key]), tz=timezone.utc)
            except Exception:
                pass
    return None

def domain_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""

def good_fin_domain(url: str) -> bool:
    d = domain_of(url)
    return any(t in d for t in FINANCE_DOMAINS)

def good_general_domain(url: str) -> bool:
    d = domain_of(url)
    return any(t in d for t in TRUSTED_DOMAINS)

def is_opinionish(url: str) -> bool:
    d = domain_of(url)
    return any(t in d for t in EXCLUDE_OPINION_DOMAINS)

def google_news_rss_url(q: str, days: int = QUERY_DAYS) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(q)}+when:{days}d&hl=en-US&gl=US&ceid=US:en"

def build_finance_query(q: str) -> str:
    bucket = " OR ".join([f'"{k}"' if " " in k else k for k in FINANCE_KEYWORDS[:16]])
    return f'{q} ({bucket})'

def resolve_publisher_url(url: str) -> str:
    """Follow redirects for Google News links; cache for a day."""
    if "news.google.com" not in (url or ""):
        return url
    ce = REDIRECT_CACHE.get(url)
    if ce and not _stale(ce["ts"], REDIRECT_TTL):
        return ce["final"]
    try:
        r = requests.get(url, headers=FEED_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        final = r.url or url
    except Exception:
        final = url
    REDIRECT_CACHE[url] = {"final": final, "ts": _NOW()}
    return final

def _fetch_raw_items(rss_url: str) -> List[Dict[str, Any]]:
    parsed = feedparser.parse(rss_url, request_headers=FEED_HEADERS)
    items: List[Dict[str, Any]] = []
    for e in parsed.entries[: MAX_RESULTS]:
        title = strip_html((e.get("title") or "").strip())
        raw_summary = e.get("summary","")
        link = first_publisher_href(raw_summary) or e.get("link")
        summary_txt = strip_html(raw_summary)
        items.append({
            "title": title or "(no title)",
            "link": link,
            "summary": summary_txt,
            "published_at": parse_entry_date(e),
            "source": strip_html((e.get("source", {}) or {}).get("title","")),
            "domain": domain_of(link or ""),
        })
    return items

def fetch_query_news(query: str, *, finance: bool=False) -> List[Dict[str, Any]]:
    """Fetch, resolve a few links in parallel, apply tiered filtering, cache 10 min."""
    key = f"{'fin' if finance else 'gen'}:{query.strip().lower()}"
    ce = NEWS_CACHE.get(key)
    if ce and not _stale(ce["ts"], NEWS_TTL):
        return ce["items"][:]

    q = build_finance_query(query) if finance else query
    url = google_news_rss_url(q)

    # HEAD may fail sometimes; ignore errors
    try:
        _ = requests.head(url, timeout=REQUEST_TIMEOUT, headers=FEED_HEADERS, allow_redirects=True)
    except Exception:
        pass

    items = _fetch_raw_items(url)

    # Resolve top-N aggregator links concurrently
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures, idx_map = [], []
        for idx, it in enumerate(items[:MAX_RESOLVE]):
            if it["link"] and "news.google.com" in it["link"]:
                futures.append(ex.submit(resolve_publisher_url, it["link"]))
                idx_map.append(idx)
        for i, fut in enumerate(futures):
            try:
                final = fut.result()
                idx = idx_map[i]
                items[idx]["link"]   = final
                items[idx]["domain"] = domain_of(final)
            except Exception:
                pass

    # Tiered filtering keeps results useful but non-empty
    if finance:
        chosen = [x for x in items if x["link"] and good_fin_domain(x["link"]) and not is_opinionish(x["link"])]
        if len(chosen) < 6:
            chosen = [x for x in items if x["link"] and (good_fin_domain(x["link"]) or good_general_domain(x["link"])) and not is_opinionish(x["link"])]
        if len(chosen) < 3:
            chosen = [x for x in items if x["link"] and not is_opinionish(x["link"])]
    else:
        chosen = [x for x in items if x["link"] and (good_general_domain(x["link"]) or good_fin_domain(x["link"]))]

    chosen.sort(key=lambda x: to_aware(x.get("published_at")), reverse=True)
    NEWS_CACHE[key] = {"items": chosen[:], "ts": _NOW()}
    log.info("[focus] %s (finance=%s) → %d items (raw=%d)", query, finance, len(chosen), len(items))
    return chosen

# ---------- Article text expansion for LLM (small & fast) ----------
def fetch_article_text(url: str) -> str:
    """Return cleaned main text (via readability). Soft-fail on any error."""
    try:
        r = requests.get(url, headers=FEED_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400 or not r.text:
            return ""
        from readability import Document
        from bs4 import BeautifulSoup
        doc  = Document(r.text)
        html_clean = doc.summary()
        soup = BeautifulSoup(html_clean, "lxml")
        text = " ".join(soup.stripped_strings)
        return text[:6000]
    except Exception:
        return ""

def expand_content(items: List[Dict[str, Any]], max_pages: int = PAGES_FOR_LLM) -> List[Dict[str, str]]:
    chosen = items[:max_pages]
    out: List[Dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max_pages)) as ex:
        futs = {ex.submit(fetch_article_text, it.get("link","")): it for it in chosen if it.get("link")}
        for f in as_completed(futs):
            it = futs[f]
            try:
                text = f.result()
            except Exception:
                text = ""
            if text:
                out.append({"title": it.get("title",""), "domain": it.get("domain",""), "text": text})
    return out

# ---------- Markdown fallback formatting ----------
def _extractive_bullets(texts: List[str], max_bullets: int = 8) -> List[str]:
    text = " ".join(strip_html(t) for t in texts if t) or ""
    if not text:
        return []
    from collections import Counter
    tokens = re.findall(r"[a-zA-Z']+", text.lower())
    STOP = set("a about above after again against all am an and any are as at be because been before being below between both but by could did do does doing down during each few for from further had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not of off on once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too under until up very was we were what when where which while who whom why with you your yours yourself yourselves".split())
    words = [w for w in tokens if w not in STOP and len(w) > 2]
    if not words:
        return []
    freq = Counter(words)
    SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
    raw_sents = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    scored = []
    for idx, s in enumerate(raw_sents):
        ws = re.findall(r"[a-zA-Z']+", s.lower())
        if not ws:
            continue
        score = sum(freq.get(w, 0) for w in ws) / max(8, len(ws))
        scored.append((idx, score, s))
    top = sorted(scored, key=lambda x: x[1], reverse=True)[:max_bullets]
    return [s for _, __, s in sorted(top, key=lambda x: x[0])]

def extractive_markdown(items: List[Dict[str,Any]], texts: List[str]) -> str:
    bullets = _extractive_bullets(texts)
    md = ["### What's new"]
    if bullets:
        md += [*(f"- {b}" for b in bullets[:3])]
    if len(bullets) > 3:
        md += ["", "### Key drivers & numbers"]
        md += [*(f"- {b}" for b in bullets[3:8])]
    md += ["", "### Notable links"]
    for a in items[:5]:
        title = (a.get("title") or "").strip() or "(link)"
        dom   = a.get("domain","")
        link  = a.get("link","")
        md.append(f"- [{title}]({link}) — {dom}")
    return "\n".join(md).strip()

# ---------- Routes ----------
@bp.route("/focus", methods=["GET", "POST"])
def focus_home():
    if request.method == "POST":
        raw  = (request.form.get("tags") or "").strip()
        tags = [t.strip() for t in re.split(r"[,\n;]", raw) if t.strip()]
        session["focus_tags"]    = tags[:10]
        session["summary_mode"]  = request.form.get("summary_mode") or "extractive"
        session["result_filter"] = request.form.get("result_filter") or "finance"
        return redirect(url_for("focused.focus_home"))

    tags = session.get("focus_tags", [])
    mode = session.get("summary_mode", "extractive")
    result_filter = session.get("result_filter", "finance")

    tag_results: Dict[str, List[Dict[str, Any]]] = {}
    if tags:
        finance = (result_filter == "finance")
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tags))) as ex:
            futures = {ex.submit(fetch_query_news, t, finance=finance): t for t in tags}
            for f in as_completed(futures):
                t = futures[f]
                items = []
                try:
                    items = f.result()
                except Exception as e:
                    log.error("fetch_query_news(%s) failed: %s", t, e)
                if not items:  # fallback to general if finance too strict
                    try:
                        items = fetch_query_news(t, finance=False)
                    except Exception:
                        items = []
                tag_results[t] = items[:6]

    return render_template(
        "focus.html",
        tags=tags,
        tag_results=tag_results,
        summary_mode=mode,
        result_filter=result_filter,
        use_llm=USE_LLM,
    )

@bp.route("/search")
def focus_search():
    """Render quickly; summary is fetched async from /api/summarize."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("focused.focus_home"))

    finance = (session.get("result_filter", "finance") == "finance")
    items = fetch_query_news(q, finance=finance) or fetch_query_news(q, finance=False)

    return render_template(
        "search.html",
        q=q,
        items=items[:12],
        summary="Generating…",
        error_msg=None,
        finance=finance,
    )

@bp.route("/api/summarize")
def api_summarize():
    """Generate (and cache) a Markdown summary. Uses LLM if enabled; otherwise extractive Markdown."""
    q = (request.args.get("q") or "").strip()
    finance = request.args.get("finance", "1") in ("1", "true", "yes")
    mode = request.args.get("mode") or session.get("summary_mode", "extractive")

    if not q:
        return jsonify({"summary": "No summary.", "cached": True, "used_llm": False})

    items = fetch_query_news(q, finance=finance) or fetch_query_news(q, finance=False)

    # cache key built from top titles/domains + mode
    top_fingerprint = "|".join([ (i.get("title","")[:80] + i.get("domain","")) for i in items[:8] ])
    skey = hashlib.sha1((("fin:" if finance else "gen:") + q.lower() + top_fingerprint + mode).encode("utf-8")).hexdigest()
    ce = SUMMARY_CACHE.get(skey)
    if ce and not _stale(ce["ts"], SUMMARY_TTL):
        return jsonify({"summary": ce["text"], "cached": True, "used_llm": ce.get("llm", False)})

    used_llm = False
    summary_md = None

    # Expand a few article pages only if using LLM (keeps it snappy)
    fulltexts = []
    if mode == "llm" and USE_LLM:
        fulltexts = expand_content(items, max_pages=PAGES_FOR_LLM)

    if mode == "llm" and USE_LLM:
        try:
            fn = summarize_with_llm_finance if finance else summarize_with_llm
            summary_md = fn(q, items, fulltexts=fulltexts)
            used_llm = True
        except Exception as e:
            log.warning("LLM summarization failed: %s", e)
            summary_md = None

    if not summary_md:
        texts = [f"{i.get('title','')}. {i.get('summary','')}" for i in items[:10]]
        summary_md = extractive_markdown(items, texts)

    SUMMARY_CACHE[skey] = {"text": summary_md, "ts": _NOW(), "llm": used_llm}
    return jsonify({"summary": summary_md, "cached": False, "used_llm": used_llm})

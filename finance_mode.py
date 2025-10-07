# finance_mode.py
from __future__ import annotations
import os, time, html, re
from datetime import datetime, timezone
from typing import Dict, Any, List
from urllib.parse import quote_plus, urlparse

import feedparser, requests

# --- Config ---
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 12))
FINANCE_QUERY_DAYS = int(os.environ.get("FINANCE_QUERY_DAYS", 14))

UA = os.environ.get("FEED_USER_AGENT", "PersonalizedNews/1.0 (+contact@example.com)")
COMMON_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}

# SEC requires a descriptive UA incl. email
SEC_UA = os.environ.get("SEC_USER_AGENT", "MyNewsApp/1.0 (contact@example.com)")
SEC_HEADERS = {"User-Agent": SEC_UA, "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8"}

FINANCE_DOMAINS = {
    "reuters.com","ft.com","wsj.com","cnbc.com","marketwatch.com","barrons.com",
    "finance.yahoo.com","apnews.com","bloomberg.com","seekingalpha.com","sec.gov"
}

# Minimal ticker/CIK map (extend as needed)
TICKERS: Dict[str, Dict[str, str]] = {
    "amazon":  {"ticker":"AMZN","cik":"0001018724"},
    "amazon.com":{"ticker":"AMZN","cik":"0001018724"},
    "amzn":    {"ticker":"AMZN","cik":"0001018724"},
    "nvidia":  {"ticker":"NVDA","cik":"0001045810"},
    "nvda":    {"ticker":"NVDA","cik":"0001045810"},
    "tesla":   {"ticker":"TSLA","cik":"0001318605"},
    "tsla":    {"ticker":"TSLA","cik":"0001318605"},
    "apple":   {"ticker":"AAPL","cik":"0000320193"},
    "aapl":    {"ticker":"AAPL","cik":"0000320193"},
    "microsoft":{"ticker":"MSFT","cik":"0000789019"},
    "msft":    {"ticker":"MSFT","cik":"0000789019"},
    "alphabet":{"ticker":"GOOGL","cik":"0001652044"},
    "google":  {"ticker":"GOOGL","cik":"0001652044"},
    "googl":   {"ticker":"GOOGL","cik":"0001652044"},
    "meta":    {"ticker":"META","cik":"0001326801"},
    "facebook":{"ticker":"META","cik":"0001326801"},
    "meta platforms":{"ticker":"META","cik":"0001326801"},
}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE  = re.compile(r"\s+")

def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = TAG_RE.sub(" ", s).replace("\xa0", " ").replace("&nbsp;", " ")
    return WS_RE.sub(" ", s).strip()

def to_aware(dt: datetime | None) -> datetime:
    if not dt: return datetime(1970,1,1,tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def parse_entry_date(e: Dict[str, Any]) -> datetime | None:
    for k in ("published","updated","created"):
        v = e.get(k)
        if v:
            try:
                from dateutil import parser as dp
                return dp.parse(v)
            except Exception:
                pass
    for k in ("published_parsed","updated_parsed"):
        if e.get(k):
            try:
                return datetime.fromtimestamp(time.mktime(e[k]), tz=timezone.utc)
            except Exception:
                pass
    return None

def domain_of(url: str) -> str:
    try: return (urlparse(url or "").netloc or "").lower()
    except Exception: return ""

def google_finance_query(company_or_ticker: str, days: int = FINANCE_QUERY_DAYS) -> str:
    """
    Finance-biased query for Google News RSS:
    - includes ticker if known
    - steers toward finance events (earnings, guidance, 8-K, etc.)
    """
    base = company_or_ticker.strip()
    key = base.lower()
    ticker = TICKERS.get(key, {}).get("ticker", "")
    terms = ("earnings OR revenue OR guidance OR outlook OR margin OR "
             "'free cash flow' OR buyback OR dividend OR '8-K' OR '10-Q' OR '10-K' OR "
             "acquisition OR merger OR antitrust OR FTC OR EU OR layoffs OR restructuring OR "
             "downgrade OR upgrade OR 'price target' OR AWS OR advertising")
    q = f"({base}{(' OR ' + ticker) if ticker else ''}) {terms}"
    return f"https://news.google.com/rss/search?q={quote_plus(q)}+when:{days}d&hl=en-US&gl=US&ceid=US:en"

def fetch_google_finance(company_or_ticker: str) -> List[Dict[str, Any]]:
    url = google_finance_query(company_or_ticker)
    try:
        requests.head(url, timeout=REQUEST_TIMEOUT, headers=COMMON_HEADERS, allow_redirects=True)
    except Exception:
        pass
    parsed = feedparser.parse(url, request_headers=COMMON_HEADERS)
    items: List[Dict[str, Any]] = []
    for e in parsed.entries[:40]:
        title = strip_html(e.get("title"))
        summary = strip_html(e.get("summary"))
        link = e.get("link")
        it = {
            "title": title or "(no title)",
            "summary": summary,
            "link": link,
            "published_at": parse_entry_date(e),
            "domain": domain_of(link),
            "source": strip_html((e.get("source", {}) or {}).get("title","")),
        }
        items.append(it)
    # prioritize finance domains; keep others as backup
    primary = [x for x in items if x["domain"] in FINANCE_DOMAINS]
    chosen  = primary if primary else items
    chosen.sort(key=lambda x: to_aware(x["published_at"]), reverse=True)
    return chosen

def sec_atom_url(cik: str) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&owner=exclude&count=40&output=atom"

def fetch_sec_filings(cik: str) -> List[Dict[str, Any]]:
    url = sec_atom_url(cik)
    try:
        requests.head(url, timeout=REQUEST_TIMEOUT, headers=SEC_HEADERS, allow_redirects=True)
    except Exception:
        pass
    parsed = feedparser.parse(url, request_headers=SEC_HEADERS)
    out: List[Dict[str, Any]] = []
    for e in parsed.entries[:25]:
        title = strip_html(e.get("title"))
        link  = e.get("link")
        out.append({
            "title": title or "SEC filing",
            "summary": strip_html(e.get("summary")),
            "link": link,
            "published_at": parse_entry_date(e),
            "domain": "sec.gov",
            "source": "SEC EDGAR",
        })
    out.sort(key=lambda x: to_aware(x["published_at"]), reverse=True)
    return out

def lookup_company(q: str) -> Dict[str, str]:
    key = q.strip().lower()
    if key in TICKERS:
        return TICKERS[key]
    # if user passes pure ticker like AMZN
    up = q.strip().upper()
    for v in TICKERS.values():
        if v["ticker"] == up:
            return v
    return {"ticker":"", "cik":""}

def fetch_finance_news(q: str) -> List[Dict[str, Any]]:
    """
    Combine SEC filings + finance-focused Google News results. Dedupe & sort.
    """
    meta = lookup_company(q)
    items: List[Dict[str, Any]] = []

    # Google News finance-biased
    items.extend(fetch_google_finance(meta["ticker"] or q))

    # SEC filings if we know the CIK
    if meta.get("cik"):
        items.extend(fetch_sec_filings(meta["cik"]))

    # Deduplicate by link
    seen, dedup = set(), []
    for a in items:
        key = a.get("link") or a.get("title")
        if not key:
            continue
        h = hash(key)
        if h in seen:
            continue
        seen.add(h); dedup.append(a)

    dedup.sort(key=lambda x: to_aware(x.get("published_at")), reverse=True)
    return dedup[:30]

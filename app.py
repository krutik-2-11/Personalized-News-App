# app.py
from __future__ import annotations

import os
import time
import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import feedparser
import requests
from dateutil import parser as dateparser
from dotenv import load_dotenv

from sources import TOPIC_FEEDS, DEFAULT_TOPICS

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("news")

SECRET_KEY = os.environ.get("NEWS_APP_SECRET", "dev-secret-change-me")
PORT = int(os.environ.get("PORT", "5000"))
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", 3600))
MAX_ITEMS_PER_TOPIC = int(os.environ.get("MAX_ITEMS_PER_TOPIC", 10))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 12))

UA = os.environ.get("FEED_USER_AGENT", "PersonalizedNews/1.0 (+https://example.com)")
FEED_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}

app = Flask(__name__)
app.secret_key = SECRET_KEY
CACHE: Dict[str, Dict[str, Any]] = {}

def _hash(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]

def human_time(dt: datetime | None) -> str:
    if not dt: return ""
    now = datetime.now(timezone.utc)
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60: return "just now"
    mins = secs // 60
    if mins < 60: return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 24: return f"{hrs} hr ago"
    days = hrs // 24
    return f"{days} d ago"

def to_aware(dt: datetime | None) -> datetime:
    if not dt: return datetime(1970,1,1,tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def parse_entry_date(entry: Dict[str, Any]) -> datetime | None:
    for key in ("published","updated","created"):
        val = entry.get(key)
        if val:
            try: return dateparser.parse(val)
            except Exception: pass
    for key in ("published_parsed","updated_parsed"):
        if entry.get(key):
            try: return datetime.fromtimestamp(time.mktime(entry[key]), tz=timezone.utc)
            except Exception: pass
    return None

def fetch_feed(url: str) -> List[Dict[str, Any]]:
    try:
        _ = requests.head(url, timeout=REQUEST_TIMEOUT, headers=FEED_HEADERS, allow_redirects=True)
    except Exception as e:
        log.warning("HEAD failed for %s: %s", url, e)
    parsed = feedparser.parse(url, request_headers=FEED_HEADERS)
    if getattr(parsed, "bozo", False):
        log.warning("Feed parse warning for %s: %s", url, getattr(parsed, "bozo_exception", ""))
    items: List[Dict[str, Any]] = []
    source_title = parsed.feed.get("title", "")
    for e in parsed.entries[:50]:
        title = html.escape((e.get("title") or "").strip())
        link = e.get("link")
        summary = e.get("summary", "")
        try:
            summary_text = feedparser._sanitizeHTML(summary, "utf-8") if summary else ""
        except Exception:
            summary_text = summary or ""
        published_at = parse_entry_date(e)
        items.append({
            "id": _hash(link or title),
            "title": title or "(no title)",
            "link": link,
            "summary": html.unescape(summary_text).replace("<p>"," ").replace("</p>"," "),
            "source": (e.get("source", {}) or {}).get("title") or source_title or "",
            "published_at": published_at,
        })
    log.info("Fetched %d items from %s", len(items), url)
    return items

def fetch_topic(topic: str) -> List[Dict[str, Any]]:
    urls = TOPIC_FEEDS.get(topic, [])
    articles: List[Dict[str, Any]] = []
    for u in urls:
        try:
            articles.extend(fetch_feed(u))
        except Exception as e:
            log.error("Error fetching %s: %s", u, e)
    seen, deduped = set(), []
    for a in articles:
        key = a.get("link") or a.get("title")
        h = _hash(key or "")
        if h in seen: continue
        seen.add(h); deduped.append(a)
    deduped.sort(key=lambda x: to_aware(x.get("published_at")), reverse=True)
    return deduped[: MAX_ITEMS_PER_TOPIC]

def ensure_fresh(topics: List[str], force: bool=False) -> None:
    now = datetime.now(timezone.utc)
    for t in topics:
        entry = CACHE.get(t)
        stale = True if not entry or not entry.get("fetched_at") else (now - entry["fetched_at"]).total_seconds() > CACHE_TTL_SECONDS
        if stale or force:
            CACHE[t] = {"fetched_at": now, "articles": fetch_topic(t)}

def get_selected_topics() -> List[str]:
    if "selected_topics" in session:
        return [t for t in session["selected_topics"] if t in TOPIC_FEEDS]
    return DEFAULT_TOPICS[:]

@app.route("/", methods=["GET"])
def index():
    topics_selected = get_selected_topics()
    ensure_fresh(topics_selected, force=False)
    return render_template(
        "index.html",
        topics_selected=topics_selected,
        topics_all=list(TOPIC_FEEDS.keys()),
        cache=CACHE,
        human_time=human_time,
    )

@app.route("/set-topics", methods=["POST"])
def set_topics():
    topics = [t for t in request.form.getlist("topics") if t in TOPIC_FEEDS] or DEFAULT_TOPICS[:]
    session["selected_topics"] = topics
    ensure_fresh(topics, force=True)
    return redirect(url_for("index"))

@app.route("/refresh", methods=["POST"])
def refresh():
    topics = get_selected_topics()
    ensure_fresh(topics, force=True)

    # If an API client calls this, return JSON.
    wants_json = (
        request.args.get("format") == "json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or "")
    )
    if wants_json:
        return jsonify({"status": "ok", "refreshed": topics})

    # Normal button click: go back to Home
    return redirect(url_for("index"))


@app.route("/api/articles")
def api_articles():
    topics = get_selected_topics()
    ensure_fresh(topics, force=False)
    out = {t: CACHE.get(t, {}).get("articles", []) for t in topics}
    return jsonify({"topics": topics, "articles": out, "generated_at": datetime.utcnow().isoformat() + "Z"})

# --- Register the Focused Search blueprint ---
from focused import bp as focused_bp
app.register_blueprint(focused_bp)

# Optional: list routes on startup
@app.errorhandler(500)
def handle_500(e):
    log.exception("Unhandled server error: %s", e)
    return render_template("500.html"), 500

if __name__ == "__main__":
    print("\nRegistered routes:")
    for r in app.url_map.iter_rules():
        print(" ", r)
    print()
    app.run(host="0.0.0.0", port=PORT)

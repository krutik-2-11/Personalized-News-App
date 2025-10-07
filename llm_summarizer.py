from __future__ import annotations
import os
from typing import List, Dict
from openai import OpenAI

MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def _brief_items(items: List[Dict]) -> str:
    lines = []
    for a in items[:10]:
        title  = a.get("title","")
        domain = a.get("domain","")
        blurb  = (a.get("summary","") or "")[:300]
        lines.append(f"- {title} — {domain} — {blurb}")
    return "\n".join(lines)

def _clip(text: str, lim: int) -> str:
    return text if len(text) <= lim else text[:lim]

def _fulltext_block(fulltexts: List[Dict] | None) -> str:
    if not fulltexts: return ""
    lines = ["\nFull article extracts (cleaned):"]
    for ft in fulltexts[:4]:
        lines.append(f"\n[{ft.get('domain','')}] {ft.get('title','')}\n{_clip(ft.get('text',''), 1600)}")
    return "\n".join(lines)

def summarize_with_llm(query: str, items: List[Dict], fulltexts: List[Dict] | None = None) -> str:
    prompt = f"""Topic: {query}

Context (Title — Domain — Blurb):
{_brief_items(items)}
{_fulltext_block(fulltexts)}

Return a concise investor-style summary **in Markdown only** with the sections:

### What's new
- 1–3 bullets on the most material developments.

### Key drivers & numbers
- 3–6 bullets (earnings/guidance, margins/FCF, M&A/regulatory, upgrades/downgrades).

### Risks / Watch items
- 2–4 bullets, only if present.

### Calendar
- Upcoming catalysts if present.

### Notable links
- 3–5 bullets as “Title — Domain” taken from the context only.

No preamble, no HTML, no invented data."""
    resp = client.responses.create(model=MODEL, input=prompt, temperature=0.25)
    return resp.output_text.strip()

def summarize_with_llm_finance(query: str, items: List[Dict], fulltexts: List[Dict] | None = None) -> str:
    prompt = f"""You are a sell-side equity analyst. Company/topic: {query}

Context (Title — Domain — Blurb):
{_brief_items(items)}
{_fulltext_block(fulltexts)}

Return a 220–280 word investor brief **in Markdown only** with exactly these sections:

### What's new
- 1–3 bullets on the most material developments.

### Key drivers & numbers
- 3–6 bullets (earnings/guidance, margins/FCF, upgrades/downgrades/price targets, M&A/regulatory/labor).

### Risks / Watch items
- 2–4 bullets if present.

### Calendar
- Upcoming catalysts if present.

### Notable links
- 3–5 bullets as “Title — Domain” taken strictly from the context.

Prioritize Reuters/Bloomberg/FT/WSJ/CNBC/MarketWatch and official filings. Ignore retail-advice/opinion/blog sources. No HTML, no invented numbers."""
    resp = client.responses.create(model=MODEL, input=prompt, temperature=0.15)
    return resp.output_text.strip()

# Personalized News (Flask + RSS)

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
# On Windows Run - source .venv/Scripts/activate
cp .env.example .env # then edit NEWS_APP_SECRET
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```


## Deploy
- **Render**: Web Service → Build: `pip install -r requirements.txt` → Start: `python app.py` → add env `NEWS_APP_SECRET`
- **Fly.io**: `fly launch` → `fly deploy`
- **Railway/Deta**: similar flow
- **Docker**: `docker build -t personalized-news .` → `docker run -p 8080:8080 -e PORT=8080 -e NEWS_APP_SECRET=... personalized-news`


## Customize
- Edit `sources.py` to change topics and feeds.
- Tune `CACHE_TTL_SECONDS` and `MAX_ITEMS_PER_TOPIC` in `.env`.


## Notes
- Uses only free RSS sources (no API keys).
- Keep `NEWS_APP_SECRET` secret in production.
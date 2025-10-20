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


## Some Images from my App
### General News Based on Different Topics like - Politics, Finance, Market etc.
<img width="1503" height="873" alt="image" src="https://github.com/user-attachments/assets/207d753e-a314-4f42-b339-5ec552c71bff" />

### Focused News Based on topics of interest like specific companies of interest - NVIDIA, Palantir. This is useful to get a daily update on the companies of investment (this is just an example and not something I am referring to my porfolio :D)
<img width="1117" height="942" alt="image" src="https://github.com/user-attachments/assets/20e3a4fa-da27-45d9-8e4c-0de9458bc0ce" />

### Let's say I want to understand what specific is going on in `Adobe` and get a summary based on different news i.e., to get a general idea from finance POV. I can do a focused search for that by adding `Adobe` or its ticker in search box and choose an LLM based summary and finance grade checkboxex, then click save. 
<img width="1495" height="497" alt="image" src="https://github.com/user-attachments/assets/db474281-91e4-4a77-86d3-a34341d20221" />

### On Clicking `Search & Summarize` we get an overall summary 
<img width="1436" height="623" alt="image" src="https://github.com/user-attachments/assets/2086bf87-24ae-4c2d-affb-3213e750a319" />

### AND some relevant sources to further deep dive - 
<img width="1411" height="847" alt="image" src="https://github.com/user-attachments/assets/59f5c112-b101-403a-8940-421b5cb5dff0" />

## Future Scope
This is an MVP, which does good in terms of functionality, however, this is not perfect yet and I need to work on refining the relevant sources as sometimes unwanted information does come up. Further there is a scope of improving the LLM summary making it more factual with more metrics. Additionally, UI looks to be ok, the colors and themes can be improved. 




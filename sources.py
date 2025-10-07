from typing import Dict, List


# Default topics shown to the user
DEFAULT_TOPICS = ["politics", "markets", "finance", "sports", "entertainment", "tech"]


# Curated, reputable RSS sources per topic
TOPIC_FEEDS: Dict[str, List[str]] = {
"politics": [
"https://feeds.bbci.co.uk/news/politics/rss.xml",
"https://feeds.reuters.com/reuters/politicsNews",
"https://www.politico.com/rss/politics08.xml",
"https://apnews.com/hub/politics?utm_source=apnews.com&utm_medium=referral&utm_campaign=rss&output=atom",
"https://feeds.bloomberg.com/politics/news.rss"
],
"markets": [
"https://feeds.reuters.com/reuters/marketsNews",
"https://feeds.bbci.co.uk/news/business/rss.xml",
"https://www.cnbc.com/id/100003114/device/rss/rss.html",
"https://feeds.bloomberg.com/markets/news.rss"
],
"finance": [
"https://feeds.reuters.com/reuters/businessNews",
"https://www.investopedia.com/feedbuilder/feedbuilder.ashx?type=most-read",
"https://www.marketwatch.com/rss/topstories",
"https://finance.yahoo.com/news/rssindex"
],
"sports": [
"https://www.espn.com/espn/rss/news",
"https://feeds.bbci.co.uk/sport/rss.xml",
"https://apnews.com/hub/apf-sports?utm_source=apnews.com&utm_medium=referral&utm_campaign=rss&output=atom",
],
"entertainment": [
"https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
"https://variety.com/feed/",
"https://www.hollywoodreporter.com/feed/",
],
"tech": [
"https://feeds.arstechnica.com/arstechnica/technology-lab",
"https://www.theverge.com/rss/index.xml",
"https://feeds.bbci.co.uk/news/technology/rss.xml",
"https://www.ft.com/technology?format=rss",
"https://techcrunch.com/feed/",
"https://www.theguardian.com/us/technology/rss",
"https://feeds.a.dj.com/rss/RSSWSJD.xml",
"https://www.ft.com/technology?format=rss",
"https://feeds.bloomberg.com/technology/news.rss"

],
}
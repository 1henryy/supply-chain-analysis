"""
Tools for Agent 1: Disruption Monitoring.
Fetches real news signals from multiple configurable sources (Google News RSS,
NewsAPI.org, GDELT, custom RSS feeds), classifies disruption types, and resolves
entity mentions to known suppliers in the knowledge graph.

Supported news sources:
  - Google News RSS (default, free, no API key)
  - NewsAPI.org (set NEWS_API_KEY in .env, free tier 100 req/day)
  - GDELT Project (free, no key, event-based disruption monitoring)
  - Custom RSS feeds (any URL)
  - Manual alerts (supplier advisories, ERP signals)
"""

import json
import os
import re
import sys
import requests
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import src.db_service as _db

_NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")


def fetch_disruption_signals(query: str = "supply chain disruption") -> str:
    """Fetch recent news from Google News RSS (free, no API key needed).

    Args:
        query: Search query for finding disruption-related news. Examples:
               'semiconductor shortage', 'shipping delay Red Sea',
               'supply chain disruption automotive', 'factory shutdown earthquake'.

    Returns:
        JSON with list of recent news articles including title, source, and snippet.
    """
    try:
        encoded_query = quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        articles = _parse_rss_xml(resp.text)

        if not articles:
            return json.dumps({"status": "no_results", "source": "google_news", "query": query, "articles": []})

        return json.dumps({"status": "ok", "source": "google_news", "query": query, "count": len(articles), "articles": articles})

    except Exception as e:
        return json.dumps({"status": "error", "source": "google_news", "message": str(e), "query": query})


def fetch_news_from_api(query: str = "supply chain disruption", source: str = "newsapi") -> str:
    """Fetch news from a configured news API (NewsAPI.org or GDELT).

    Requires NEWS_API_KEY in .env for NewsAPI.org. GDELT is free with no key.

    Args:
        query: Search query for disruption-related news.
        source: Which API to use: 'newsapi' (NewsAPI.org) or 'gdelt' (GDELT Project).

    Returns:
        JSON with articles from the selected news API.
    """
    if source == "gdelt":
        return _fetch_gdelt(query)
    elif source == "newsapi":
        return _fetch_newsapi(query)
    else:
        return json.dumps({"status": "error", "message": f"Unknown source: {source}. Use 'newsapi' or 'gdelt'."})


def fetch_from_rss_feed(rss_url: str) -> str:
    """Fetch articles from any custom RSS feed URL.

    Use this to monitor specific industry news sources, supplier advisory feeds,
    regulatory announcement feeds, or regional news outlets.

    Args:
        rss_url: Full URL to an RSS/Atom feed. Examples:
                 'https://feeds.reuters.com/reuters/businessNews'
                 'https://www.supplychaindive.com/feeds/news/'

    Returns:
        JSON with parsed articles from the RSS feed.
    """
    try:
        resp = requests.get(rss_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        articles = _parse_rss_xml(resp.text)

        if not articles:
            return json.dumps({"status": "no_results", "source": "custom_rss", "feed_url": rss_url, "articles": []})

        return json.dumps({
            "status": "ok",
            "source": "custom_rss",
            "feed_url": rss_url,
            "count": len(articles),
            "articles": articles,
        })
    except Exception as e:
        return json.dumps({"status": "error", "source": "custom_rss", "message": str(e), "feed_url": rss_url})


def ingest_manual_alert(
    title: str,
    description: str,
    source_type: str = "supplier_advisory",
    severity: str = "medium",
    affected_region: str = "",
) -> str:
    """Ingest a manual disruption alert (supplier advisory, ERP signal, internal report).

    Use this for signals that don't come from news feeds: supplier notifications,
    quality audit failures, ERP system alerts, logistics partner updates, etc.

    Args:
        title: Brief title of the alert.
        description: Full description of the disruption signal.
        source_type: Type of source: 'supplier_advisory', 'erp_signal', 'internal_report',
                     'regulatory_filing', 'social_media'.
        severity: Estimated severity: 'low', 'medium', 'high', 'critical'.
        affected_region: Geographic region affected (optional).

    Returns:
        JSON with the alert formatted for downstream pipeline processing.
    """
    alert = {
        "status": "ok",
        "source": source_type,
        "count": 1,
        "articles": [{
            "title": title,
            "source": source_type,
            "published": "manual_input",
            "snippet": description[:500],
            "severity_hint": severity,
            "affected_region_hint": affected_region,
        }],
    }
    return json.dumps(alert)


# ---------------------------------------------------------------------------
# Internal helpers for news API sources
# ---------------------------------------------------------------------------

def _fetch_newsapi(query: str) -> str:
    """Fetch from NewsAPI.org (requires NEWS_API_KEY)."""
    if not _NEWS_API_KEY:
        return json.dumps({
            "status": "error",
            "source": "newsapi",
            "message": "NEWS_API_KEY not set in .env. Get a free key at https://newsapi.org/register",
        })

    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "pageSize": 8,
                "language": "en",
                "apiKey": _NEWS_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for a in data.get("articles", [])[:8]:
            articles.append({
                "title": a.get("title", "Unknown"),
                "source": a.get("source", {}).get("name", "Unknown"),
                "published": a.get("publishedAt", "Unknown"),
                "snippet": (a.get("description") or "")[:200],
                "url": a.get("url", ""),
            })

        return json.dumps({"status": "ok", "source": "newsapi", "query": query, "count": len(articles), "articles": articles})

    except Exception as e:
        return json.dumps({"status": "error", "source": "newsapi", "message": str(e)})


def _fetch_gdelt(query: str) -> str:
    """Fetch from GDELT Project (free, no API key needed).

    GDELT monitors news worldwide and is excellent for geopolitical events,
    natural disasters, and supply chain disruptions.
    """
    try:
        encoded_query = quote(query)
        resp = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query,
                "mode": "ArtList",
                "maxrecords": "8",
                "format": "json",
                "sort": "DateDesc",
            },
            timeout=15,
        )
        resp.raise_for_status()

        # GDELT sometimes returns empty or non-JSON for rare queries
        try:
            data = resp.json()
        except Exception:
            return json.dumps({"status": "no_results", "source": "gdelt", "query": query, "articles": []})

        articles = []
        for a in data.get("articles", [])[:8]:
            articles.append({
                "title": a.get("title", "Unknown").strip(),
                "source": a.get("domain", "Unknown"),
                "published": a.get("seendate", "Unknown"),
                "snippet": a.get("title", "").strip()[:200],
                "url": a.get("url", ""),
            })

        if not articles:
            return json.dumps({"status": "no_results", "source": "gdelt", "query": query, "articles": []})

        return json.dumps({"status": "ok", "source": "gdelt", "query": query, "count": len(articles), "articles": articles})

    except Exception as e:
        return json.dumps({"status": "error", "source": "gdelt", "message": str(e)})


def _parse_rss_xml(xml_text: str) -> list[dict]:
    """Parse RSS/Atom XML into a list of article dicts."""
    articles = []
    items = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    if not items:
        # Try Atom format
        items = re.findall(r"<entry>(.*?)</entry>", xml_text, re.DOTALL)

    for item in items[:8]:
        title = re.search(r"<title[^>]*>(.*?)</title>", item)
        source = re.search(r"<source.*?>(.*?)</source>", item)
        pub_date = re.search(r"<pubDate>(.*?)</pubDate>", item)
        if not pub_date:
            pub_date = re.search(r"<published>(.*?)</published>", item)
        if not pub_date:
            pub_date = re.search(r"<updated>(.*?)</updated>", item)
        description = re.search(r"<description>(.*?)</description>", item)
        if not description:
            description = re.search(r"<summary[^>]*>(.*?)</summary>", item)
        link = re.search(r"<link[^>]*href=[\"'](.*?)[\"']", item)
        if not link:
            link = re.search(r"<link>(.*?)</link>", item)

        articles.append({
            "title": _clean_html(title.group(1)) if title else "Unknown",
            "source": (source.group(1) if source else "Unknown"),
            "published": pub_date.group(1) if pub_date else "Unknown",
            "snippet": _clean_html(description.group(1))[:200] if description else "",
        })

    return articles


def classify_disruption_type(headline: str, snippet: str) -> str:
    """Classify a disruption signal into a category based on headline and snippet text.

    Args:
        headline: The news article headline.
        snippet: A brief description or snippet from the article.

    Returns:
        JSON with disruption_type, confidence, and affected_sectors.
        Types: geopolitical, natural_disaster, supplier_failure, shipping, cyber, economic, regulatory.
    """
    text = f"{headline} {snippet}".lower()

    classifications = {
        "geopolitical": ["sanction", "tariff", "trade war", "embargo", "geopolit", "conflict", "tension",
                         "export restrict", "import ban", "political"],
        "natural_disaster": ["earthquake", "typhoon", "hurricane", "flood", "tsunami", "wildfire",
                             "volcano", "storm", "drought", "climate"],
        "supplier_failure": ["bankrupt", "insolvency", "shutdown", "closure", "quality issue",
                             "recall", "default", "financial trouble"],
        "shipping": ["port congestion", "shipping delay", "container shortage", "freight",
                     "logistics", "red sea", "suez", "panama canal", "route disruption"],
        "cyber": ["cyber attack", "ransomware", "data breach", "hack", "malware"],
        "economic": ["recession", "inflation", "demand drop", "market crash", "price spike"],
        "regulatory": ["regulation", "compliance", "environmental law", "safety standard", "fda", "eu regulation"],
    }

    scores = {}
    for dtype, keywords in classifications.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[dtype] = score

    if not scores:
        return json.dumps({
            "disruption_type": "unknown",
            "confidence": 0.3,
            "affected_sectors": ["general"],
        })

    best_type = max(scores, key=scores.get)
    max_score = scores[best_type]
    confidence = min(0.5 + max_score * 0.15, 0.95)

    # Identify affected sectors
    sector_keywords = {
        "semiconductor": ["chip", "semiconductor", "wafer", "fab", "silicon"],
        "automotive": ["automotive", "car", "vehicle", "ev", "motor"],
        "electronics": ["electronics", "pcb", "circuit", "component"],
        "battery": ["battery", "lithium", "cell", "energy storage"],
        "mining": ["mining", "rare earth", "mineral", "cobalt", "copper"],
    }
    affected = [sector for sector, kws in sector_keywords.items() if any(kw in text for kw in kws)]

    return json.dumps({
        "disruption_type": best_type,
        "confidence": round(confidence, 2),
        "affected_sectors": affected or ["general"],
    })


def extract_affected_entities(headline: str, snippet: str) -> str:
    """Extract potentially affected geographic regions and industries from disruption news.

    Args:
        headline: The news article headline.
        snippet: A brief description or snippet from the article.

    Returns:
        JSON with affected_regions, affected_industries, and severity_estimate.
    """
    text = f"{headline} {snippet}".lower()

    regions = {
        "Taiwan": ["taiwan", "hsinchu", "tsmc", "taiwanese"],
        "China": ["china", "chinese", "beijing", "shanghai", "shenzhen"],
        "South Korea": ["south korea", "korean", "seoul", "samsung"],
        "Japan": ["japan", "japanese", "tokyo", "osaka"],
        "USA": ["united states", "us ", "american", "texas", "california"],
        "Germany": ["germany", "german", "munich", "berlin"],
        "India": ["india", "indian", "mumbai", "delhi"],
        "Chile": ["chile", "chilean", "santiago"],
        "Peru": ["peru", "peruvian", "lima"],
        "Malaysia": ["malaysia", "malaysian", "penang"],
        "Red Sea": ["red sea", "suez", "houthi", "yemen"],
        "Southeast Asia": ["southeast asia", "asean", "vietnam", "thailand"],
    }

    industries = {
        "semiconductor": ["semiconductor", "chip", "wafer", "fab", "silicon", "processor"],
        "pcb_assembly": ["pcb", "circuit board", "printed circuit"],
        "battery": ["battery", "lithium", "ev battery", "cell"],
        "sensors": ["sensor", "lidar", "radar", "camera module"],
        "mining": ["mining", "rare earth", "mineral", "ore", "cobalt"],
        "chemicals": ["chemical", "reagent", "solvent"],
        "shipping": ["shipping", "freight", "container", "port"],
    }

    matched_regions = [r for r, kws in regions.items() if any(kw in text for kw in kws)]
    matched_industries = [i for i, kws in industries.items() if any(kw in text for kw in kws)]

    # Severity heuristics
    severity = "medium"
    high_severity_words = ["critical", "severe", "major", "devastating", "halt", "shutdown", "crisis"]
    low_severity_words = ["minor", "slight", "temporary", "brief", "small"]

    if any(w in text for w in high_severity_words):
        severity = "high"
    elif any(w in text for w in low_severity_words):
        severity = "low"

    return json.dumps({
        "affected_regions": matched_regions or ["Unknown"],
        "affected_industries": matched_industries or ["general"],
        "severity_estimate": severity,
    })


def resolve_entities_to_suppliers(text: str) -> str:
    """Resolve entity mentions in text to known suppliers in the knowledge graph.

    Maps company names, regions, and industries from unstructured news to actual
    supplier IDs in the database. Uses fuzzy keyword matching.
    (Per AlMahri et al. 2025 resolve_entity_struct pattern.)

    Args:
        text: Unstructured text containing entity mentions (e.g., news article text).

    Returns:
        JSON with matched suppliers, their IDs, and confidence scores.
    """
    snapshot = _db.get_full_supply_chain_snapshot()
    suppliers = snapshot["suppliers"]
    text_lower = text.lower()

    matches = []
    for s in suppliers:
        score = 0.0
        reasons = []

        # Name match (exact or partial)
        name_lower = s["name"].lower()
        name_parts = name_lower.split()
        if name_lower in text_lower:
            score += 0.9
            reasons.append("exact_name_match")
        else:
            part_hits = sum(1 for p in name_parts if len(p) > 3 and p in text_lower)
            if part_hits > 0:
                score += 0.3 * part_hits
                reasons.append(f"partial_name_match({part_hits}_words)")

        # Region match
        if s["region"].lower() in text_lower:
            score += 0.2
            reasons.append("region_match")

        # Industry match
        industry_keywords = {
            "semiconductor": ["semiconductor", "chip", "wafer", "fab"],
            "pcb_assembly": ["pcb", "circuit board", "assembly"],
            "battery": ["battery", "lithium", "cell"],
            "sensors": ["sensor", "lidar", "camera"],
            "mining": ["mining", "rare earth", "mineral"],
            "chemicals": ["chemical", "reagent"],
            "optics": ["optics", "lens", "optical"],
        }
        ind = s["industry"].lower()
        for ind_key, kws in industry_keywords.items():
            if ind_key in ind and any(kw in text_lower for kw in kws):
                score += 0.15
                reasons.append("industry_match")
                break

        if score >= 0.2:
            matches.append({
                "supplier_id": s["id"],
                "supplier_name": s["name"],
                "tier": s["tier"],
                "region": s["region"],
                "confidence": round(min(score, 1.0), 2),
                "match_reasons": reasons,
            })

    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return json.dumps({
        "matches": matches[:10],
        "total_matches": len(matches),
        "query_text_preview": text[:100],
    })


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    return re.sub(r"<[^>]+>", "", text).strip()

import aiohttp
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict
from backend.config import logger, client
from backend.config import SERP_API_KEY, GNEWS_API_KEY

async def get_bio(subject: str) -> str:
    """Biography lookup using SerpAPI"""
    logger.info(f"📖 Getting biography for: {subject}")
    if not SERP_API_KEY:
        error_msg = f"❌ SerpAPI key not configured. Cannot get bio for {subject}"
        logger.error(error_msg)
        return error_msg

    url = "https://serpapi.com/search.json"
    params = {
        "q": f"{subject} biography who is",
        "api_key": SERP_API_KEY,
        "engine": "google",
        "num": 5,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                logger.info(f"📡 SerpAPI Bio Response: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Try knowledge graph first
                    knowledge_graph = data.get("knowledge_graph", {})
                    if knowledge_graph.get("description"):
                        bio = f"Biography of {subject}: {knowledge_graph['description']}"
                        if knowledge_graph.get("title"):
                            bio = f"{knowledge_graph['title']}: {knowledge_graph['description']}"
                        return bio
                    
                    # Fallback to organic results
                    organic_results = data.get("organic_results", [])
                    if organic_results:
                        snippet = organic_results[0].get("snippet", "No snippet available")
                        return f"Biography of {subject}: {snippet}"
                    
                    return f"No biography found for {subject}"
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ SerpAPI Error {resp.status}: {error_text}")
                    return f"API error getting bio for {subject}"
    except Exception as e:
        logger.error(f"❌ Exception getting bio for {subject}: {str(e)}")
        return f"Error: {str(e)}"

async def search_images(subject: str, max_results: int = 2) -> List[dict]:
    """Search for images using SerpAPI"""
    logger.info(f"🖼️ Searching images for: {subject} (max: {max_results})")
    if not SERP_API_KEY:
        logger.error("❌ SerpAPI key not configured for image search")
        return [{"error": "SerpAPI key not configured"}]

    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_images",
        "q": subject,
        "num": max_results,
        "api_key": SERP_API_KEY,
        "safe": "active",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                logger.info(f"📡 Image Search Response: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    images_results = data.get("images_results", [])
                    results = []
                    for img in images_results[:max_results]:
                        if img.get("original"):
                            results.append({
                                "title": img.get("title", "Untitled"),
                                "url": img.get("original"),
                                "thumbnail": img.get("thumbnail"),
                                "source": img.get("source", "Unknown"),
                            })
                    logger.info(f"✅ Found {len(results)} images for {subject}")
                    return results
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Image Search Error {resp.status}: {error_text}")
                    return [{"error": f"API error ({resp.status})"}]
    except Exception as e:
        logger.error(f"❌ Exception searching images for {subject}: {str(e)}")
        return [{"error": str(e)}]

async def get_news(topic: str, max_items: int = 3) -> List[dict]:
    """Get news articles using GNews API - limited to 2 items to prevent truncation"""
    logger.info(f"📰 Getting news for: {topic} (max: {max_items})")
    if not GNEWS_API_KEY:
        logger.error("❌ GNews API key not configured")
        return [{"error": "GNews API key not configured"}]

    url = "https://gnews.io/api/v4/search"
    params = {
        "q": topic,
        "max": max_items,
        "apikey": GNEWS_API_KEY,
        "lang": "en",
        "sortby": "publishedAt",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                logger.info(f"📡 GNews Response: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    articles = data.get("articles", [])
                    results = []
                    for article in articles:
                        if article.get("title"):
                            results.append({
                                "title": article.get("title"),
                                "url": article.get("url"),
                                "description": article.get("description", ""),
                                "publishedAt": article.get("publishedAt", ""),
                                "source": article.get("source", {}).get("name", "Unknown"),
                                "image": article.get("image", ""),
                            })
                    logger.info(f"✅ Found {len(results)} news articles for {topic}")
                    return results
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ GNews Error {resp.status}: {error_text}")
                    return [{"error": f"API error ({resp.status})"}]
    except Exception as e:
        logger.error(f"❌ Exception getting news for {topic}: {str(e)}")
        return [{"error": str(e)}]

# Minimal changes to your existing function - NOW PRIORITIZES FRESH RESULTS FOR ALL QUERIES
async def web_search(query: str, num_results: int = 5) -> List[dict]:
    """Perform web search using SerpAPI - enhanced for fresh results on ALL queries"""
    logger.info(f"🔍 Web searching for: {query} (max: {num_results})")
    if not SERP_API_KEY:
        logger.error("❌ SerpAPI key not configured for web search")
        return [{"error": "SerpAPI key not configured"}]

    from datetime import datetime
    current_year = datetime.now().strftime("%Y")
    current_month_year = datetime.now().strftime("%B %Y")
    
    # ALWAYS enhance queries for freshness - not just financial
    enhanced_query = f"{query} {current_year} latest recent"
    
    # Add specific terms based on query type
    financial_keywords = ['nifty', 'sensex', 'stock', 'price', 'index', 'bse', 'nse', 'market']
    is_financial_query = any(keyword.lower() in query.lower() for keyword in financial_keywords)
    
    if is_financial_query:
        enhanced_query = f"{query} {current_month_year} live current today"
    elif any(word in query.lower() for word in ['news', 'update', 'latest', 'breaking']):
        enhanced_query = f"{query} {current_year} today latest news"
    elif any(word in query.lower() for word in ['now', 'current', 'today']):
        enhanced_query = f"{query} {current_year} current today"

    url = "https://serpapi.com/search.json"
    params = {
        "q": enhanced_query,  # Use enhanced query
        "num": num_results,
        "api_key": SERP_API_KEY,
        "engine": "google",
        "gl": "in",  # India-specific results
        "hl": "en",  # English language
    }
    
    # APPLY DATE FILTERING FOR ALL QUERIES - not just financial
    if any(word in query.lower() for word in ['now', 'today', 'current']) or is_financial_query:
        params["tbs"] = "qdr:d"  # Past day for urgent queries
    elif any(word in query.lower() for word in ['latest', 'recent', 'news', 'update']):
        params["tbs"] = "qdr:w"  # Past week for recent queries  
    else:
        params["tbs"] = "qdr:m"  # Past month for general queries (still fresh!)

    logger.info(f"🎯 Enhanced query: {enhanced_query}")
    logger.info(f"📅 Date filter applied: {params.get('tbs', 'none')}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                logger.info(f"📡 Web Search Response: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    organic_results = data.get("organic_results", [])
                    results = []
                    for result in organic_results[:num_results]:
                        if result.get("title"):
                            results.append({
                                "title": result.get("title"),
                                "url": result.get("link"),
                                "snippet": result.get("snippet", ""),
                                "source": result.get("source", ""),
                            })
                    logger.info(f"✅ Found {len(results)} web search results for {enhanced_query}")
                    return results
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Web Search Error {resp.status}: {error_text}")
                    return [{"error": f"API error ({resp.status})"}]
    except Exception as e:
        logger.error(f"❌ Exception searching web for {query}: {str(e)}")
        return [{"error": str(e)}]
    
async def get_datetime() -> dict:
    """Get current datetime in IST"""
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    return {
        "iso": now_ist.isoformat(),
        "pretty": now_ist.strftime("%A, %B %d, %Y at %I:%M %p %Z"),
        "date_only": now_ist.strftime("%A, %B %d, %Y"),
        "time_only": now_ist.strftime("%I:%M %p %Z"),
    }

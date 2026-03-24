import asyncio
from urllib.parse import urlparse # Re-adding this as it's used later in the code

# crawl4ai imports — install with: pip install crawl4ai
# First-time setup (downloads browser): crawl4ai-setup
try:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    from crawl4ai.deep_crawling.filters import (
        FilterChain,
        URLPatternFilter,
        DomainFilter,
    )
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

# How many pages to crawl maximum (keep low to stay within LLM context)
MAX_PAGES = 10

# Character cap on total output — stays well within gpt-4o-mini context
MAX_CHARS = 8000

# Pages whose URLs suggest marketing-relevant content — prioritized
MARKETING_KEYWORDS = [
    "about", "story", "mission", "product", "feature", "service",
    "solution", "pricing", "case-study", "customer", "blog", "use-case"
]

# Pages to skip — not useful for brand understanding
SKIP_PATTERNS = [
    "login", "signup", "register", "checkout", "cart", "privacy",
    "terms", "cookie", "sitemap", "cdn", "static", "wp-admin"
]

# Fallback headers for requests-based scraper
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── crawl4ai-based crawler (primary) ─────────────────────────────────────────

async def _crawl_with_crawl4ai(url: str) -> str:
    """
    Uses crawl4ai to recursively crawl the website from the given URL.

    Strategy:
    - BFSDeepCrawlStrategy does breadth-first traversal of the site
    - DomainFilter keeps crawling within the same domain (no external links)
    - URLPatternFilter skips login pages, CDN assets, etc.
    - Returns clean markdown from each page, concatenated
    """
    domain = urlparse(url).netloc

    # Filter chain — controls which URLs get crawled
    filter_chain = FilterChain([
        # Stay on the same domain
        DomainFilter(allowed_domains=[domain]),
        # Skip irrelevant pages
        # crawl4ai 0.8+: use patterns= + reverse=True (acts as a blocklist)
        URLPatternFilter(
            patterns=[f"*{pattern}*" for pattern in SKIP_PATTERNS],
            reverse=True,  # reverse=True means: BLOCK URLs that match these patterns
        ),
    ])

    # BFS crawler — discovers pages level by level from the root URL
    deep_crawler = BFSDeepCrawlStrategy(
        max_depth=3,          # how many link-hops from the root URL
        max_pages=MAX_PAGES,  # hard cap on total pages
        filter_chain=filter_chain,
    )

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,  # always fetch fresh
        word_count_threshold=50,      # skip pages with barely any content
        remove_overlay_elements=True, # strip cookie banners, popups
        deep_crawl_strategy=deep_crawler,
        stream=True,                  # crawl4ai 0.8+: stream=True enables async-for iteration
    )

    collected_sections = []

    async with AsyncWebCrawler() as crawler:
        async for result in await crawler.arun(url, config=config):
            if result.success and result.markdown:
                # Label each page so Agent 1 knows where content came from
                page_path = urlparse(result.url).path or "/"
                section = f"[Page: {page_path}]\n{result.markdown.strip()}\n"
                collected_sections.append(section)

    if not collected_sections:
        raise ValueError(f"crawl4ai returned no content from {url}")

    # Join all pages and cap at MAX_CHARS
    full_content = "\n\n".join(collected_sections)
    return full_content[:MAX_CHARS]


# ── requests fallback scraper (if crawl4ai not installed) ─────────────────────

def _fallback_scrape(url: str) -> str:
    """
    Simple requests + BeautifulSoup scraper.
    Used when crawl4ai is not installed OR if crawl4ai hits an error.
    Scrapes the homepage only — less thorough but always available.
    """
    print("[Scraper] Using fallback scraper (homepage only — no JS rendering).")
    print("[Scraper] Tip: ensure crawl4ai is installed + run: crawl4ai-setup")

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except Exception as e:
        raise ValueError(f"Could not fetch {url}: {e}")

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove noise elements
    for tag in soup.find_all(["nav", "footer", "script", "style", "header"]):
        tag.decompose()

    parts = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        text = tag.get_text(separator=" ", strip=True)
        if text and len(text) > 30:
            parts.append(text)

    content = "\n".join(parts)
    return content[:MAX_CHARS]


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_brand_website(url: str) -> str:
    """
    Crawls a brand's website and returns clean text content.

    If crawl4ai is installed: recursively crawls up to MAX_PAGES pages,
    returns clean markdown from all of them.

    If crawl4ai is not installed: falls back to scraping the homepage only.

    Args:
        url: Brand website URL (e.g. "https://zenfit.io")

    Returns:
        str: Clean text content from the website, max MAX_CHARS characters

    Raises:
        ValueError: If the website cannot be fetched at all
    """
    # Normalize URL
    if not url.startswith("http"):
        url = "https://" + url
    url = url.rstrip("/")

    if CRAWL4AI_AVAILABLE:
        print(f"[Scraper] Crawling {url} with crawl4ai (max {MAX_PAGES} pages)...")
        try:
            content = asyncio.run(_crawl_with_crawl4ai(url))
            pages_scraped = content.count("[Page:")
            print(f"[Scraper] Crawled {pages_scraped} pages, {len(content)} chars extracted")
            return content
        except Exception as e:
            print(f"[Scraper] crawl4ai error: {e}. Falling back to simple scraper.")
            return _fallback_scrape(url)
    else:
        return _fallback_scrape(url)


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_url = "https://openai.com"
    print(f"Testing scraper on {test_url}\n")
    content = scrape_brand_website(test_url)
    print(content[:800])
    print(f"\n... ({len(content)} total chars extracted)")

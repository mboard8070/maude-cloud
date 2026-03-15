"""
Web tool implementations — web_browse, web_search, web_image_search.
Vision tools (web_view, view_image) require a vision-capable cloud model.
"""

from ..tool_registry import register_tool
from .log import log
from .paths import resolve_path


def tool_web_browse(url: str) -> str:
    """Fetch and parse web page content."""
    import requests
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "Error: beautifulsoup4 not installed. Run: pip install beautifulsoup4"

    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        log(f"Fetching {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'header', 'noscript', 'iframe']):
            tag.decompose()

        main_content = soup.find('main') or soup.find('article') or soup.find('div', {'class': ['content', 'post', 'article', 'main']})
        if main_content:
            text = main_content.get_text(separator='\n', strip=True)
        else:
            text = soup.get_text(separator='\n', strip=True)

        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        if len(text) > 15000:
            text = text[:15000] + "\n\n... (content truncated)"

        log(f"Retrieved {len(text)} chars from {url}")
        return f"Content from {url}:\n\n{text}"

    except Exception as e:
        return f"Error fetching {url}: {e}"


def tool_web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from ddgs import DDGS
    except ImportError:
        return "Error: ddgs not installed. Run: pip install ddgs"

    try:
        num_results = min(max(1, num_results), 10)
        log(f"Searching: {query}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        if not results:
            return f"No results found for: {query}"

        output = f"Search results for: {query}\n\n"
        for i, r in enumerate(results, 1):
            output += f"{i}. {r.get('title', 'No title')}\n"
            output += f"   URL: {r.get('href', 'No URL')}\n"
            output += f"   {r.get('body', 'No description')}\n\n"

        log(f"Found {len(results)} results")
        return output
    except Exception as e:
        return f"Error searching: {e}"


def tool_web_image_search(query: str, num_results: int = 5) -> str:
    """Search the web for images using DuckDuckGo."""
    try:
        from ddgs import DDGS
    except ImportError:
        return "Error: ddgs not installed. Run: pip install ddgs"

    try:
        num_results = min(max(1, num_results), 10)
        log(f"Image search: {query}")
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=num_results))
        if not results:
            return f"No image results found for: {query}"

        output = f"Image search results for: {query}\n\n"
        for i, r in enumerate(results, 1):
            img_url = r.get("image", "")
            title = r.get("title", "Image")
            source = r.get("source", "")
            if img_url.startswith("http://"):
                img_url = "https://" + img_url[7:]
            output += f"{i}. {title}\n"
            output += f"   ![{title}]({img_url})\n"
            if source:
                output += f"   Source: {source}\n"
            output += "\n"

        log(f"Found {len(results)} image results")
        return output
    except Exception as e:
        return f"Error searching images: {e}"


def tool_web_view(url: str, question: str = None) -> str:
    """Screenshot a webpage and describe it (requires browser + vision model)."""
    return "web_view is not available in the cloud-only package (requires local vision model). Use web_browse instead to fetch page content as text."


def tool_view_image(path: str, question: str = None) -> str:
    """Analyze a local image (requires vision model)."""
    return "view_image is not available in the cloud-only package (requires local vision model). You can share images via the share_file tool."


# ── Registry wrappers ──────────────────────────────────────────

@register_tool("web_browse", cacheable=True)
def _dispatch_web_browse(args):
    return tool_web_browse(args.get("url", ""))

@register_tool("web_search", cacheable=True)
def _dispatch_web_search(args):
    return tool_web_search(args.get("query", ""), args.get("num_results", 5))

@register_tool("web_view", cacheable=True)
def _dispatch_web_view(args):
    return tool_web_view(args.get("url", ""), args.get("question"))

@register_tool("view_image", cacheable=True)
def _dispatch_view_image(args):
    return tool_view_image(args.get("path", ""), args.get("question"))

@register_tool("web_image_search", cacheable=True)
def _dispatch_web_image_search(args):
    return tool_web_image_search(args.get("query", ""), args.get("num_results", 5))

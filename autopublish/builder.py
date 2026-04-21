"""Site artifact builder for fromtheabysmal.net.

Generates individual post pages, index.html, rss.xml, and per-month archive
pages (/archive/YYYY-MM.html) from state and post content. No API calls —
deterministic Python only.
"""
import re
import logging
from collections import OrderedDict
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from autopublish.converter import _escape, _format_date

log = logging.getLogger(__name__)

# Fonts and external stylesheet links used on every page
_FONT_LINKS = """\
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Yrsa:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://use.typekit.net/unb6zxk.css">"""

_SITE_TITLE = "from the abysmal"

# Navigation links shown on the index and month-archive pages
_SITE_NAV = """\
<nav class="site-nav">
<a href="https://fromtheabysmal.substack.com">substack</a>
<span class="sep">·</span>
<a href="https://bookofappetite.com">book</a>
<span class="sep">·</span>
<a href="https://estherpatrizia.com">projects</a>
<span class="sep">·</span>
<a href="https://esther.news">news</a>
</nav>"""

_SITE_HEADER = """\
<header class="site-header">
<a href="/" class="site-title-link" id="site-title">
<img src="/title.png" alt="letters from the abysmal" class="site-title-img"
     onerror="this.style.display='none'; document.getElementById('site-title-text').style.display='block';">
<h1 id="site-title-text" class="site-title-text" style="display:none;">from the abysmal</h1>
</a>
</header>"""

_FOOTER = """\
<hr class="section-rule">
<footer class="site-footer">
<span>Copyright © Esther Olschowy 2026 · Bergisch Gladbach, Germany</span>
</footer>"""


def post_description(html_body: str) -> str:
    """Extract a plain-text description from post body HTML.

    Strips all HTML tags, collapses whitespace, and returns the first ~200
    characters trimmed to the last word boundary.
    """
    text = re.sub(r"<[^>]+>", "", html_body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= 200:
        return text
    truncated = text[:200]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


def render_post_page(
    title: str,
    slug: str,
    date: str,
    body_html: str,
    revision_dates: list,
    site_url: str,
) -> str:
    """Render a full HTML page for an individual post."""
    description = _escape(post_description(body_html))
    esc_title = _escape(title)
    formatted_date = _format_date(date)
    post_url = f"{site_url}/posts/{slug}.html"

    history_html = ""
    if revision_dates:
        latest = max(revision_dates)
        history_html = f'\n<p class="post-history">Last revised {_format_date(latest)}.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_FONT_LINKS}
<title>{esc_title} — {_SITE_TITLE}</title>
<link rel="canonical" href="{post_url}">
<meta property="og:title" content="{esc_title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{post_url}">
<meta property="og:type" content="article">
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/rss+xml" title="{_SITE_TITLE}" href="{site_url}/rss.xml">
</head>
<body>
{_SITE_HEADER}
<nav class="post-nav"><a href="/">← back to main</a></nav>
<article class="post post-single">
<div class="post-heading">
<h1>{esc_title}</h1>
<div class="post-meta">{formatted_date}</div>
</div>
<div class="post-body">
{body_html}{history_html}
</div>
<nav class="post-nav post-nav-bottom"><a href="/">← back to main</a></nav>
</article>
{_FOOTER}
</body>
</html>
"""


def render_index(posts: list, site_url: str, site_path: str) -> str:
    """Render the full index.html for the site.

    posts is the published list from state.json, newest-first.
    Inline-renders the 10 most recent posts; all posts appear in the archive nav.
    """
    site_path = Path(site_path)
    posts_dir = site_path / "posts"

    archive_html = _render_archive(posts)

    inline_articles = _render_inline_posts(posts[:10], posts_dir, site_url)
    posts_html = inline_articles or '<p class="loading">nothing here yet.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_FONT_LINKS}
<title>{_SITE_TITLE}</title>
<link rel="canonical" href="{site_url}/">
<meta property="og:title" content="{_SITE_TITLE}">
<meta property="og:url" content="{site_url}/">
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/rss+xml" title="{_SITE_TITLE}" href="{site_url}/rss.xml">
</head>
<body>
{_SITE_HEADER}
{_SITE_NAV}
{archive_html}
<main class="posts" id="posts">
{posts_html}
</main>
{_FOOTER}
</body>
</html>
"""


def render_month_archive(year: str, month: str, all_posts: list, site_url: str, site_path: str) -> str:
    """Render /archive/YYYY-MM.html — all posts from (year, month) rendered inline.

    all_posts is the full published list from state.json, newest-first, used to
    render the archive nav with the current month highlighted.
    """
    site_path = Path(site_path)
    posts_dir = site_path / "posts"
    prefix = f"{year}-{month}"

    month_posts = [p for p in all_posts if p["slug"].startswith(prefix)]
    month_posts.sort(key=lambda p: p["slug"][:10], reverse=True)

    archive_html = _render_archive(all_posts, current_month=prefix)
    inline_articles = _render_inline_posts(month_posts, posts_dir, site_url)
    posts_html = inline_articles or '<p class="loading">nothing here.</p>'

    month_title = datetime.strptime(f"{prefix}-01", "%Y-%m-%d").strftime("%B %Y")
    page_url = f"{site_url}/archive/{prefix}.html"
    esc_month_title = _escape(month_title)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_FONT_LINKS}
<title>{esc_month_title} — {_SITE_TITLE}</title>
<link rel="canonical" href="{page_url}">
<meta property="og:title" content="{esc_month_title} — {_SITE_TITLE}">
<meta property="og:url" content="{page_url}">
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/rss+xml" title="{_SITE_TITLE}" href="{site_url}/rss.xml">
</head>
<body>
{_SITE_HEADER}
{_SITE_NAV}
{archive_html}
<main class="posts" id="posts">
{posts_html}
</main>
{_FOOTER}
</body>
</html>
"""


def render_rss(posts: list, site_url: str, site_path: str) -> str:
    """Render an RSS 2.0 feed with the 20 most recent posts (full body)."""
    site_path = Path(site_path)
    posts_dir = site_path / "posts"
    now_rfc = format_datetime(datetime.utcnow())

    items = []
    for post in posts[:20]:
        slug = post["slug"]
        title = post["title"]
        post_url = f"{site_url}/posts/{slug}.html"
        post_file = posts_dir / f"{slug}.html"

        body_content = _extract_post_body(post_file) if post_file.exists() else ""
        pub_date = _date_to_rfc2822(slug[:10])

        esc_title = _xml_escape(title)
        esc_url = _xml_escape(post_url)

        items.append(f"""<item>
<title>{esc_title}</title>
<link>{esc_url}</link>
<guid isPermaLink="true">{esc_url}</guid>
<pubDate>{pub_date}</pubDate>
<description><![CDATA[{body_content}]]></description>
</item>""")

    items_str = "\n".join(items)
    esc_site_url = _xml_escape(site_url)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{_SITE_TITLE}</title>
<link>{esc_site_url}</link>
<description>{_SITE_TITLE}</description>
<lastBuildDate>{now_rfc}</lastBuildDate>
<atom:link href="{esc_site_url}/rss.xml" rel="self" type="application/rss+xml"/>
{items_str}
</channel>
</rss>
"""


def month_pages(posts: list) -> list:
    """Return list of (year, month) pairs that have posts, newest-first.

    posts is assumed newest-first; the returned list preserves that order.
    """
    pairs = OrderedDict()
    for post in posts:
        y, m = post["slug"][:4], post["slug"][5:7]
        pairs[(y, m)] = None
    return list(pairs.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_inline_posts(posts: list, posts_dir: Path, site_url: str) -> str:
    """Render a list of posts inline as <article class="post"> blocks with <h2> title links."""
    articles = []
    for i, post in enumerate(posts):
        slug = post["slug"]
        title = post["title"]
        date = slug[:10]
        post_url = f"{site_url}/posts/{slug}.html"
        post_file = posts_dir / f"{slug}.html"

        body_content = _extract_post_body(post_file) if post_file.exists() else ""

        if i > 0:
            articles.append('<hr class="post-separator">')

        articles.append(f"""<article class="post">
<div class="post-heading">
<h2><a href="{post_url}">{_escape(title)}</a></h2>
<div class="post-meta">{_format_date(date)}</div>
</div>
<div class="post-body">
{body_content}
</div>
</article>""")

    return "\n".join(articles)


def _render_archive(posts: list, current_month: str = None) -> str:
    """Render the archive nav: years collapse to month links only.

    current_month is None on the index, or "YYYY-MM" on a month-archive page —
    in which case that month's link gets the `current` class.
    """
    by_year = OrderedDict()
    for post in posts:
        date_str = post["slug"][:10]
        year, month = date_str[:4], date_str[5:7]
        by_year.setdefault(year, OrderedDict())[month] = None

    year_blocks = []
    for year, months in by_year.items():
        month_links = []
        for m in months:
            month_name = datetime.strptime(f"{year}-{m}-01", "%Y-%m-%d").strftime("%B")
            cls = "archive-month-link"
            if current_month == f"{year}-{m}":
                cls += " current"
            month_links.append(f'<a class="{cls}" href="/archive/{year}-{m}.html">{month_name}</a>')
        months_html = "\n".join(month_links)
        year_blocks.append(
            f'<details class="archive-year-group">\n'
            f'<summary class="archive-year-label">{year}</summary>\n'
            f'<div class="archive-months">\n{months_html}\n</div>\n'
            f'</details>'
        )

    years_html = "\n".join(year_blocks)
    return (
        f'<nav class="archive-bar" id="archive-bar">\n'
        f'<div class="archive-years">\n{years_html}\n</div>\n'
        f'</nav>'
    )


def _extract_post_body(post_file: Path) -> str:
    """Extract the inner content of <div class="post-body"> from a post HTML file.

    Handles both the new format (post-body div inside article) and the old bare
    fragment format (raw paragraphs in body, h1 at top).
    """
    html = post_file.read_text(encoding="utf-8")

    start_tag = '<div class="post-body">'
    end_marker = '</article>'
    start = html.find(start_tag)
    end = html.find(end_marker)

    if start != -1 and end != -1:
        inner_start = start + len(start_tag)
        closing = html.rfind("</div>", inner_start, end)
        if closing != -1:
            return html[inner_start:closing].strip()

    body_match = re.search(r"<body>(.*?)</body>", html, re.DOTALL)
    if body_match:
        content = body_match.group(1)
        content = re.sub(r"<h1>.*?</h1>\s*", "", content, flags=re.DOTALL)
        return content.strip()

    return ""


def _date_to_rfc2822(date_str: str) -> str:
    """Convert YYYY-MM-DD to RFC 2822 format for RSS pubDate."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return format_datetime(dt)
    except ValueError:
        return date_str


def _xml_escape(text: str) -> str:
    """Escape text for use in XML attributes and text nodes."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

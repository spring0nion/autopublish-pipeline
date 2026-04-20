import re
from datetime import datetime


def text_to_html(title, text, revision_dates=None):
    """Convert Markdown text to the post HTML format used by fromtheabysmal.net.

    Matches the existing format:
    - <!doctype html>, <html>, <head> with charset meta + <title>
    - <body> with <h1> title and <p> paragraphs or <hr> dividers
    - No classes, no CSS link, no wrappers
    """
    # Strip leading markdown heading if it matches the title (iA Writer drafts often start with # Title)
    text = _strip_title_heading(text, title)
    blocks = _split_blocks(text)
    blocks, footnote_texts = _extract_footnotes(blocks)
    _FN_RE = re.compile(r"\x00fn(\d+)\x00")

    def _apply_inline(text):
        html = _inline_markdown(_escape(text))
        return _FN_RE.sub(
            lambda m: f'<sup><a href="#fn{m.group(1)}" id="fnr{m.group(1)}">{m.group(1)}</a></sup>',
            html,
        )

    body_parts = []
    for block in blocks:
        if block == "---":
            body_parts.append('<p class="post-divider">· · ·</p>')
        elif block.startswith(_LIST_MARKER):
            body_parts.append(_list_block_to_html(block[len(_LIST_MARKER):], _apply_inline))
        else:
            body_parts.append(f"<p>{_apply_inline(block)}</p>")
    body_html = "\n".join(body_parts)

    footnotes_html = ""
    if footnote_texts:
        items = []
        for i, ft in enumerate(footnote_texts, 1):
            ft_html = _inline_markdown(_escape(ft))
            items.append(f'<li id="fn{i}"><p>{ft_html} <a href="#fnr{i}">↩︎</a></p></li>')
        footnotes_html = '\n<div class="footnotes">\n<ol>\n' + "\n".join(items) + "\n</ol>\n</div>"

    history_html = ""
    if revision_dates:
        seen = set()
        unique_dates = [d for d in revision_dates if not (d in seen or seen.add(d))]
        formatted = " \u00b7 ".join(_format_date(d) for d in unique_dates)
        history_html = f'\n<p class="post-history">Revised {formatted}.</p>'

    return f"""<!doctype html>
<html>
<head>
\t<meta charset="UTF-8">
\t<title>{_escape(title)}</title>
</head>
<body>
<h1>{_escape(title)}</h1>

{body_html}{footnotes_html}{history_html}
</body>
</html>
"""


_LIST_MARKER = "\x01LIST\x01"
_LIST_LINE_RE = re.compile(r"^(\t*)- (.+)$")


def _split_blocks(text):
    """Split text into blocks on double newlines.

    Returns a list of strings where each item is either '---' (a divider),
    a _LIST_MARKER-prefixed string (a markdown list block), or a paragraph
    string (with internal soft-wraps collapsed to spaces).
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_paras = re.split(r"\n\s*\n", text.strip())
    blocks = []
    for p in raw_paras:
        p = p.strip()
        if not p:
            continue
        if re.fullmatch(r"-{3,}", p):
            blocks.append("---")
        elif _LIST_LINE_RE.match(p.split("\n")[0]):
            blocks.append(_LIST_MARKER + p)
        else:
            p = re.sub(r"\n", " ", p)
            p = re.sub(r"  +", " ", p)
            blocks.append(p)
    return blocks


def _list_block_to_html(text, inline_fn):
    """Convert a tab-indented markdown list block to nested <ul><li> HTML."""
    parsed = [
        (len(m.group(1)), inline_fn(m.group(2).strip()))
        for line in text.split("\n")
        if line.strip() and (m := _LIST_LINE_RE.match(line))
    ]
    if not parsed:
        return ""

    result = []
    depth_stack = []

    for i, (indent, content) in enumerate(parsed):
        next_indent = parsed[i + 1][0] if i + 1 < len(parsed) else -1

        if not depth_stack:
            result.append("<ul>")
            depth_stack.append(indent)
        elif indent > depth_stack[-1]:
            result.append("<ul>")
            depth_stack.append(indent)
        elif indent < depth_stack[-1]:
            while depth_stack and depth_stack[-1] > indent:
                result.append("</ul></li>")
                depth_stack.pop()

        if next_indent > indent:
            result.append(f"<li>{content}")
        else:
            result.append(f"<li>{content}</li>")

    while len(depth_stack) > 1:
        result.append("</ul></li>")
        depth_stack.pop()
    result.append("</ul>")

    return "\n".join(result)


def _extract_footnotes(blocks):
    """Replace [^footnote text] with null-byte placeholders; return (blocks, texts)."""
    footnotes = []

    def replacer(m):
        footnotes.append(m.group(1))
        return f"\x00fn{len(footnotes)}\x00"

    processed = []
    for block in blocks:
        if block == "---":
            processed.append(block)
        else:
            processed.append(re.sub(r"\[\^([^\]]+)\]", replacer, block))
    return processed, footnotes


def _inline_markdown(text):
    """Convert inline Markdown in already-HTML-escaped text to HTML tags.

    Handles **bold**, *italic*, __bold__, _italic_.
    Must run AFTER _escape() so we're not double-escaping.
    """
    # Bold before italic so **x** isn't parsed as *(*x*)*
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
    return text


def _strip_title_heading(text, title):
    """Remove a leading # heading line if the draft starts with one."""
    lines = text.lstrip().split("\n", 1)
    first = lines[0].strip()
    if first.startswith("#"):
        # Remove the heading — we generate our own <h1>
        return lines[1] if len(lines) > 1 else ""
    return text


def _escape(text):
    """Minimal HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_date(date_str):
    """Format a YYYY-MM-DD string as 'Month D, YYYY' (e.g. 'April 16, 2026')."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%B %-d, %Y")
    except ValueError:
        return date_str

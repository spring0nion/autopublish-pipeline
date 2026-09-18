import re
from datetime import datetime


def text_to_html(title, text):
    """Convert Markdown text to the inner body HTML for a post.

    Returns the paragraph/list/footnote HTML only — no doctype, no <head>,
    no <h1>, no revision dates. The caller (builder.py) wraps this in the
    full page template.
    """
    text = _strip_title_heading(text, title)
    text, footnote_texts = _extract_footnotes(text)
    blocks = _split_blocks(text)
    _FN_RE = re.compile(r"\x00fn(\d+)\x00")

    # Pre-render each footnote as inline HTML for the hover/tap popup.
    # Paragraph breaks become <br><br> so the popup can live inside <sup>.
    footnote_popups = []
    for ft in footnote_texts:
        paras = [p.strip() for p in re.split(r"\n\s*\n", ft.strip()) if p.strip()]
        para_htmls = [_inline_markdown(_escape(re.sub(r"\s*\n\s*", " ", p))) for p in paras]
        footnote_popups.append("<br><br>".join(para_htmls))

    def _apply_inline(text):
        html = _inline_markdown(_escape(text))

        def _fn_repl(m):
            i = int(m.group(1))
            popup = footnote_popups[i - 1] if i - 1 < len(footnote_popups) else ""
            return (
                f'<sup class="fn-ref" tabindex="0" id="fnr{i}">{i}'
                f'<span class="fn-popup" role="tooltip">{popup}</span></sup>'
            )

        return _FN_RE.sub(_fn_repl, html)

    body_parts = []
    for block in blocks:
        if block == "---":
            body_parts.append('<p class="post-divider">· · ·</p>')
        elif block.startswith(_LIST_MARKER):
            body_parts.append(_list_block_to_html(block[len(_LIST_MARKER):], _apply_inline))
        elif block.startswith(_BLOCKQUOTE_MARKER):
            body_parts.append(_blockquote_block_to_html(block[len(_BLOCKQUOTE_MARKER):], _apply_inline))
        else:
            body_parts.append(f"<p>{_apply_inline(block)}</p>")
    body_html = "\n".join(body_parts)

    if footnote_texts:
        items = []
        for i, ft in enumerate(footnote_texts, 1):
            paras = [p.strip() for p in re.split(r"\n\s*\n", ft.strip()) if p.strip()]
            if not paras:
                paras = [""]
            para_htmls = [_inline_markdown(_escape(re.sub(r"\s*\n\s*", " ", p))) for p in paras]
            para_htmls[-1] = f'{para_htmls[-1]} <a href="#fnr{i}">↩︎</a>'
            body = "".join(f"<p>{p}</p>" for p in para_htmls)
            items.append(f'<li id="fn{i}">{body}</li>')
        footnotes_html = '\n<div class="footnotes">\n<ol>\n' + "\n".join(items) + "\n</ol>\n</div>"
        body_html = body_html + footnotes_html

    return body_html


def format_revision_dates(revision_dates):
    """Return the revision history HTML fragment for a list of YYYY-MM-DD strings.

    Returns an empty string if revision_dates is empty or None.
    """
    if not revision_dates:
        return ""
    seen = set()
    unique_dates = [d for d in revision_dates if not (d in seen or seen.add(d))]
    formatted = " \u00b7 ".join(_format_date(d) for d in unique_dates)
    return f'\n<p class="post-history">Revised {formatted}.</p>'


_LIST_MARKER = "\x01LIST\x01"
_LIST_LINE_RE = re.compile(r"^ *(\t*)- (.+)$")
_BLOCKQUOTE_MARKER = "\x01BLOCKQUOTE\x01"
_BLOCKQUOTE_LINE_RE = re.compile(r"^ *> ?(.*)")


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
        elif _BLOCKQUOTE_LINE_RE.match(p.split("\n")[0]):
            blocks.append(_BLOCKQUOTE_MARKER + p)
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


def _blockquote_block_to_html(text, inline_fn):
    """Convert a `> `-prefixed block to <blockquote>…</blockquote>.

    Empty `>` lines separate paragraphs; consecutive non-empty `>` lines
    inside a paragraph are joined with <br> so poetry-style quotes keep
    their line breaks.
    """
    stripped = [
        _BLOCKQUOTE_LINE_RE.match(line).group(1) if _BLOCKQUOTE_LINE_RE.match(line) else line
        for line in text.split("\n")
    ]
    paragraphs = []
    current = []
    for line in stripped:
        if line.strip() == "":
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(line.strip())
    if current:
        paragraphs.append(current)
    parts = [
        "<p>" + "<br>\n".join(inline_fn(l) for l in para) + "</p>"
        for para in paragraphs
    ]
    return "<blockquote>" + "\n".join(parts) + "</blockquote>"


def _extract_footnotes(text):
    """Replace [^footnote text] with null-byte placeholders; return (text, texts).

    Runs before _split_blocks so footnote bodies may contain blank lines
    (paragraph breaks within a footnote).
    """
    footnotes = []

    def replacer(m):
        footnotes.append(m.group(1))
        return f"\x00fn{len(footnotes)}\x00"

    # Body may contain a markdown link `[label](url)`; its `]` must not be
    # read as the footnote's closing bracket. "Non-bracket char OR a whole
    # `[...]` group" allows one level of nesting (a link label). A naive
    # `[^\]]+` stopped at the link's first `]` and spilled the rest into the
    # body. Kept identical in fairy food's footnotes.py (see both CLAUDE.md).
    return re.sub(r"\[\^((?:[^\[\]]|\[[^\]]*\])*)\]", replacer, text), footnotes


def _inline_markdown(text):
    """Convert inline Markdown in already-HTML-escaped text to HTML tags.

    Handles [text](url) links, **bold**, *italic*, __bold__, _italic_.
    Must run AFTER _escape() so we're not double-escaping.
    """
    # Extract links first so underscores/asterisks inside URLs don't get
    # parsed as italic/bold. Replace with placeholder tokens, then restore.
    links = []

    def _link_sub(m):
        label, url = m.group(1), m.group(2)
        url_attr = url.replace('"', "&quot;")
        links.append(f'<a href="{url_attr}">{label}</a>')
        return f"\x02lnk{len(links) - 1}\x02"

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link_sub, text)

    # Bold before italic so **x** isn't parsed as *(*x*)*
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)

    text = re.sub(r"\x02lnk(\d+)\x02", lambda m: links[int(m.group(1))], text)
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

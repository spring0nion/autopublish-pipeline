import re
import logging
from pathlib import Path
from datetime import datetime

from autopublish import config, prompts
from autopublish.claude_cli import ClaudeUnavailable, call_claude

log = logging.getLogger(__name__)


def _get_reference_post(cfg):
    site_path = Path(cfg["site_path"])
    for html_file in sorted((site_path / "posts").glob("*.html")):
        html = html_file.read_text(encoding="utf-8")
        # Strip tags, collapse whitespace, keep only the prose
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:1500]
    return "(no reference post available)"


def _slugify(text):
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:60]


def _title_from_filename(filename):
    name = Path(filename).stem
    return name.strip()


def _title_from_text(text):
    """Extract title from a leading # heading, stripping iA Writer tags. Returns (title, remaining_text) or (None, text)."""
    lines = text.lstrip().splitlines()
    if not lines or not lines[0].startswith("#"):
        return None, text
    heading = lines[0].lstrip("#").strip()
    # Strip #tag and #date YYYY-MM-DD tokens
    heading = re.sub(r"#date[:\s]+\d{4}-\d{2}-\d{2}", "", heading, flags=re.IGNORECASE)
    heading = re.sub(r"#\w+", "", heading)
    title = heading.strip()
    remaining = "\n".join(lines[1:]).lstrip()
    return (title or None), remaining


def edit(candidate, cfg=None, dry_run=False):
    """
    Run editorial pass on a candidate. Returns dict with:
    {title, slug, edited_text, changes, editorial_note, date_slug}
    """
    if cfg is None:
        cfg = config.load()

    # Use an explicit #date tag if present, otherwise fall back to last-modified
    if candidate.get("date_override"):
        post_date = candidate["date_override"]
        log.info("Using date override: %s", post_date)
    else:
        post_date = datetime.fromtimestamp(candidate["modified"]).strftime("%Y-%m-%d")

    # Extract title from leading H1 if present, strip it from the text
    h1_title, body_text = _title_from_text(candidate["text"])
    title = h1_title or _title_from_filename(candidate["filename"])

    if dry_run:
        slug = _slugify(title)
        date_slug = f"{post_date}-{slug}"
        log.info("Dry run: skipping editorial pass, using title '%s'", title)
        return {
            "title": title,
            "slug": slug,
            "date_slug": date_slug,
            "edited_text": body_text,
            "changes": [],
            "editorial_note": f"[dry run] {candidate['word_count']} words, ready to ship.",
            "questions": [],
        }

    reference = _get_reference_post(cfg)
    prompt = prompts.EDIT_PROMPT.format(
        reference_post=reference,
        draft_text=body_text,
    )

    try:
        result = call_claude(prompt)
        if not isinstance(result, dict) or "edited_text" not in result:
            raise ClaudeUnavailable("Claude's editorial reply had no 'edited_text' field")
    except ClaudeUnavailable as e:
        # Deliberate fallback: a failed copy-edit must not block the publish, so the
        # draft is queued as written. `claude_error` lets the caller flag it to Esther
        # instead of letting an unedited post go out silently.
        log.warning("Editorial pass failed (%s) — queueing unedited text", e.reason)
        slug = _slugify(title)
        return {
            "title": title,
            "slug": slug,
            "date_slug": f"{post_date}-{slug}",
            "edited_text": body_text,
            "changes": [],
            "editorial_note": "No editorial pass — unedited.",
            "questions": [],
            "claude_error": e.reason,
        }

    slug = _slugify(title)
    return {
        "title": title,
        "slug": slug,
        "date_slug": f"{post_date}-{slug}",
        "edited_text": result["edited_text"],
        "changes": result.get("changes", []),
        "editorial_note": result.get("editorial_note", "Ship it."),
        "questions": result.get("questions", []),
    }

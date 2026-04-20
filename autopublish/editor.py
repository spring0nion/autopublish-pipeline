import json
import re
import subprocess
import logging
from pathlib import Path
from datetime import datetime

from autopublish import config, prompts

log = logging.getLogger(__name__)


def _get_reference_post(cfg):
    site_path = Path(cfg["site_path"])
    for html_file in sorted((site_path / "posts").glob("*.html")):
        return html_file.read_text(encoding="utf-8")
    return "(no reference post available)"


def _call_claude(prompt_text):
    try:
        result = subprocess.run(
            ["claude", "-p", prompt_text, "--output-format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning("Claude CLI failed: %s", result.stderr[:500])
            return None
        outer = json.loads(result.stdout)
        text = outer.get("result", result.stdout)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log.warning("Claude call failed: %s", e)
        return None


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

    result = _call_claude(prompt)
    if result and "edited_text" in result:
        slug = _slugify(title)
        date_slug = f"{post_date}-{slug}"
        return {
            "title": title,
            "slug": slug,
            "date_slug": date_slug,
            "edited_text": result["edited_text"],
            "changes": result.get("changes", []),
            "editorial_note": result.get("editorial_note", "Ship it."),
            "questions": result.get("questions", []),
        }

    # Fallback: no edits
    slug = _slugify(title)
    date_slug = f"{post_date}-{slug}"
    log.info("Editorial pass failed, using raw text")
    return {
        "title": title,
        "slug": slug,
        "date_slug": date_slug,
        "edited_text": body_text,
        "changes": [],
        "editorial_note": "Editorial pass unavailable. Publishing raw. Ship it anyway.",
        "questions": [],
    }

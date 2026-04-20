import os
import re
from pathlib import Path

from autopublish import config, state


def scan_drafts(cfg=None, current_state=None):
    """Find all eligible .txt drafts from iA Writer, sorted by publish-readiness signals."""
    if cfg is None:
        cfg = config.load()
    if current_state is None:
        current_state = state.load()

    drafts_path = Path(cfg["drafts_path"])
    min_chars = cfg.get("editorial", {}).get("min_chars", 500)
    candidates = []

    for txt_file in drafts_path.rglob("*.txt"):
        filename = txt_file.name

        # Skip already published
        if state.is_published(current_state, filename):
            continue

        # Skip nopublish
        if filename in current_state.get("nopublish", []):
            continue

        try:
            text = txt_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Skip if tagged #nopublish in content
        if "#nopublish" in text.lower():
            continue

        priority = "#priority" in text.lower()

        # #date YYYY-MM-DD — override the post date (otherwise uses last-modified)
        date_override = None
        date_match = re.search(r"#date[:\s]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        if date_match:
            date_override = date_match.group(1)

        # Skip stubs
        if len(text.strip()) < min_chars:
            continue

        stat = txt_file.stat()
        word_count = len(text.split())
        veto_count = state.get_veto_count(current_state, filename)

        candidates.append({
            "path": str(txt_file),
            "filename": filename,
            "text": text,
            "word_count": word_count,
            "modified": stat.st_mtime,
            "size": stat.st_size,
            "veto_count": veto_count,
            "priority": priority,
            "date_override": date_override,
        })

    # Sort by heuristic score (higher = more publish-ready)
    candidates.sort(key=lambda c: _score(c), reverse=True)
    return candidates


def _score(candidate):
    """Heuristic publish-readiness score. Used as fallback when Claude is unavailable."""
    score = 0.0

    # Word count: reward substance, diminishing returns past 2000
    wc = candidate["word_count"]
    score += min(wc / 2000.0, 1.0) * 30

    # Recency: more recently modified = more top-of-mind
    # Normalize to 0-1 over 90 days
    import time
    days_old = (time.time() - candidate["modified"]) / 86400
    recency = max(0, 1.0 - days_old / 90)
    score += recency * 25

    # Completeness: does it end with punctuation? (rough proxy for "has an ending")
    text = candidate["text"].rstrip()
    if text and text[-1] in ".!?\"'":
        score += 20
    elif text and text[-1] in "):;":
        score += 10

    # Priority flag: jump to the front of the queue
    if candidate.get("priority"):
        score += 1000

    # Penalize heavily vetoed pieces (but they still come back)
    score -= candidate["veto_count"] * 5

    # Bonus for file size (correlates with substantive content)
    score += min(candidate["size"] / 10000, 1.0) * 10

    return score

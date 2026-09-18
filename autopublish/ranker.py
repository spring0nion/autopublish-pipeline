import re
import logging
from datetime import datetime
from pathlib import Path

from autopublish import config, prompts
from autopublish.claude_cli import ClaudeUnavailable, call_claude

log = logging.getLogger(__name__)


def _get_reference_post(cfg):
    """Load the existing published post as a style reference."""
    site_path = Path(cfg["site_path"])
    posts_dir = site_path / "posts"
    for html_file in sorted(posts_dir.glob("*.html")):
        html = html_file.read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:1500]
    return "(no reference post available)"


def rank(candidates, cfg=None, dry_run=False):
    """Rank candidates for publish-readiness. Returns the top pick dict, or None.

    Raises ClaudeUnavailable if the ranking pass could not complete — the caller
    aborts the run and emails Esther rather than guessing at a pick.
    """
    if not candidates:
        return None

    if cfg is None:
        cfg = config.load()

    if dry_run:
        log.info("Dry run: using heuristic ranking (scanner sort order)")
        return candidates[0]

    reference = _get_reference_post(cfg)

    # Build candidate summaries for the prompt (truncate long pieces)
    summaries = []
    for c in candidates[:10]:  # Cap at 10 to stay within context
        preview = c["text"][:2000] + ("..." if len(c["text"]) > 2000 else "")
        header = f"## {c['filename']} ({c['word_count']} words)"
        if c.get("priority"):
            header += " [PRIORITY — Esther wants this one published]"
        summaries.append(f"{header}\n{preview}")

    today = datetime.now().strftime("%B %d, %Y")
    prompt = prompts.RANK_PROMPT.format(
        today=today,
        reference_post=reference,
        candidates="\n\n---\n\n".join(summaries),
    )

    result = call_claude(prompt)

    if not isinstance(result, dict) or "pick" not in result:
        raise ClaudeUnavailable(
            "Claude's ranking reply had no 'pick' field",
            "Usually transient — the next scheduled run will retry.",
        )

    pick_filename = result["pick"]
    for c in candidates:
        if c["filename"] == pick_filename:
            c["ranking_result"] = result
            editorial = next(
                (r for r in result.get("ranking", []) if r["filename"] == pick_filename),
                None
            )
            if editorial:
                c["verdict"] = editorial.get("verdict", "ship")
                c["editorial_note"] = editorial.get("note", "")
            return c

    # Claude named a file that isn't on the shortlist — don't guess a substitute.
    raise ClaudeUnavailable(
        f"Claude picked '{pick_filename}', which is not in the candidate list",
        "Usually transient — the next scheduled run will retry.",
    )

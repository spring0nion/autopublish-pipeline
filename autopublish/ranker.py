import json
import re
import subprocess
import logging
from datetime import datetime
from pathlib import Path

from autopublish import config, prompts

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


def _call_claude(prompt_text):
    """Call Claude via the CLI. Returns parsed JSON or None on failure."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt_text, "--output-format", "json"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            log.warning("Claude CLI failed: %s", result.stderr[:500])
            return None
        # claude --output-format json wraps result in {"result": "..."}
        outer = json.loads(result.stdout)
        text = outer.get("result", result.stdout)
        # Extract JSON from the response (may be wrapped in markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log.warning("Claude call failed: %s", e)
        return None


def rank(candidates, cfg=None, dry_run=False):
    """Rank candidates for publish-readiness. Returns the top pick dict, or None."""
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

    result = _call_claude(prompt)
    if result and "pick" in result:
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
        log.warning("Claude picked '%s' but it's not in candidates", pick_filename)

    # Claude unavailable — don't guess
    log.warning("Claude unavailable for ranking — aborting run")
    return None

import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta

from autopublish import config, state, prompts, notifier

log = logging.getLogger(__name__)


def _call_claude(prompt_text):
    try:
        result = subprocess.run(
            ["claude", "-p", prompt_text, "--output-format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return None
        outer = json.loads(result.stdout)
        text = outer.get("result", result.stdout).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)
    except Exception as e:
        log.warning("Claude call failed: %s", e)
        return None


def get_week_posts(cfg, current_state):
    """Get posts published in the last 7 days."""
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [p for p in current_state["published"] if p["date"] >= cutoff]
    return recent


def pick_for_substack(cfg, current_state, dry_run=False):
    """Pick the best piece from the week for Substack."""
    recent = get_week_posts(cfg, current_state)

    if not recent:
        log.info("No posts published this week — nothing to nudge")
        return None

    if len(recent) == 1:
        pick = recent[0]
    elif dry_run:
        # Just pick the longest
        site_path = Path(cfg["site_path"])
        best = None
        best_size = 0
        for p in recent:
            post_file = site_path / "posts" / f"{p['slug']}.html"
            if post_file.exists() and post_file.stat().st_size > best_size:
                best = p
                best_size = post_file.stat().st_size
        pick = best or recent[0]
    else:
        # Use Claude to pick
        site_path = Path(cfg["site_path"])
        post_texts = []
        for p in recent:
            post_file = site_path / "posts" / f"{p['slug']}.html"
            if post_file.exists():
                text = post_file.read_text(encoding="utf-8")
                post_texts.append(f"## {p['slug']}\nTitle: {p['title']}\n\n{text}")

        if post_texts:
            prompt = prompts.WEEKEND_PROMPT.format(posts="\n\n---\n\n".join(post_texts))
            result = _call_claude(prompt)
            if result and "pick" in result:
                for p in recent:
                    if p["slug"] == result["pick"]:
                        pick = p
                        pick["substack_meta"] = result
                        break
                else:
                    pick = recent[0]
            else:
                pick = recent[0]
        else:
            pick = recent[0]

    return pick


def send_substack_nudge(cfg, pick, dry_run=False):
    """Send the Substack nudge email with the piece ready to paste."""
    import re

    site_path = Path(cfg["site_path"])
    post_file = site_path / "posts" / f"{pick['slug']}.html"

    if not post_file.exists():
        log.error("Post file not found: %s", post_file)
        return

    post_html = post_file.read_text(encoding="utf-8")

    # Plain-text fallback: strip tags
    plain_text = re.sub(r"<[^>]+>", "", post_html)
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text).strip()

    title = pick["title"]
    url = f"https://fromtheabysmal.net/posts/{pick['slug']}.html"

    plain_body = f"""This week's Substack piece:

"{title}"

Already live at {url}

Copy the text below and paste into Substack. Formatting should carry over.

---

{plain_text}

---

—autopublish
"""

    html_body = f"""<p>This week's Substack piece:</p>
<p><strong>{title}</strong></p>
<p>Already live at <a href="{url}">{url}</a></p>
<p>Copy everything below the line and paste into Substack.</p>
<hr>
{post_html}
<hr>
<p>—autopublish</p>"""

    if dry_run:
        log.info("Dry run: would send Substack nudge for '%s'", title)
        print(plain_body)
        return

    esther_email = cfg["email"].get("notify_esther")
    if esther_email:
        notifier._send_email(cfg, esther_email, f"Substack: \"{title}\"", plain_body, html_body=html_body)
        log.info("Substack nudge sent for '%s'", title)
    else:
        log.warning("No notify_esther email configured")
        print(plain_body)

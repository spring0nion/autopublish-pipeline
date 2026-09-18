import smtplib
import subprocess
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from autopublish import config

log = logging.getLogger(__name__)


def _send_email(cfg, to_address, subject, body, html_body=None):
    """Send an email via Gmail SMTP. If html_body is provided, sends multipart/alternative."""
    email_cfg = cfg["email"]
    from_addr = email_cfg["pipeline_address"]
    password = email_cfg["pipeline_password"]

    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["From"] = f"autopublish <{from_addr}>"
    msg["To"] = to_address
    msg["Subject"] = subject

    try:
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(from_addr, password)
            server.send_message(msg)
        log.info("Email sent to %s: %s", to_address, subject)
        return msg["Message-ID"]
    except Exception as e:
        log.error("Failed to send email to %s: %s", to_address, e)
        return None


def _macos_notification(title, body):
    """Show a macOS notification via osascript."""
    # Escape quotes for AppleScript
    title = title.replace('"', '\\"')
    body = body.replace('"', '\\"')
    script = f'display notification "{body}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=5)
    except Exception as e:
        log.warning("macOS notification failed: %s", e)


def notify_publish_pending(cfg, title, slug, editorial_note, edited_text, questions=None, veto_count=0):
    """Notify Esther that a piece is going out. Returns the email Message-ID."""
    veto_hours = cfg["schedule"]["veto_window_hours"]

    snooze_note = ""
    if veto_count > 0:
        snooze_note = f"\n\n(This is attempt #{veto_count + 1}. You've vetoed this {veto_count} time{'s' if veto_count > 1 else ''}. It keeps coming back.)\n"

    questions_block = ""
    if questions:
        qs = "\n".join(f"  - {q}" for q in questions)
        questions_block = f"\nA few things to consider:\n{qs}\n"

    body = f"""This is going out in {veto_hours} hours:

    "{title}"

{editorial_note}
{questions_block}{snooze_note}
Reply VETO (or anything else) to delay by one day.
To change the text, edit the .txt file in iA Writer — the pipeline re-reads it at publish time.
If you don't reply, it publishes as-is.

---

{edited_text}

---

—autopublish
"""

    subject = f"Publishing \"{title}\" in {veto_hours} hours"

    # macOS notification
    _macos_notification(
        "autopublish",
        f'Publishing "{title}" in {veto_hours}h. Check email to veto.'
    )

    # Email to Esther
    esther_email = cfg["email"].get("notify_esther")
    if not esther_email:
        log.warning("No notify_esther email configured — skipping email notification")
        return None

    return _send_email(cfg, esther_email, subject, body)


def notify_published(cfg, title, slug, changes=None, editorial_note=None):
    """Notify Esther that a piece is live."""
    editorial_block = ""
    if editorial_note:
        editorial_block += f"\n{editorial_note}\n"
    if changes:
        lines = "\n".join(f"  '{c.get('original')}' → '{c.get('fixed')}' ({c.get('reason')})" for c in changes)
        editorial_block += f"\nFixes applied:\n{lines}\n"

    body = f""""{title}" is live.

https://fromtheabysmal.net/posts/{slug}.html
{editorial_block}
—autopublish
"""
    esther_email = cfg["email"].get("notify_esther")
    if esther_email:
        _send_email(cfg, esther_email, f'"{title}" is live', body)

    _macos_notification("autopublish", f'"{title}" is live on fromtheabysmal.net')


def notify_revised(cfg, title, slug, revision_date):
    """Notify Esther that a post was re-published after a source file change."""
    body = f""""{title}" was updated and re-published.

https://fromtheabysmal.net/posts/{slug}.html

Revision recorded: {revision_date}

—autopublish
"""
    esther_email = cfg["email"].get("notify_esther")
    if esther_email:
        _send_email(cfg, esther_email, f'"{title}" updated', body)

    _macos_notification("autopublish", f'"{title}" re-published with revisions.')


def notify_pipeline_error(cfg, stage, reason, hint=None, fatal=True):
    """Tell Esther the pipeline broke, and why.

    Without this the only signal was a macOS notification, which nobody sees if the
    Mac is asleep or unattended — an expired Claude token killed every run for two
    months before anyone noticed. `stage` is e.g. "ranking" or "editorial pass".
    """
    outcome = ("No post went out today. Nothing is stuck in the queue — the next "
               "scheduled run will try again.")
    if not fatal:
        outcome = "The run continued, but without that step."

    body = f"""The {stage} failed.

{reason}
"""
    if hint:
        body += f"\nWhat to do:\n{hint}\n"

    body += f"""
{outcome}

To run it by hand once it's fixed:

    cd "/Users/esther/Development/autopublish pipeline"
    source venv/bin/activate
    python -m autopublish weekday

Full log: logs/weekday.log

—autopublish
"""

    subject = f"autopublish: {stage} failed"
    esther_email = cfg["email"].get("notify_esther")
    if esther_email:
        _send_email(cfg, esther_email, subject, body)
    else:
        log.error("No notify_esther address configured — cannot email pipeline error")

    _macos_notification("autopublish", f"{stage.capitalize()} failed: {reason[:120]}")


def notify_veto_witness(cfg, title, veto_count):
    """Notify Kiryll that Esther vetoed a piece."""
    body = f"""Esther vetoed "{title}."

Snooze count: {veto_count}

No action needed. Just so you know.

—autopublish
"""
    kiryll_email = cfg["email"]["notify_kiryll"]
    _send_email(cfg, kiryll_email, f"Esther vetoed \"{title}\" (#{veto_count})", body)

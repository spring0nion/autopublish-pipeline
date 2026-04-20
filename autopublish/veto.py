import imaplib
import email
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from autopublish import config, state, notifier

log = logging.getLogger(__name__)


# Return values for check_for_reply
REPLY_NONE = "none"
REPLY_VETO = "veto"
REPLY_EDIT = "edit"


def check_for_reply(cfg=None, current_state=None):
    """Check the pipeline inbox for replies. Returns (type, body).

    type is one of: REPLY_NONE, REPLY_VETO, REPLY_EDIT
    body is the reply text (only meaningful for REPLY_EDIT)
    """
    if cfg is None:
        cfg = config.load()
    if current_state is None:
        current_state = state.load()

    queue = current_state.get("queue")
    if not queue:
        log.debug("No item in queue, nothing to check")
        return REPLY_NONE, None

    email_cfg = cfg["email"]
    address = email_cfg["pipeline_address"]
    password = email_cfg["pipeline_password"]

    try:
        mail = imaplib.IMAP4_SSL(email_cfg["imap_host"], email_cfg["imap_port"])
        mail.login(address, password)
        mail.select("INBOX")

        # Search for recent unseen replies
        since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
        _, message_ids = mail.search(None, f'(SINCE {since_date} UNSEEN)')

        if not message_ids[0]:
            mail.logout()
            return REPLY_NONE, None

        for msg_id in message_ids[0].split():
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            # Check if this is a reply to our notification
            in_reply_to = msg.get("In-Reply-To", "")
            queue_msg_id = queue.get("message_id", "")

            is_reply = (queue_msg_id and in_reply_to == queue_msg_id)

            body = _get_body(msg).strip()

            if not is_reply and not body:
                continue

            # If not a direct reply, check if it's at least from Esther's email
            if not is_reply:
                from_addr = msg.get("From", "")
                esther_email = cfg["email"].get("notify_esther", "")
                if esther_email and esther_email not in from_addr:
                    continue

            # Mark as read
            mail.store(msg_id, "+FLAGS", "\\Seen")

            # Determine: VETO or edited text?
            if body.upper().strip() == "VETO":
                mail.logout()
                return REPLY_VETO, None
            elif len(body) > 100:
                # Substantial text = edited version
                mail.logout()
                return REPLY_EDIT, body
            else:
                # Short reply that isn't "VETO" — treat as veto to be safe
                log.info("Short reply that isn't VETO: '%s' — treating as veto", body[:50])
                mail.logout()
                return REPLY_VETO, None

        mail.logout()
    except Exception as e:
        log.error("IMAP check failed: %s", e)

    return REPLY_NONE, None


def process_queue(cfg=None, current_state=None):
    """Check for replies and publish if deadline passed. Called by the veto-check cron."""
    if cfg is None:
        cfg = config.load()
    if current_state is None:
        current_state = state.load()

    queue = current_state.get("queue")
    if not queue:
        return

    # Check for replies
    reply_type, reply_body = check_for_reply(cfg, current_state)

    if reply_type == REPLY_VETO:
        log.info("VETO received for '%s' — delayed to tomorrow", queue["title"])
        source = queue["source"]
        veto_count = state.increment_veto(current_state, source)
        notifier.notify_veto_witness(cfg, queue["title"], veto_count)
        return

    if reply_type == REPLY_EDIT:
        log.info("Received edited text for '%s' — running editorial pass then publishing", queue["title"])
        from autopublish.publisher import publish
        from autopublish import editor
        from autopublish.editor import _slugify

        # Check for #date override in the reply body
        date_match = re.search(r"#date[:\s]+(\d{4}-\d{2}-\d{2})", reply_body, re.IGNORECASE)
        if date_match:
            new_date = date_match.group(1)
            reply_body = re.sub(r"[ \t]*#date[ \t:]+\d{4}-\d{2}-\d{2}[ \t]*", "", reply_body, flags=re.IGNORECASE).strip()
            log.info("Date override in reply: %s", new_date)
        else:
            # Extract date from existing slug (YYYY-MM-DD-rest)
            new_date = "-".join(queue["slug"].split("-", 3)[:3])

        # Write the email-edited text back to the source .txt file
        src_path = Path(cfg["drafts_path"]) / queue["source"]
        if src_path.exists():
            src_path.write_text(reply_body, encoding="utf-8")
            log.info("Wrote email edits back to %s", src_path.name)

        # Check for a title override — a leading # heading in the reply
        user_title = None
        lines = reply_body.lstrip().splitlines()
        if lines and lines[0].startswith("#"):
            user_title = lines[0].lstrip("#").strip()
            reply_body = "\n".join(lines[1:]).lstrip()
            log.info("Title override in reply: '%s'", user_title)

        # Build the slug from the new title if provided, otherwise keep the original
        if user_title:
            date_slug = f"{new_date}-{_slugify(user_title)}"
        else:
            date_slug = f"{new_date}-{'-'.join(queue['slug'].split('-', 3)[3:])}"

        # Run a fresh editorial pass on the reply text
        candidate = {
            "text": reply_body,
            "filename": queue["source"],
            "word_count": len(reply_body.split()),
            "modified": datetime.now().timestamp(),
        }
        result = editor.edit(candidate, cfg)
        final_text = result["edited_text"]
        changes = result.get("changes", [])
        editorial_note = result.get("editorial_note", "")
        if changes:
            log.info("Editorial pass made %d fix(es) on reply", len(changes))

        # User-supplied title wins over whatever Claude came up with
        title = user_title or queue["title"]

        edited = {
            "title": title,
            "date_slug": date_slug,
            "edited_text": final_text,
        }
        filename = publish(edited, cfg)
        src_path = Path(cfg["drafts_path"]) / queue["source"]
        mtime = src_path.stat().st_mtime if src_path.exists() else None
        state.record_publish(current_state, queue["source"], date_slug, title, source_mtime=mtime)
        notifier.notify_published(cfg, title, date_slug, changes=changes, editorial_note=editorial_note)
        log.info("Published (with edits): %s", filename)
        return

    # No reply — check if deadline passed
    if state.queue_deadline_passed(current_state):
        log.info("Veto deadline passed — publishing '%s'", queue["title"])
        from autopublish.publisher import publish
        edited = {
            "title": queue["title"],
            "date_slug": queue["slug"],
            "edited_text": queue["edited_text"],
        }
        filename = publish(edited, cfg)
        src_path = Path(cfg["drafts_path"]) / queue["source"]
        mtime = src_path.stat().st_mtime if src_path.exists() else None
        state.record_publish(current_state, queue["source"], queue["slug"], queue["title"], source_mtime=mtime)
        notifier.notify_published(cfg, queue["title"], queue["slug"])
        log.info("Published: %s", filename)


def _get_body(msg):
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return _strip_email_quoting(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return _strip_email_quoting(payload.decode("utf-8", errors="replace"))
    return ""


def _strip_email_quoting(text):
    """Strip > quote prefixes that email clients add when replying."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        # Strip one or more levels of email quoting ("> ", ">> ", etc.)
        stripped = line
        while stripped.startswith(">"):
            stripped = stripped[1:].lstrip(" ")
        cleaned.append(stripped)
    return "\n".join(cleaned)

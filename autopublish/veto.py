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


def check_for_reply(cfg=None, current_state=None):
    """Check the pipeline inbox for replies. Returns REPLY_NONE or REPLY_VETO.

    Any reply from Esther to a queued notification is treated as a veto. To
    change the text of a post, she edits the .txt file in iA Writer; the
    pipeline re-reads the source at publish time and also has a 30-minute
    edit-checker for post-publish changes.
    """
    if cfg is None:
        cfg = config.load()
    if current_state is None:
        current_state = state.load()

    queue = current_state.get("queue")
    if not queue:
        log.debug("No item in queue, nothing to check")
        return REPLY_NONE

    email_cfg = cfg["email"]
    address = email_cfg["pipeline_address"]
    password = email_cfg["pipeline_password"]

    try:
        mail = imaplib.IMAP4_SSL(email_cfg["imap_host"], email_cfg["imap_port"])
        mail.login(address, password)
        mail.select("INBOX")

        since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
        _, message_ids = mail.search(None, f'(SINCE {since_date} UNSEEN)')

        if not message_ids[0]:
            mail.logout()
            return REPLY_NONE

        for msg_id in message_ids[0].split():
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            in_reply_to = msg.get("In-Reply-To", "")
            queue_msg_id = queue.get("message_id", "")

            is_reply = (queue_msg_id and in_reply_to == queue_msg_id)

            body = _get_body(msg).strip()

            if not is_reply and not body:
                continue

            if not is_reply:
                from_addr = msg.get("From", "")
                esther_email = cfg["email"].get("notify_esther", "")
                if esther_email and esther_email not in from_addr:
                    continue

            mail.store(msg_id, "+FLAGS", "\\Seen")

            log.info("Reply received — treating as veto: '%s'", body[:80])
            mail.logout()
            return REPLY_VETO

        mail.logout()
    except Exception as e:
        log.error("IMAP check failed: %s", e)

    return REPLY_NONE


def process_queue(cfg=None, current_state=None):
    """Check for replies and publish if deadline passed. Called by the veto-check cron."""
    if cfg is None:
        cfg = config.load()
    if current_state is None:
        current_state = state.load()

    queue = current_state.get("queue")
    if not queue:
        return

    reply_type = check_for_reply(cfg, current_state)

    if reply_type == REPLY_VETO:
        log.info("VETO received for '%s' — delayed to tomorrow", queue["title"])
        source = queue["source"]
        veto_count = state.increment_veto(current_state, source)
        notifier.notify_veto_witness(cfg, queue["title"], veto_count)
        return

    # No reply — check if deadline passed
    if state.queue_deadline_passed(current_state):
        log.info("Veto deadline passed — publishing '%s'", queue["title"])
        from autopublish.publisher import publish

        edited = _refresh_from_source(cfg, queue)

        filename = publish(edited, cfg)
        from autopublish.publisher import _find_source
        src_path = _find_source(Path(cfg["drafts_path"]), queue["source"])
        mtime = src_path.stat().st_mtime if src_path is not None else None
        state.record_publish(current_state, queue["source"], edited["date_slug"], edited["title"], source_mtime=mtime)
        notifier.notify_published(cfg, edited["title"], edited["date_slug"])
        log.info("Published: %s", filename)


def _refresh_from_source(cfg, queue):
    """Build the {title, date_slug, edited_text} dict handed to publish().

    If the source .txt file has been edited since the queue was created, re-read
    it and use the latest version (including any #date override and title
    change). Otherwise use the Claude-edited text from the queue.
    """
    from autopublish.editor import _title_from_text, _slugify

    stored_mtime = queue.get("source_mtime")
    src_path = Path(cfg["drafts_path"]) / queue["source"]

    use_file = (
        stored_mtime is not None
        and src_path.exists()
        and src_path.stat().st_mtime > stored_mtime
    )

    if not use_file:
        return {
            "title": queue["title"],
            "date_slug": queue["slug"],
            "edited_text": queue["edited_text"],
        }

    log.info("Source edited during veto window — publishing latest file version")
    text = src_path.read_text(encoding="utf-8")

    date_match = re.search(r"#date[:\s]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if date_match:
        new_date = date_match.group(1)
        text = re.sub(r"[ \t]*#date[ \t:]+\d{4}-\d{2}-\d{2}[ \t]*", "", text, flags=re.IGNORECASE).strip()
    else:
        new_date = queue["slug"][:10]

    title, body = _title_from_text(text)
    if not title:
        title = queue["title"]
        body = text

    if title != queue["title"]:
        date_slug = f"{new_date}-{_slugify(title)}"
        log.info("Title changed in source: '%s' → '%s'", queue["title"], title)
    else:
        slug_tail = "-".join(queue["slug"].split("-", 3)[3:])
        date_slug = f"{new_date}-{slug_tail}"

    return {
        "title": title,
        "date_slug": date_slug,
        "edited_text": body,
    }


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
        stripped = line
        while stripped.startswith(">"):
            stripped = stripped[1:].lstrip(" ")
        cleaned.append(stripped)
    return "\n".join(cleaned)

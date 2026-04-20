import re
import logging
from pathlib import Path

import paramiko

from autopublish import config

log = logging.getLogger(__name__)


def update_posts_js(site_path, new_filename, remove_filename=None):
    """Insert a new entry into posts.js, sorted by date (newest first).

    If remove_filename is given, that entry is removed first (used when a post's
    date slug changes and the old file is being replaced).
    """
    posts_js = Path(site_path) / "posts.js"
    content = posts_js.read_text(encoding="utf-8")

    # Extract existing entries
    entries = re.findall(r'"([^"]+\.html)"', content)

    # Drop the old entry if we're renaming
    if remove_filename and remove_filename in entries:
        entries.remove(remove_filename)

    # Add the new entry and sort newest-first (YYYY-MM-DD prefix sorts lexicographically)
    entries.append(new_filename)
    entries = sorted(set(entries), reverse=True)

    # Rebuild the posts array, preserving the header comment and structure
    entries_str = "\n".join(f'    "{e}",' for e in entries)
    content = re.sub(
        r"(const\s+posts\s*=\s*\[)[^\]]*(\])",
        rf"\1\n{entries_str}\n\2",
        content,
        flags=re.DOTALL,
    )

    posts_js.write_text(content, encoding="utf-8")
    log.info("Updated posts.js with %s (%d total posts)", new_filename, len(entries))
    return content


def save_post_html(site_path, filename, html_content):
    """Save post HTML to the posts/ directory."""
    post_path = Path(site_path) / "posts" / filename
    post_path.write_text(html_content, encoding="utf-8")
    log.info("Saved %s", post_path)
    return str(post_path)


def sftp_upload(cfg, site_path):
    """Upload the new post and updated posts.js to the server."""
    sftp_cfg = cfg["sftp"]
    host = sftp_cfg["host"]
    port = sftp_cfg.get("port", 22)
    username = sftp_cfg["username"]
    password = sftp_cfg.get("password")
    remote_root = sftp_cfg.get("remote_root", "/")

    transport = paramiko.Transport((host, port))
    try:
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Upload posts.js
        local_posts_js = str(Path(site_path) / "posts.js")
        remote_posts_js = f"{remote_root}/posts.js".replace("//", "/")
        sftp.put(local_posts_js, remote_posts_js)
        log.info("Uploaded posts.js to %s", remote_posts_js)

        # Upload all post HTML files (simpler than tracking which is new)
        local_posts_dir = Path(site_path) / "posts"
        remote_posts_dir = f"{remote_root}/posts".replace("//", "/")

        # Ensure remote posts dir exists
        try:
            sftp.stat(remote_posts_dir)
        except FileNotFoundError:
            sftp.mkdir(remote_posts_dir)

        for html_file in local_posts_dir.glob("*.html"):
            remote_path = f"{remote_posts_dir}/{html_file.name}"
            sftp.put(str(html_file), remote_path)
            log.info("Uploaded %s", remote_path)

        sftp.close()
    finally:
        transport.close()

    log.info("SFTP upload complete")


def republish_if_changed(cfg, current_state):
    """Check all published posts for source file changes and re-publish any that have been edited.

    Supports #date YYYY-MM-DD in the .txt file to change the post's date and re-sort it in posts.js.
    """
    from pathlib import Path
    from datetime import datetime
    from autopublish import state as state_module, notifier

    drafts_path = Path(cfg["drafts_path"])
    site_path = cfg["site_path"]
    today = datetime.now().strftime("%Y-%m-%d")

    for post in current_state.get("published", []):
        source_mtime = post.get("source_mtime")
        if source_mtime is None:
            # No baseline recorded — skip (pre-feature posts)
            continue

        src_path = drafts_path / post["source"]
        if not src_path.exists():
            continue

        current_mtime = src_path.stat().st_mtime
        if current_mtime <= source_mtime:
            continue

        # Source file changed since last publish — re-publish
        log.info("Source changed for '%s' — re-publishing", post["title"])
        text = src_path.read_text(encoding="utf-8")

        # Re-read title from file heading in case it was edited
        from autopublish.editor import _title_from_text
        new_title, _ = _title_from_text(text)
        if new_title and new_title != post["title"]:
            log.info("Title changed: '%s' → '%s'", post["title"], new_title)
            post["title"] = new_title

        # Parse optional #date override
        date_match = re.search(r"#date[:\s]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        if date_match:
            new_date = date_match.group(1)
            text = re.sub(r"[ \t]*#date[ \t:]+\d{4}-\d{2}-\d{2}[ \t]*", "", text, flags=re.IGNORECASE).strip()
            log.info("Date override in source file: %s", new_date)
        else:
            new_date = "-".join(post["slug"].split("-", 3)[:3])

        old_slug = post["slug"]
        slug_tail = "-".join(old_slug.split("-", 3)[3:])
        new_slug = f"{new_date}-{slug_tail}"
        title = post["title"]
        revision_dates = post.get("edit_history", []) + [today]

        from autopublish.converter import text_to_html
        html = text_to_html(title, text, revision_dates=revision_dates)

        new_filename = f"{new_slug}.html"
        save_post_html(site_path, new_filename, html)

        if new_slug != old_slug:
            # Remove the old HTML file and swap the posts.js entry
            old_path = Path(site_path) / "posts" / f"{old_slug}.html"
            if old_path.exists():
                old_path.unlink()
                log.info("Removed old post file %s", old_path.name)
            update_posts_js(site_path, new_filename, remove_filename=f"{old_slug}.html")
            post["slug"] = new_slug  # update in-place so state helpers find it
        else:
            update_posts_js(site_path, new_filename)

        sftp_upload(cfg, site_path)

        state_module.record_revision(current_state, new_slug, today)
        state_module.update_source_mtime(current_state, new_slug, current_mtime)
        notifier.notify_revised(cfg, title, new_slug, today)
        log.info("Re-published '%s' as %s with revision date %s", title, new_slug, today)


def publish(edited, cfg=None, dry_run=False):
    """Full publish flow: save HTML, update posts.js, SFTP upload."""
    if cfg is None:
        cfg = config.load()

    site_path = cfg["site_path"]
    filename = f"{edited['date_slug']}.html"

    from autopublish.converter import text_to_html
    html = text_to_html(edited["title"], edited["edited_text"])

    if dry_run:
        # Preview only — don't touch the real site
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="autopublish_"))
        (tmp_dir / "posts").mkdir()
        post_path = tmp_dir / "posts" / filename
        post_path.write_text(html, encoding="utf-8")
        log.info("Dry run: wrote preview to %s", post_path)
        return filename

    save_post_html(site_path, filename, html)
    update_posts_js(site_path, filename)
    sftp_upload(cfg, site_path)
    return filename

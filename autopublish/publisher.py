import re
import logging
from pathlib import Path
from typing import Optional

import paramiko

from autopublish import config

log = logging.getLogger(__name__)


def _find_source(drafts_path: Path, source_name: str) -> Optional[Path]:
    """Find a source .txt file anywhere under drafts_path (matches the scanner's rglob).

    iA Writer lets Esther move files into subfolders (e.g. `x - published/`) after
    they're published. state.json only stores the bare filename, so we have to
    search recursively to locate the current path.
    """
    direct = drafts_path / source_name
    if direct.exists():
        return direct
    for candidate in drafts_path.rglob(source_name):
        if candidate.is_file():
            return candidate
    return None


def save_post_html(site_path, filename, html_content):
    """Save post HTML to the posts/ directory."""
    post_path = Path(site_path) / "posts" / filename
    post_path.write_text(html_content, encoding="utf-8")
    log.info("Saved %s", post_path)
    return str(post_path)


def save_month_archive(site_path, year_month, html_content):
    """Save a month archive page to archive/YYYY-MM.html (creating the dir if needed)."""
    archive_dir = Path(site_path) / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{year_month}.html"
    path.write_text(html_content, encoding="utf-8")
    log.info("Saved %s", path)
    return str(path)


def sftp_upload_files(cfg, site_path, relative_paths):
    """Upload a specific list of files (relative to site_path) via SFTP."""
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

        ensured_dirs = set()
        for rel_path in relative_paths:
            parent = str(Path(rel_path).parent)
            if parent in (".", "", "/") or parent in ensured_dirs:
                continue
            remote_dir = f"{remote_root}/{parent}".replace("//", "/")
            try:
                sftp.stat(remote_dir)
            except FileNotFoundError:
                sftp.mkdir(remote_dir)
                log.info("Created remote dir %s", remote_dir)
            ensured_dirs.add(parent)

        for rel_path in relative_paths:
            local_path = str(Path(site_path) / rel_path)
            remote_path = f"{remote_root}/{rel_path}".replace("//", "/")
            sftp.put(local_path, remote_path)
            log.info("Uploaded %s", remote_path)

        sftp.close()
    finally:
        transport.close()

    log.info("SFTP upload complete (%d files)", len(relative_paths))


def rebuild_index_and_rss(cfg, current_state, site_path):
    """Regenerate index.html and rss.xml from the current published post list."""
    from autopublish import builder

    site_url = cfg.get("site_url", "")
    published = current_state.get("published", [])
    posts = sorted(published, key=lambda p: p["slug"][:10], reverse=True)

    index_html = builder.render_index(posts, site_url, site_path)
    rss_xml = builder.render_rss(posts, site_url, site_path)

    (Path(site_path) / "index.html").write_text(index_html, encoding="utf-8")
    (Path(site_path) / "rss.xml").write_text(rss_xml, encoding="utf-8")
    log.info("Rebuilt index.html and rss.xml")


def rebuild_month_archives(cfg, current_state, site_path, year_months):
    """Regenerate one or more /archive/YYYY-MM.html pages.

    year_months is an iterable of "YYYY-MM" strings. Returns the list of relative
    paths that were written (suitable for inclusion in an SFTP upload set).
    """
    from autopublish import builder

    site_url = cfg.get("site_url", "")
    published = current_state.get("published", [])
    all_posts = sorted(published, key=lambda p: p["slug"][:10], reverse=True)

    written = []
    for ym in year_months:
        year, month = ym.split("-", 1)
        html = builder.render_month_archive(year, month, all_posts, site_url, site_path)
        save_month_archive(site_path, ym, html)
        written.append(f"archive/{ym}.html")
    return written


def _year_month(slug):
    """Extract 'YYYY-MM' from a slug (which starts with YYYY-MM-DD-)."""
    return slug[:7]


def republish_if_changed(cfg, current_state):
    """Check all published posts for source file changes and re-publish any that have been edited.

    Supports #date YYYY-MM-DD in the .txt file to change the post's date.
    """
    from datetime import datetime
    from autopublish import state as state_module, notifier

    drafts_path = Path(cfg["drafts_path"])
    site_path = cfg["site_path"]
    today = datetime.now().strftime("%Y-%m-%d")
    site_url = cfg.get("site_url", "")
    any_changed = False

    for post in current_state.get("published", []):
        source_mtime = post.get("source_mtime")
        if source_mtime is None:
            continue

        src_path = _find_source(drafts_path, post["source"])
        if src_path is None:
            continue

        current_mtime = src_path.stat().st_mtime
        if current_mtime <= source_mtime:
            continue

        log.info("Source changed for '%s' — re-publishing", post["title"])
        text = src_path.read_text(encoding="utf-8")

        from autopublish.editor import _title_from_text
        new_title, _ = _title_from_text(text)
        if new_title and new_title != post["title"]:
            log.info("Title changed: '%s' → '%s'", post["title"], new_title)
            post["title"] = new_title

        date_match = re.search(r"#date[:\s]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        if date_match:
            new_date = date_match.group(1)
            text = re.sub(r"[ \t]*#date[ \t:]+\d{4}-\d{2}-\d{2}[ \t]*", "", text, flags=re.IGNORECASE).strip()
        else:
            new_date = "-".join(post["slug"].split("-", 3)[:3])

        old_slug = post["slug"]
        slug_tail = "-".join(old_slug.split("-", 3)[3:])
        new_slug = f"{new_date}-{slug_tail}"
        title = post["title"]
        revision_dates = post.get("edit_history", []) + [today]

        from autopublish.converter import text_to_html
        from autopublish import builder
        body_html = text_to_html(title, text)
        html = builder.render_post_page(title, new_slug, new_date, body_html, revision_dates, site_url)

        new_filename = f"{new_slug}.html"
        save_post_html(site_path, new_filename, html)

        if new_slug != old_slug:
            old_path = Path(site_path) / "posts" / f"{old_slug}.html"
            if old_path.exists():
                old_path.unlink()
                log.info("Removed old post file %s", old_path.name)
            post["slug"] = new_slug

        rebuild_index_and_rss(cfg, current_state, site_path)

        affected_months = {_year_month(new_slug)}
        if _year_month(old_slug) != _year_month(new_slug):
            affected_months.add(_year_month(old_slug))
        month_paths = rebuild_month_archives(cfg, current_state, site_path, affected_months)

        sftp_upload_files(cfg, site_path, [
            f"posts/{new_filename}",
            "index.html",
            "rss.xml",
            *month_paths,
        ])

        state_module.record_revision(current_state, new_slug, today)
        state_module.update_source_mtime(current_state, new_slug, current_mtime)
        notifier.notify_revised(cfg, title, new_slug, today)
        log.info("Re-published '%s' as %s with revision date %s", title, new_slug, today)
        any_changed = True

    return any_changed


def publish(edited, cfg=None, dry_run=False):
    """Full publish flow: generate HTML, rebuild index+RSS, upload."""
    if cfg is None:
        cfg = config.load()

    site_path = cfg["site_path"]
    site_url = cfg.get("site_url", "")
    slug = edited["date_slug"]
    filename = f"{slug}.html"
    title = edited["title"]
    date = slug[:10]

    from autopublish.converter import text_to_html
    from autopublish import builder, state as state_module
    body_html = text_to_html(title, edited["edited_text"])
    html = builder.render_post_page(title, slug, date, body_html, [], site_url)

    if dry_run:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="autopublish_"))
        (tmp_dir / "posts").mkdir()
        post_path = tmp_dir / "posts" / filename
        post_path.write_text(html, encoding="utf-8")
        log.info("Dry run: wrote preview to %s", post_path)
        return filename

    save_post_html(site_path, filename, html)

    current_state = state_module.load()
    # Include the post being published in the in-memory state so it appears in
    # index.html, rss.xml, and the month archive. record_publish() in state.json
    # happens in the caller after publish() returns, so state.json on disk does
    # not yet include this post.
    if not any(p.get("slug") == slug for p in current_state.get("published", [])):
        current_state.setdefault("published", []).append({
            "slug": slug,
            "title": title,
            "date": date,
            "edit_history": [],
        })
    rebuild_index_and_rss(cfg, current_state, site_path)
    month_paths = rebuild_month_archives(cfg, current_state, site_path, [_year_month(slug)])

    sftp_upload_files(cfg, site_path, [
        f"posts/{filename}",
        "index.html",
        "rss.xml",
        *month_paths,
    ])

    return filename


def full_rebuild(cfg=None):
    """Rebuild all post HTML files, index.html, rss.xml, and all month archives from scratch.

    Use after changing the page template, CSS references, or any builder logic.
    Reads source .txt files from drafts_path; uploads everything via SFTP.
    """
    if cfg is None:
        cfg = config.load()

    from autopublish import state as state_module, builder
    from autopublish.converter import text_to_html

    site_path = cfg["site_path"]
    site_url = cfg.get("site_url", "")
    drafts_path = Path(cfg["drafts_path"])
    current_state = state_module.load()
    published = current_state.get("published", [])

    upload_paths = []
    rebuilt = 0

    for post in published:
        slug = post["slug"]
        title = post["title"]
        date = post["date"]
        src_path = _find_source(drafts_path, post["source"])
        revision_dates = post.get("edit_history", [])

        if src_path is None:
            log.warning("Source file not found for '%s': %s", title, post["source"])
            continue

        text = src_path.read_text(encoding="utf-8")
        text = re.sub(r"[ \t]*#date[ \t:]+\d{4}-\d{2}-\d{2}[ \t]*", "", text, flags=re.IGNORECASE).strip()

        body_html = text_to_html(title, text)
        html = builder.render_post_page(title, slug, date, body_html, revision_dates, site_url)
        save_post_html(site_path, f"{slug}.html", html)
        upload_paths.append(f"posts/{slug}.html")
        rebuilt += 1

    log.info("Rebuilt %d post HTML files", rebuilt)

    rebuild_index_and_rss(cfg, current_state, site_path)
    upload_paths += ["index.html", "rss.xml"]

    posts_newest_first = sorted(published, key=lambda p: p["slug"][:10], reverse=True)
    year_months = [f"{y}-{m}" for (y, m) in builder.month_pages(posts_newest_first)]
    month_paths = rebuild_month_archives(cfg, current_state, site_path, year_months)
    upload_paths += month_paths
    log.info("Rebuilt %d month archive pages", len(month_paths))

    sftp_upload_files(cfg, site_path, upload_paths)
    log.info("Full rebuild complete: %d files uploaded", len(upload_paths))

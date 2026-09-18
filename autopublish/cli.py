#!/usr/bin/env python3
"""
autopublish — the boss that makes sure your writing gets out the door.

Usage:
    python -m autopublish weekday [--dry-run]
    python -m autopublish veto-check
    python -m autopublish scan [--dry-run]
    python -m autopublish rebuild
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta

from autopublish import config, state, scanner, ranker, editor, publisher, notifier, veto, builder
from autopublish.claude_cli import ClaudeUnavailable

log = logging.getLogger("autopublish")


def cmd_weekday(args):
    """Main weekday pipeline: scan → rank → edit → notify (→ publish after veto window)."""
    cfg = config.load()
    current_state = state.load()

    # If there's already something in the queue, don't start a new one
    if current_state.get("queue"):
        log.info("Queue already has '%s' — waiting for veto window to resolve",
                 current_state["queue"]["title"])
        # Process the existing queue instead
        veto.process_queue(cfg, current_state)
        return

    # 1. Scan
    candidates = scanner.scan_drafts(cfg, current_state)
    if not candidates:
        log.info("No eligible drafts found. Write more, or lower the bar.")
        return

    log.info("Found %d eligible drafts", len(candidates))
    for c in candidates[:5]:
        log.info("  - %s (%d words, score %.1f)", c["filename"], c["word_count"], scanner._score(c))

    # 2. Rank
    try:
        pick = ranker.rank(candidates, cfg, dry_run=args.dry_run)
    except ClaudeUnavailable as e:
        log.warning("Ranking failed — %s", e.reason)
        if e.hint:
            log.warning("Hint: %s", e.hint)
        notifier.notify_pipeline_error(cfg, "ranking pass", e.reason, e.hint)
        return
    if not pick:
        log.info("Nothing worth publishing today.")
        return
    log.info("Selected: %s (%d words)", pick["filename"], pick["word_count"])

    # 3. Edit — never fatal; editor.edit falls back to the unedited draft.
    edited = editor.edit(pick, cfg, dry_run=args.dry_run)
    if edited.get("claude_error"):
        notifier.notify_pipeline_error(
            cfg, "editorial pass", edited["claude_error"],
            hint=f'"{edited["title"]}" was queued as written, with no copy-edit. '
                 "Reply to the veto email if you'd rather it waited.",
            fatal=False,
        )
    log.info("Title: %s", edited["title"])
    log.info("Slug: %s", edited["date_slug"])
    if edited["changes"]:
        log.info("Editorial changes:")
        for change in edited["changes"]:
            log.info("  '%s' → '%s' (%s)", change.get("original"), change.get("fixed"), change.get("reason"))
    log.info("Editorial note: %s", edited["editorial_note"])

    if args.dry_run:
        log.info("--- DRY RUN: publishing locally only ---")
        filename = publisher.publish(edited, cfg, dry_run=True)
        log.info("Would publish: %s", filename)

        from autopublish.converter import text_to_html
        body_html = text_to_html(edited["title"], edited["edited_text"])
        site_url = cfg.get("site_url", "https://fromtheabysmal.net")
        slug = edited["date_slug"]
        date = slug[:10]
        html = builder.render_post_page(edited["title"], slug, date, body_html, [], site_url)
        print("\n--- Generated HTML (first 80 lines) ---")
        for i, line in enumerate(html.split("\n")[:80]):
            print(line)
        return

    # 4. Queue with veto window
    veto_deadline = datetime.now() + timedelta(hours=cfg["schedule"]["veto_window_hours"])
    veto_count = state.get_veto_count(current_state, pick["filename"])

    message_id = notifier.notify_publish_pending(
        cfg, edited["title"], edited["date_slug"],
        edited["editorial_note"], edited["edited_text"],
        edited.get("questions", []), veto_count,
    )

    state.set_queue(
        current_state, pick["filename"], edited["date_slug"],
        edited["title"], edited["edited_text"],
        veto_deadline, message_id,
        source_mtime=pick.get("modified"),
    )

    log.info("Queued '%s' — publishing at %s unless vetoed", edited["title"], veto_deadline.strftime("%H:%M"))


def cmd_veto_check(args):
    """Check for veto replies and publish if deadline passed. Also re-publishes edited posts."""
    cfg = config.load()
    current_state = state.load()
    veto.process_queue(cfg, current_state)
    publisher.republish_if_changed(cfg, current_state)


def cmd_rebuild(args):
    """Rebuild all post HTML files, index.html, and rss.xml from source. Uploads everything."""
    cfg = config.load()
    publisher.full_rebuild(cfg)


def cmd_scan(args):
    """Just scan and rank drafts, don't publish anything."""
    cfg = config.load()
    current_state = state.load()
    candidates = scanner.scan_drafts(cfg, current_state)

    if not candidates:
        print("No eligible drafts found.")
        return

    print(f"\n{len(candidates)} eligible drafts:\n")
    for i, c in enumerate(candidates, 1):
        score = scanner._score(c)
        print(f"  {i}. {c['filename']}")
        print(f"     {c['word_count']} words | score: {score:.1f} | vetoed: {c['veto_count']}x")
        # Show first line
        first_line = c["text"].strip().split("\n")[0][:100]
        print(f"     \"{first_line}...\"")
        print()


def main():
    parser = argparse.ArgumentParser(
        prog="autopublish",
        description="The boss that makes sure your writing gets out the door.",
    )
    sub = parser.add_subparsers(dest="command")

    p_weekday = sub.add_parser("weekday", help="Run the weekday publish pipeline")
    p_weekday.add_argument("--dry-run", action="store_true", help="Scan, rank, edit locally — no SFTP, no email")

    p_veto = sub.add_parser("veto-check", help="Check inbox for VETO replies")

    p_scan = sub.add_parser("scan", help="Just scan and rank drafts")
    p_scan.add_argument("--dry-run", action="store_true")

    sub.add_parser("rebuild", help="Rebuild all post pages, index.html, rss.xml and upload")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    commands = {
        "weekday": cmd_weekday,
        "veto-check": cmd_veto_check,
        "scan": cmd_scan,
        "rebuild": cmd_rebuild,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

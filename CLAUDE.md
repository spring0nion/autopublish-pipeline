# autopublish

An automated publishing pipeline for [fromtheabysmal.net](https://fromtheabysmal.net).

It watches Esther's iA Writer drafts, picks the best one, runs a light copy-edit via Claude, gives Esther a 4-hour veto window by email, and publishes automatically if she doesn't object. It also watches already-published posts for edits and re-publishes them when the source file changes.

---

## How it works

### The weekday pipeline

Runs at **12pm Monday, Wednesday, Friday**.

1. **Scan** — reads all `.txt` files from iA Writer's documents folder, filters out published/excluded/too-short drafts, scores each one by word count, recency, whether it has a proper ending, and veto history
2. **Rank** — passes the top 10 candidates to Claude, which picks the best one for today
3. **Edit** — Claude runs a light copy-edit on the chosen draft (mechanical fixes only — typos, punctuation), returns a title, slug, and brief editorial note
4. **Queue** — the edited post is held in `state.json` with a 4-hour veto deadline
5. **Notify** — Esther gets an email with the full text, editorial note, and instructions

### The veto window

Esther can reply to the notification email within 4 hours:

| Reply | Effect |
|-------|--------|
| Any reply (including `VETO`) | Post is delayed. Veto count incremented. Kiryll is notified. Draft re-enters the pool with a score penalty. |
| No reply | Post publishes automatically when the deadline passes. |

To change the text, Esther edits the `.txt` file in iA Writer. The pipeline re-reads the source at publish time and uses the latest version if the file was modified during the veto window (handled by `veto._refresh_from_source`). If the heading changed, the slug and URL are rebuilt accordingly. `#date YYYY-MM-DD` in the file is still honored at publish time.

### The veto-check job

Runs **every 30 minutes**. Does two things:
1. Checks the pipeline inbox for replies and processes the queue (publish, veto, or wait)
2. Scans all published posts for source file changes — if a `.txt` has been modified since last publish, re-converts and re-uploads the HTML automatically

---

## Draft tags

Add these anywhere in a `.txt` file to control pipeline behaviour:

| Tag | Effect |
|-----|--------|
| `#nopublish` | Permanently excludes the file from the pipeline |
| `#priority` | Jumps to the front of the queue (score +1000) |
| `#date YYYY-MM-DD` | Overrides the post date used for the slug and sort order |

Tags can appear inline in a heading line or on their own line. `#date` is stripped from the published text.

---

## Post-publish edits

Once a post is published, just edit the `.txt` file in iA Writer and save. The next veto-check run (within 30 minutes) will detect the change, re-generate the HTML, and re-upload it.

- Adding `#date YYYY-MM-DD` to the file will also change the post's position in the archive
- If there are multiple saves on the same day, only one revision date is recorded
- Revision dates appear at the bottom of each post in grey: *Last revised April 17, 2026.* — only the most recent date is shown.

---

## Controlling the pipeline

### Check what's running

```bash
launchctl list | grep abysmal
```

Each line shows: PID (or `-` if not currently running), last exit code, job name. Exit code `0` is normal.

### Stop a job temporarily

```bash
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.weekday.plist
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.vetocheck.plist
```

Or all at once:
```bash
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.*.plist
```

Unloading stops the job and removes it from launchd's schedule until reloaded. The Mac doesn't need to restart.

### Restart a job

```bash
launchctl load ~/Library/LaunchAgents/com.abysmal.autopublish.weekday.plist
```

### Reinstall everything (after editing a plist or a fresh setup)

```bash
bash install_plists.sh
```

This unloads any existing jobs, re-creates the symlinks in `~/Library/LaunchAgents/`, and reloads them.

### Run a job manually

```bash
cd "/Users/esther/Development/autopublish pipeline"
source venv/bin/activate
python -m autopublish weekday
python -m autopublish veto-check
python -m autopublish scan          # preview only — lists eligible drafts, no publishing
python -m autopublish rebuild       # rebuild all post pages + index.html + rss.xml + month archives and upload
```

### Rebuild after template changes

If you change `builder.py`, the CSS, or `converter.py`, run a full rebuild to regenerate all post pages on disk and on the server:

```bash
cd "/Users/esther/Development/autopublish pipeline"
source venv/bin/activate
python -m autopublish rebuild
```

This reads every source `.txt` from iA Writer's folder, regenerates all post HTML files using the current template, rebuilds `index.html`, `rss.xml`, and every `/archive/YYYY-MM.html` page, and uploads everything. Takes ~1 minute at current scale.

### Pause publishing without stopping the jobs

Add `#priority` to a draft you want to hold back if you need a break, or just reply `VETO` to each notification. After 5 vetoes of the same piece a warning is logged.

---

## Logs

All job output goes to the `logs/` directory:

```
logs/weekday.log
logs/vetocheck.log
```

Tail a log in real time:
```bash
tail -f "/Users/esther/Development/autopublish pipeline/logs/vetocheck.log"
```

---

## Key files

| File | Purpose |
|------|---------|
| `config.yaml` | SFTP credentials, email addresses, schedule settings, editorial thresholds |
| `state.json` | Published post registry, veto counts, active queue, nopublish list |
| `plists/` | launchd job definitions |
| `install_plists.sh` | Registers/reinstalls the launchd jobs |
| `autopublish/scanner.py` | Draft discovery and scoring |
| `autopublish/ranker.py` | Claude ranking pass |
| `autopublish/editor.py` | Claude editorial pass |
| `autopublish/veto.py` | Email reply detection and queue processing |
| `autopublish/publisher.py` | Publish flow, targeted SFTP upload, post-publish edit detection, full rebuild |
| `autopublish/builder.py` | Site artifact rendering: post pages, index.html, rss.xml, month archive pages |
| `autopublish/converter.py` | Markdown-to-body-HTML conversion (no page wrapper) |
| `autopublish/notifier.py` | Email and macOS notifications |
| `autopublish/state.py` | state.json read/write helpers |

---

## Site architecture

The site (`~/Documents/from the abysmal (site)/`) is a statically-generated site built by the pipeline at publish time:

- `index.html` — **generated** on every publish; renders the 10 most recent posts inline plus a server-side archive nav. No JavaScript required.
- `style.css` — symlink to `assets/style.css` in this repo (source of truth). All styles including dark mode and a `@media (max-width: 640px)` block for mobile. Not uploaded by the pipeline — deploy manually via SFTP if changed.
- `posts/YYYY-MM-DD-slug.html` — **generated** individual post pages with full site chrome (header logo, back-link top and bottom, footer), `<head>` og tags, canonical URL, and `style.css` link
- `archive/YYYY-MM.html` — **generated** per-month archive pages that render every post from that month inline, same layout as the index
- `rss.xml` — **generated** RSS 2.0 feed with the 20 most recent posts (full body)

**Archive nav UX:** the archive at the top of `index.html` (and every month archive page) shows only year labels at rest. Clicking a year reveals the months that have posts; clicking a month navigates to `/archive/YYYY-MM.html`. Post titles are **never** listed in the nav itself — the user only sees them by clicking through to a month page or the post page.

**Per-operation upload set:**
- Normal publish: `posts/{new-slug}.html` + `index.html` + `rss.xml` + `archive/{YYYY-MM}.html` (4 files)
- Post-publish edit: `posts/{edited-slug}.html` + `index.html` + `rss.xml` + `archive/{YYYY-MM}.html` (4 files; if the `#date` moved the post to a new month, both old and new month archives upload)
- Full rebuild (`python -m autopublish rebuild`): all post pages + `index.html` + `rss.xml` + every `archive/YYYY-MM.html`

**Individual post URLs:** `https://fromtheabysmal.net/posts/YYYY-MM-DD-slug.html`

**Month archive URLs:** `https://fromtheabysmal.net/archive/YYYY-MM.html`

**RSS feed:** `https://fromtheabysmal.net/rss.xml`

---

## Email accounts

| Address | Purpose |
|---------|---------|
| `fromtheabysmalautopublish@gmail.com` | Pipeline sends from here; Esther replies to here |
| `mutativedesign@gmail.com` | Esther's address — receives publish notifications |
| `thehereticalinvestigator@gmail.com` | Kiryll's address — receives veto witness emails |

---

## Notes

- The pipeline only runs while Esther's Mac is on and the user session is active. Missed launchd firings are not retried. To run a missed weekday job manually, see the "Run a job manually" section above. **[DEFERRED]** A more automated fix would be to store `last_successful_weekday_run` in `state.json` and have `veto-check` fire the weekday pipeline if a publish day has passed without a run and the queue is empty — but this adds complexity and Esther is happy running it manually for now.
- Claude is called via the Claude CLI (`subprocess`). If Claude is unavailable, ranking and editing fall back to heuristics.
- `state.json` is the source of truth for what has been published. Deleting an entry from `published` would allow a post to be re-submitted, but this should be done carefully.
- The SFTP password and email app password are stored in plaintext in `config.yaml`. Don't commit that file.
- **Title is locked at scan time, but re-publish updates it.** The title is extracted from the `# Heading` when the pipeline queues the post. Re-publish on edit (`republish_if_changed`) now re-reads the heading from the file and updates `state.json` if it changed — so editing the heading in iA Writer will propagate on the next veto-check run (within 30 min). Before this fix, the cached title was always used regardless of file edits.
- **Title extraction** (`editor.py:_title_from_text`): strips the leading `#`, removes `#tag` and `#date` tokens, then calls `.strip()` to trim whitespace. Titles ending in `(N)` (like series numbers) are preserved correctly.
- **Source files can live in subfolders of `drafts_path`.** iA Writer lets Esther move already-published `.txt` files into subfolders (e.g. `x - published/`) to declutter her drafts view. The scanner already handles this because it uses `rglob`. `publisher._find_source()` does the same for `republish_if_changed` and `full_rebuild`: it first checks the top level, then falls back to a recursive search by bare filename. State.json stores only the bare filename, so renaming the source file **will** break the link — update the `source` field manually if you rename.
- **`publisher.publish()` injects the post-being-published into its in-memory state before rebuilding index/rss/archive.** The caller (`veto.process_queue`) records the publish in `state.json` only *after* `publish()` returns, so a fresh `state_module.load()` inside `publish()` would not include the new post. Without this injection, `index.html` / `rss.xml` / the month archive get rebuilt from a stale list and uploaded without the new post. The `save()`-then-`publish()` ordering was kept (rather than reversing it) because it preserves "don't record state if SFTP fails" semantics.

---

## converter.py behaviour

`autopublish/converter.py` converts a draft's markdown body to inner body HTML. It returns **only the paragraph/list/footnote HTML** — no doctype, no `<head>`, no `<h1>`, no revision dates. The caller (`builder.py`) wraps this in the full page template.

Key behaviours:
- **Paragraphs**: blocks separated by blank lines become `<p>` elements. Internal single newlines (iA Writer soft-wraps) are collapsed to spaces.
- **Lists**: a block whose first line starts with `- ` is rendered as a nested `<ul><li>` tree. Indentation is tab-based (one tab per level). Inline markdown and footnotes work inside list items.
- **Dividers**: a line of three or more dashes (`---`) becomes `<p class="post-divider">· · ·</p>`.
- **Inline formatting**: `**bold**`, `*italic*`, `__bold__`, `_italic_`.
- **Footnotes**: `[^footnote text]` inline — the text becomes the footnote body, rendered in a `<div class="footnotes">` at the bottom with numbered superscript links.
- **Title heading**: a leading `# Title` line is stripped from the body (the title is passed separately by the caller).
- **Revision dates**: handled by `builder.render_post_page()`, not converter.

## builder.py behaviour

`autopublish/builder.py` generates all site artifacts. No API calls — pure Python, deterministic.

- **`render_post_page(title, slug, date, body_html, revision_dates, site_url)`** — full HTML page with `<head>` (charset, viewport, fonts, canonical, og tags, style.css, RSS autodiscovery). Body: site header, `<nav class="post-nav">` back-link, `<article class="post">` with `<h1>` title + date + `<div class="post-body">` content, second `<nav class="post-nav post-nav-bottom">` back-link, site footer. Revision dates (if any) render as `<p class="post-history">Last revised Month D, YYYY.</p>` — only the most recent date.
- **`render_index(posts, site_url, site_path)`** — generates `index.html`. Reads the 10 most recent post HTML files to extract their `post-body` content for inline rendering. Builds the archive nav (year `<details>` → month `<a>` links — no post titles in the nav) and renders it without any `open` attribute, so years start collapsed.
- **`render_month_archive(year, month, all_posts, site_url, site_path)`** — generates `archive/YYYY-MM.html`. Same chrome as the index but renders **every** post from that month inline (no 10-post cap). The current month's link in the archive nav gets a `current` class.
- **`render_rss(posts, site_url, site_path)`** — generates `rss.xml`. Last 20 posts, full body HTML in CDATA blocks, RFC 2822 dates.
- **`month_pages(posts)`** — returns the list of `(year, month)` tuples that have posts, newest-first. Used by `full_rebuild` to enumerate every month archive page.
- **`post_description(html_body)`** — strips HTML tags, returns first ~200 chars trimmed to word boundary. Used for `og:description`.
- **`_extract_post_body(post_file)`** — extracts the inner content of `<div class="post-body">` from a generated post file. Falls back to stripping `<h1>` from `<body>` content for old-format files (pre-rebuild).
- **`_render_inline_posts(posts, posts_dir, site_url)`** — shared helper used by both `render_index` and `render_month_archive` to build the `<article class="post">` blocks (with `<h2><a>` title links) separated by `<hr class="post-separator">`.

### Design decisions worth knowing
- Posts are sorted by `slug[:10]` (the date prefix), not `post["date"]`. The `date` field in state.json can be the pipeline processing date; the slug date reflects any `#date` override and is authoritative.
- Archive nav has no `open` attribute on `<details>` elements — years always start collapsed. Post titles are deliberately never rendered inside the archive nav itself.
- Prev/next post navigation: deliberately skipped.
- RSS: 20 posts, full body HTML in CDATA blocks.

---

## Standing instruction for Claude

When working on this codebase, update this CLAUDE.md file whenever you discover something non-obvious about how the system works, fix a bug with a surprising root cause, or identify a behaviour that would confuse a future session. Do this without being asked.

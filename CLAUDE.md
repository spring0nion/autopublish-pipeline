# autopublish

An automated publishing pipeline for [fromtheabysmal.net](https://fromtheabysmal.net). It watches Esther's iA Writer drafts, picks the best one, runs a light copy-edit via Claude, gives Esther a 4-hour veto window by email, and publishes automatically if she doesn't object. It also watches already-published posts for edits and re-publishes them when the source file changes.

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
| `VETO` | Post is delayed. Veto count incremented. Kiryll is notified. Draft re-enters the pool with a score penalty. |
| Anything over 100 characters | Treated as an edited version. Her text is published instead of Claude's. The edit is written back to the source `.txt` file. |
| No reply | Post publishes automatically when the deadline passes. |

### The veto-check job

Runs **every 30 minutes**. Does two things:
1. Checks the pipeline inbox for replies and processes the queue (publish, veto, or wait)
2. Scans all published posts for source file changes — if a `.txt` has been modified since last publish, re-converts and re-uploads the HTML automatically

### The weekend job

Runs at **4pm Saturday**. Claude picks the best post from the last 7 days and emails Esther a formatted version ready to paste into Substack. The email is sent as HTML so that copying the body and pasting into Substack preserves all formatting (italics, paragraph breaks, etc.). The subject line uses the actual post title — no Claude-generated Substack title.

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
- Revision dates appear at the bottom of each post in grey: *Revised April 17, 2026.*

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
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.weekend.plist
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

This unloads any existing jobs, re-creates the symlinks in `~/Library/LaunchAgents/`, and reloads all three.

### Run a job manually

```bash
cd "/Users/esther/Development/autopublish pipeline"
source venv/bin/activate
python -m autopublish weekday
python -m autopublish veto-check
python -m autopublish weekend
python -m autopublish scan          # preview only — lists eligible drafts, no publishing
```

### Pause publishing without stopping the jobs

Add `#priority` to a draft you want to hold back if you need a break, or just reply `VETO` to each notification. After 5 vetoes of the same piece a warning is logged.

---

## Logs

All job output goes to the `logs/` directory:

```
logs/weekday.log
logs/vetocheck.log
logs/weekend.log
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
| `autopublish/publisher.py` | HTML generation, posts.js update, SFTP upload, post-publish edit detection |
| `autopublish/converter.py` | Markdown-to-HTML conversion |
| `autopublish/notifier.py` | Email and macOS notifications |
| `autopublish/state.py` | state.json read/write helpers |
| `autopublish/weekend.py` | Substack curation |

---

## Site architecture

The site (`~/Documents/from the abysmal (site)/`) is a static single-page app:

- `index.html` — the only page; all posts render inline here
- `style.css` — all styles including dark mode
- `app.js` — fetches post HTML files, extracts their body content, renders them as articles
- `posts.js` — a simple array of post filenames in newest-first order; updated on each publish
- `posts/YYYY-MM-DD-slug.html` — individual post files (bare HTML, unstyled, used only as data sources by app.js)

There are no clickable links to individual post pages. Everything is rendered on index.html.

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

---

## converter.py behaviour

`autopublish/converter.py` converts a draft's markdown body to the bare HTML format the site expects.

Key behaviours:
- **Paragraphs**: blocks separated by blank lines become `<p>` elements. Internal single newlines (iA Writer soft-wraps) are collapsed to spaces.
- **Lists**: a block whose first line starts with `- ` is rendered as a nested `<ul><li>` tree. Indentation is tab-based (one tab per level). Inline markdown and footnotes work inside list items.
- **Dividers**: a line of three or more dashes (`---`) becomes `<p class="post-divider">· · ·</p>`.
- **Inline formatting**: `**bold**`, `*italic*`, `__bold__`, `_italic_`.
- **Footnotes**: `[^footnote text]` inline — the text becomes the footnote body, rendered in a `<div class="footnotes">` at the bottom with numbered superscript links.
- **Title heading**: a leading `# Title` line is stripped from the body (the title is passed separately and emitted as `<h1>`).
- **Revision dates**: passed in as `revision_dates` list; rendered as `<p class="post-history">Revised Month D, YYYY.</p>` at the bottom.
- The output is a complete `<!doctype html>` document with no CSS link — bare HTML used as a data source by `app.js`.

---

## Standing instruction for Claude

When working on this codebase, update this CLAUDE.md file whenever you discover something non-obvious about how the system works, fix a bug with a surprising root cause, or identify a behaviour that would confuse a future session. Do this without being asked.

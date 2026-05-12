# autopublish

An automated publishing pipeline for writers who want their work to get out the door without having to decide, daily, that it's time.

Watches a folder of plain-text drafts, picks the best one using Claude, runs a light copy-edit (mechanical fixes only — typos, punctuation), then holds the post for a configurable veto window before publishing automatically to a static site over SFTP. While the post is queued, you can reply to the notification email to kill it, or just edit the source file and the pipeline picks up the latest version at publish time.

Live example: [fromtheabysmal.net](https://fromtheabysmal.net)

---

## What this is and isn't

This is a personal publishing tool, not a CMS. It's built around one writer's workflow: drafts in [iA Writer](https://ia.writer.com/) (plain `.txt` files), a static site hosted over SFTP, and a Mac running 24/7. If your setup looks roughly like that, you can adapt it. If you want a database, a web UI, or multi-author support, this is not the right starting point.

**Requirements:**
- macOS (uses launchd for scheduling)
- [Claude Code](https://claude.ai/code) CLI installed and authenticated (`claude` available in your `PATH`)
- iA Writer, or any writing app that saves plain `.txt` files to a folder
- SFTP access to your web host
- A Gmail account to send and receive pipeline notifications (or adapt `notifier.py` for another provider)
- Python 3.10+

---

## How it works

### The publish pipeline

Runs on a schedule (default: Monday, Wednesday, Friday at noon).

1. **Scan** — reads all `.txt` files from your drafts folder, filters out published/excluded/too-short ones, scores each by word count, recency, whether it has a proper ending, and veto history
2. **Rank** — passes the top 10 candidates to Claude, which picks the best one for today
3. **Edit** — Claude runs a light copy-edit on the chosen draft: mechanical fixes only (typos, punctuation), no rewrites, no smoothing. Returns a title, slug, and a brief editorial note. If Claude is unavailable, the piece is queued unedited.
4. **Queue** — the post is held in `state.json` with a veto deadline
5. **Notify** — you get an email with the full text, the editorial note, and any questions Claude flagged

### The veto window

After the notification, you have a configurable window (default: 4 hours) to respond.

| Action | Effect |
|--------|--------|
| Reply to the email (anything, including `VETO`) | Post is delayed; veto count incremented; a witness address is notified; draft re-enters the pool with a score penalty |
| No reply | Post publishes automatically when the deadline passes |

To change the text before it publishes, edit the `.txt` file in iA Writer. The pipeline re-reads the source at publish time and uses the latest version. If you've changed the heading, the slug and URL are rebuilt accordingly.

### The veto-check job

Runs every 30 minutes. Does two things:

1. Checks the pipeline inbox for replies and processes the queue (publish, veto, or wait)
2. Scans all published posts for source file changes — if a `.txt` has been modified since last publish, re-converts and re-uploads the HTML automatically

Post-publish edits propagate within 30 minutes with no action required.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourname/autopublish-pipeline.git
cd autopublish-pipeline
```

### 2. Install dependencies

```bash
bash setup.sh
```

This creates a `venv/` and installs the two dependencies: `paramiko` (SFTP) and `pyyaml`.

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
drafts_path: ~/path/to/your/drafts/   # folder where your .txt files live
site_path: ~/path/to/your/site/        # local site folder (generated files go here)
site_url: https://yoursite.example.com

sftp:
  host: your-sftp-host.example.com
  port: 22
  username: your-username
  password: your-sftp-password
  remote_root: /public_html            # remote path where site files should land

email:
  pipeline_address: yourpipeline@gmail.com   # sends notifications from here
  pipeline_password: your-app-password       # Gmail app password (not your account password)
  notify_esther: you@example.com             # receives publish notifications
  notify_kiryll: witness@example.com         # receives veto notifications (can be the same address)
  smtp_host: smtp.gmail.com
  smtp_port: 587
  imap_host: imap.gmail.com
  imap_port: 993

schedule:
  weekday_hour: 12       # hour to run the publish pipeline (24h)
  veto_window_hours: 4   # hours to wait before auto-publishing

editorial:
  min_words: 500         # drafts shorter than this are ignored
  min_chars: 500
  max_veto_before_warning: 5
```

**Gmail app password:** go to your Google account → Security → 2-Step Verification → App passwords. Generate one for "Mail". Use that as `pipeline_password`. Standard account passwords won't work with SMTP.

`config.yaml` is in `.gitignore` and should never be committed.

### 4. Prepare your site folder

The pipeline generates HTML into `site_path`. It expects this structure to already exist:

```
site/
  posts/        ← generated post pages go here
  archive/      ← generated month archive pages go here
  style.css     ← your stylesheet (not managed by the pipeline)
  title.png     ← site logo, if you use one
```

Create the folders manually. The pipeline will not create them.

The pipeline uploads to your SFTP host but does not manage `style.css` — deploy that manually when you change it.

### 5. Initialize state

The pipeline tracks published posts and veto counts in `state.json`. On first run it creates this file automatically. If you're migrating an existing site, you can pre-populate the `published` array — see `state.py` for the schema.

### 6. Install the launchd jobs

```bash
bash install_plists.sh
```

This symlinks the plists from `plists/` into `~/Library/LaunchAgents/` and loads them. The pipeline is now scheduled.

**Before running this**, open the two plist files in `plists/` and update the hardcoded paths to match your setup:

- `ProgramArguments` — the path to your venv's Python
- `WorkingDirectory` — the path to your project folder
- `StandardOutPath` / `StandardErrorPath` — where logs should go
- `EnvironmentVariables.PATH` — must include your venv's `bin/` and wherever `claude` is installed

---

## Draft tags

Add these anywhere in a `.txt` file to control pipeline behavior:

| Tag | Effect |
|-----|--------|
| `#nopublish` | Permanently excludes the file from the pipeline |
| `#priority` | Jumps to the front of the queue (score +1000) |
| `#date YYYY-MM-DD` | Overrides the post date used for the slug and URL |

Tags can appear inline in a heading line or on their own line. `#date` is stripped from the published text.

---

## Running manually

```bash
cd /path/to/autopublish-pipeline
source venv/bin/activate

python -m autopublish weekday       # full pipeline: scan → rank → edit → queue → notify
python -m autopublish veto-check    # check inbox, publish if deadline passed, re-publish edited posts
python -m autopublish scan          # preview only — lists eligible drafts with scores, no publishing
python -m autopublish rebuild       # rebuild all post pages, index.html, rss.xml, archives and upload
```

The pipeline only fires launchd jobs while your Mac is on and your user session is active. Missed scheduled runs are not retried automatically — run the `weekday` command manually to catch up.

---

## Site output

The pipeline generates a fully static site with no JavaScript required:

| File | What it is |
|------|------------|
| `posts/YYYY-MM-DD-slug.html` | Individual post pages |
| `archive/YYYY-MM.html` | Per-month archive pages (every post from that month, rendered inline) |
| `index.html` | Homepage with the 10 most recent posts inline and a collapsible year/month archive nav |
| `rss.xml` | RSS 2.0 feed, last 20 posts, full body HTML |

**Per-publish upload set:** the new post page + `index.html` + `rss.xml` + the relevant month archive (4 files). Full rebuild uploads everything.

The archive nav shows years at rest; clicking a year reveals its months. Post titles are never listed in the nav — readers see them by clicking through to a month page or post.

### Adapting the templates

All HTML generation is in `autopublish/builder.py`. It's plain Python string templates — no template engine. Edit `render_post_page()`, `render_index()`, and `render_month_archive()` to change the site structure. After any template change, run `python -m autopublish rebuild` to regenerate and upload everything.

Markdown-to-HTML conversion is in `autopublish/converter.py`. Supported: paragraphs, `**bold**`, `*italic*`, nested `- ` lists, `---` dividers, and `[^inline footnotes]`. It does not use a Markdown library — the converter is written for iA Writer's specific conventions.

---

## Controlling the scheduled jobs

```bash
# Check what's running
launchctl list | grep abysmal

# Stop all jobs
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.*.plist

# Stop one job
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.vetocheck.plist

# Restart one job
launchctl load ~/Library/LaunchAgents/com.abysmal.autopublish.weekday.plist

# Reinstall after editing a plist
bash install_plists.sh
```

Each line from `launchctl list` shows: PID (or `-` if not running), last exit code, job name. Exit code `0` is normal.

---

## Logs

```
logs/weekday.log
logs/vetocheck.log
```

```bash
tail -f logs/vetocheck.log
```

---

## Key files

| File | Purpose |
|------|---------|
| `config.yaml` | All configuration — credentials, paths, schedule (not committed) |
| `config.example.yaml` | Template for config.yaml |
| `state.json` | Published post registry, veto counts, active queue |
| `autopublish/scanner.py` | Draft discovery and scoring |
| `autopublish/ranker.py` | Claude ranking pass |
| `autopublish/editor.py` | Claude editorial pass |
| `autopublish/veto.py` | Email reply detection and queue processing |
| `autopublish/publisher.py` | Publish flow, SFTP upload, post-publish edit detection, full rebuild |
| `autopublish/builder.py` | Site artifact rendering: post pages, index, RSS, month archives |
| `autopublish/converter.py` | Plain-text to body HTML conversion |
| `autopublish/notifier.py` | Email and macOS notifications |
| `autopublish/state.py` | state.json read/write helpers |
| `autopublish/prompts.py` | Claude prompts for ranking and editing |
| `autopublish/cli.py` | Command-line entry point |
| `plists/` | launchd job definitions |
| `install_plists.sh` | Registers/reinstalls the launchd jobs |
| `setup.sh` | Creates venv and installs dependencies |

---

## Claude integration

The pipeline calls Claude via the Claude Code CLI (`claude -p "..." --output-format json`). Both the ranking and editorial passes use it. If Claude is unavailable or times out, ranking aborts the run (rather than guessing); the editorial pass falls back to queueing the piece unedited, so you still get a notification and a veto window.

The prompts are in `autopublish/prompts.py`. The editorial prompt is deliberately conservative — it instructs Claude to fix mechanical errors only and explicitly not to rewrite, smooth, restructure, or change the author's voice.

---

## Scoring

Drafts are scored before ranking to filter down to the top 10 candidates passed to Claude. The score is a heuristic — Claude makes the final call.

Factors:
- Word count (longer scores higher, up to a point)
- Recency of last modification
- Whether the piece appears to have a proper ending (doesn't trail off mid-sentence)
- `#priority` tag (+1000, effectively guarantees selection)
- Repeated vetoes (score penalty per veto)

The scorer is in `autopublish/scanner.py`. Adjust the weights there if the heuristic isn't surfacing the right pieces.

---

## Adapting for a different writing app

The scanner looks for `.txt` files in `drafts_path` (recursively, so subfolders work). Any app that saves plain text files to a folder on disk will work. iA Writer-specific behavior:

- The default `drafts_path` in `config.example.yaml` points to iA Writer's sandboxed documents folder on macOS
- iA Writer soft-wraps lines with single newlines; the converter collapses these to spaces within a paragraph (double newlines become paragraph breaks)

If your app uses a different newline convention or file extension, adjust `scanner.py` and `converter.py` accordingly.

---

## License

MIT.

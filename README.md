# autopublish

An automated publishing pipeline for [fromtheabysmal.net](https://fromtheabysmal.net).

Watches iA Writer drafts, picks the best one, runs a light copy-edit via Claude, gives a 4-hour veto window by email, and publishes automatically if there's no objection. Also watches published posts for edits and re-publishes them when the source file changes.

---

## Setup

1. Copy `config.example.yaml` to `config.yaml` and fill in your SFTP credentials and email passwords.
2. Create a virtual environment and install dependencies:
   ```bash
   bash setup.sh
   ```
3. Register the launchd jobs:
   ```bash
   bash install_plists.sh
   ```

---

## Schedule

| Job | When | What it does |
|-----|------|--------------|
| Weekday | Mon/Wed/Fri at 12pm | Picks a draft, edits it, queues it, emails a veto notice |
| Veto-check | Every 30 min | Processes email replies; re-publishes edited posts |
| Weekend | Saturday at 4pm | Emails a formatted post ready to paste into Substack |

The pipeline only runs while the Mac is on and the user session is active. Missed jobs can be run manually (see below).

---

## Draft tags

Add these anywhere in a `.txt` file:

| Tag | Effect |
|-----|--------|
| `#nopublish` | Permanently excludes the file |
| `#priority` | Jumps to the front of the queue |
| `#date YYYY-MM-DD` | Overrides the post date |

---

## Veto window

After a draft is queued, reply to the notification email within 4 hours:

| Reply | Effect |
|-------|--------|
| `VETO` | Post is delayed; draft re-enters pool with a score penalty |
| Reply over 100 characters | Your text is published instead of Claude's edit |
| No reply | Post publishes automatically |

---

## Running manually

```bash
cd "/Users/esther/Development/autopublish pipeline"
source venv/bin/activate

python -m autopublish weekday
python -m autopublish veto-check
python -m autopublish weekend
python -m autopublish scan      # preview only — lists eligible drafts
```

---

## Logs

```
logs/weekday.log
logs/vetocheck.log
logs/weekend.log
```

```bash
tail -f "/Users/esther/Development/autopublish pipeline/logs/vetocheck.log"
```

---

## Controlling launchd jobs

```bash
launchctl list | grep abysmal          # check status
launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.*.plist   # stop all
launchctl load ~/Library/LaunchAgents/com.abysmal.autopublish.weekday.plist  # restart one
bash install_plists.sh                 # reinstall after editing a plist
```

---

## Key files

| File | Purpose |
|------|---------|
| `config.yaml` | SFTP credentials, email settings (not committed) |
| `state.json` | Published post registry, veto counts, active queue |
| `autopublish/scanner.py` | Draft discovery and scoring |
| `autopublish/ranker.py` | Claude ranking pass |
| `autopublish/editor.py` | Claude editorial pass |
| `autopublish/veto.py` | Email reply detection and queue processing |
| `autopublish/publisher.py` | HTML generation, SFTP upload, edit detection |
| `autopublish/converter.py` | Markdown-to-HTML conversion |
| `autopublish/notifier.py` | Email and macOS notifications |
| `autopublish/weekend.py` | Substack curation |

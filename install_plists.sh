#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_DIR="$SCRIPT_DIR/plists"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$LOG_DIR"

for plist in "$PLIST_DIR"/*.plist; do
    name=$(basename "$plist")
    dest="$LAUNCH_AGENTS/$name"

    # Unload if already loaded
    launchctl unload "$dest" 2>/dev/null || true

    # Symlink
    ln -sf "$plist" "$dest"
    echo "Linked $name → $dest"

    # Load
    launchctl load "$dest"
    echo "Loaded $name"
done

echo ""
echo "All plists installed. The pipeline is now running."
echo "  Weekday: Mon/Wed/Fri at 8:00 AM"
echo "  Veto check: every 30 minutes"
echo ""
echo "To stop: launchctl unload ~/Library/LaunchAgents/com.abysmal.autopublish.*.plist"
echo "But you'd have to do that for each one. And Kiryll would know."

#!/bin/bash
# Store a Claude CLI token (from `claude setup-token`) in config.yaml.
#
# `claude setup-token` only PRINTS the token; it does not install it anywhere.
# Until it's stored here, the CLI keeps using its expired keychain login and
# every ranking pass dies with a 401.
#
# Usage:  bash set_claude_token.sh      (prompts; nothing echoed, nothing in history)

set -e
cd "$(dirname "$0")"

if [ ! -f config.yaml ]; then
    echo "No config.yaml here. Run this from the pipeline directory." >&2
    exit 1
fi

printf 'Paste the token from `claude setup-token` (input hidden), then Enter:\n> '
read -rs TOKEN
echo

TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"

if [ -z "$TOKEN" ]; then
    echo "Nothing pasted. Aborted." >&2
    exit 1
fi

case "$TOKEN" in
    sk-ant-oat*) ;;
    *) echo "That doesn't look like a setup-token (expected it to start with sk-ant-oat). Aborted." >&2; exit 1 ;;
esac

cp config.yaml "config.yaml.bak.$(date +%Y%m%d-%H%M%S)"

TOKEN="$TOKEN" python3 - <<'PY'
import os, re, pathlib
token = os.environ["TOKEN"]
p = pathlib.Path("config.yaml")
text = p.read_text()
line = f'claude_oauth_token: "{token}"'
if re.search(r'^claude_oauth_token:.*$', text, re.M):
    text = re.sub(r'^claude_oauth_token:.*$', line, text, count=1, flags=re.M)
else:
    text = text.rstrip("\n") + "\n\n" + line + "\n"
p.write_text(text)
PY

chmod 600 config.yaml
echo "Token stored in config.yaml (backup written alongside it)."
echo "Testing it now..."

if venv/bin/python3 -c "
from autopublish.claude_cli import call_claude
r = call_claude('Reply with exactly this JSON and nothing else: {\"ok\": true}')
print('Claude responded:', r)
"; then
    echo
    echo "Working. Run the job with:  venv/bin/python3 -m autopublish weekday"
else
    echo
    echo "Still failing - see the error above." >&2
    exit 1
fi

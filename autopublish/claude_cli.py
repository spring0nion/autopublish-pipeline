"""Shared Claude CLI invocation for the ranking and editorial passes.

Both ranker.py and editor.py shell out to `claude -p ... --output-format json`.
They used to carry near-identical copies of this function, and both copies had the
same blind spot: the CLI reports API-level failures (expired OAuth token, rate
limits, server errors) as a *zero-length stderr* plus an error payload on stdout —

    {"is_error": true, "api_error_status": 401, "result": "Failed to authenticate..."}

Logging `result.stderr` therefore produced the empty message `Claude CLI failed: `,
which is how an expired OAuth token silently killed every weekday run for two
months. Always read the stdout payload and check `is_error`.
"""
import json
import logging
import os
import subprocess

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300

# Substrings that mean "the login is dead", not "the service hiccuped".
# The CLI words this inconsistently: a fresh expiry surfaces as an
# `authentication_error` 401, while a fully-lapsed token gives a bare
# "Not logged in · Please run /login" with no api_error_status at all.
_AUTH_MARKERS = (
    "authentication_error",
    "oauth",
    "re-authenticate",
    "invalid api key",
    "invalid x-api-key",
    "not logged in",
    "/login",
)


class ClaudeUnavailable(Exception):
    """Raised when the Claude CLI could not produce a usable response.

    `reason` is a one-line human-readable summary; `hint` (optional) is the
    suggested fix, surfaced in the failure email.
    """

    def __init__(self, reason, hint=None):
        super().__init__(reason)
        self.reason = reason
        self.hint = hint


def _hint_for(status, detail):
    """Map an API status / error blob to an actionable suggestion, or None."""
    blob = f"{status or ''} {detail}".lower()

    if status == 401 or status == 403 or any(m in blob for m in _AUTH_MARKERS):
        return ("The CLI's login has expired. Run `claude setup-token` in Terminal, "
                "then paste the printed token into config.yaml as `claude_oauth_token`. "
                "setup-token only PRINTS the token \u2014 it does not install it, so the "
                "CLI keeps using the dead keychain credential until you store it.")
    if status == 429 or "rate limit" in blob or "overloaded" in blob:
        return "Rate limited or overloaded. The next scheduled run will retry on its own."
    if isinstance(status, int) and 500 <= status < 600:
        return "Anthropic-side error. The next scheduled run will retry on its own."
    return None


def _claude_env():
    """Environment for the `claude` subprocess, with the OAuth token injected.

    `claude setup-token` PRINTS a long-lived token but does not install it anywhere:
    the CLI keeps reading the (expired) "Claude Code-credentials" keychain entry and
    keeps returning 401 until the token is supplied as CLAUDE_CODE_OAUTH_TOKEN. An
    `export` in Esther's interactive shell would not help the launchd jobs either --
    they get a bare environment. So the token lives in config.yaml (gitignored,
    alongside the SFTP and email passwords) and is injected here, which covers both
    the scheduled runs and manual ones.

    An already-set CLAUDE_CODE_OAUTH_TOKEN wins, so a temporary `export` can still be
    used to test a new token before committing it to config.yaml.
    """
    env = os.environ.copy()
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return env

    try:
        from autopublish import config
        token = (config.load().get("claude_oauth_token") or "").strip()
    except Exception as exc:  # missing/unreadable config is not fatal here
        log.warning("Could not read claude_oauth_token from config.yaml: %s", exc)
        return env

    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    else:
        log.warning(
            "No claude_oauth_token in config.yaml and no CLAUDE_CODE_OAUTH_TOKEN in "
            "the environment - the CLI will fall back to its stored login, which may "
            "have expired."
        )
    return env


def call_claude(prompt_text):
    """Call Claude via the CLI and return the parsed JSON response.

    Raises ClaudeUnavailable (with a specific reason) on any failure.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt_text, "--output-format", "json"],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            env=_claude_env(),
        )
    except subprocess.TimeoutExpired:
        raise ClaudeUnavailable(
            f"Claude CLI timed out after {TIMEOUT_SECONDS}s",
            "The Mac may have slept mid-call, or the prompt was oversized.",
        )
    except FileNotFoundError:
        raise ClaudeUnavailable(
            "The `claude` CLI was not found on PATH",
            "Check the PATH entry in plists/com.abysmal.autopublish.weekday.plist, "
            "or reinstall the CLI.",
        )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    outer = None
    if stdout:
        try:
            outer = json.loads(stdout)
        except json.JSONDecodeError:
            outer = None

    # API-level failure: the process may still exit 0, so check this before returncode.
    if isinstance(outer, dict) and outer.get("is_error"):
        status = outer.get("api_error_status")
        detail = str(outer.get("result") or "").strip() or "no detail provided"
        label = f"Claude API error {status}" if status else "Claude returned an error"
        raise ClaudeUnavailable(f"{label}: {detail[:500]}", _hint_for(status, detail))

    if result.returncode != 0:
        detail = stderr or stdout or "no output on stdout or stderr"
        raise ClaudeUnavailable(
            f"Claude CLI exited {result.returncode}: {detail[:500]}",
            _hint_for(None, detail),
        )

    if outer is None:
        raise ClaudeUnavailable(
            f"Claude CLI returned unparseable output: {(stdout or stderr or 'nothing')[:300]}"
        )

    # `claude --output-format json` wraps the reply in {"result": "..."}.
    text = str(outer.get("result", stdout)).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ClaudeUnavailable(
            f"Claude's reply was not valid JSON: {text[:300]}",
            "Usually transient — the next scheduled run will retry.",
        )

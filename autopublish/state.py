import json
from pathlib import Path
from datetime import datetime


STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"

DEFAULT = {
    "published": [],      # [{source, slug, date, title}]
    "queue": None,         # {source, slug, title, edited_text, veto_deadline, message_id} or None
    "veto_counts": {},     # {filename: count}
    "nopublish": [],       # [filename, ...]
}


def load():
    if not STATE_PATH.exists():
        return dict(DEFAULT)
    with open(STATE_PATH) as f:
        return json.load(f)


def save(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def is_published(state, source_filename):
    return any(p["source"] == source_filename for p in state["published"])


def record_publish(state, source, slug, title, source_mtime=None):
    state["published"].append({
        "source": source,
        "slug": slug,
        "title": title,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source_mtime": source_mtime,
        "edit_history": [],
    })
    state["queue"] = None
    save(state)


def record_revision(state, slug, revision_date):
    """Append a revision date to a published post's edit_history."""
    for post in state["published"]:
        if post["slug"] == slug:
            post.setdefault("edit_history", []).append(revision_date)
            save(state)
            return


def update_source_mtime(state, slug, new_mtime):
    """Update the stored source file mtime for a published post."""
    for post in state["published"]:
        if post["slug"] == slug:
            post["source_mtime"] = new_mtime
            save(state)
            return


def set_queue(state, source, slug, title, edited_text, veto_deadline, message_id=None):
    state["queue"] = {
        "source": source,
        "slug": slug,
        "title": title,
        "edited_text": edited_text,
        "veto_deadline": veto_deadline.isoformat(),
        "message_id": message_id,
    }
    save(state)


def increment_veto(state, source):
    state["veto_counts"][source] = state["veto_counts"].get(source, 0) + 1
    state["queue"] = None
    save(state)
    return state["veto_counts"][source]


def get_veto_count(state, source):
    return state["veto_counts"].get(source, 0)


def queue_deadline_passed(state):
    if not state["queue"]:
        return False
    deadline = datetime.fromisoformat(state["queue"]["veto_deadline"])
    return datetime.now() >= deadline

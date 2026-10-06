"""progress: record every attempt at a task in data/progress.json.

An attempt runs from `start` until a check passes. The file looks like:

    {"attempts": [
        {"task_id": "pod-web", "concept": "pods",
         "started_at": "2026-10-05T20:41:07-04:00",
         "passed": true, "seconds": 192, "hints": 1, "failed_checks": 2},
        ...
    ]}

Attempts are only ever added or updated, never deleted, so the file is
your full learning history, oldest attempt first.
"""

import json
from datetime import datetime
from pathlib import Path

PROGRESS_FILE = Path(__file__).resolve().parent / "data" / "progress.json"


def _now():
    # Local time with its UTC offset, e.g. 2026-10-05T20:41:07-04:00. The
    # offset keeps timestamps unambiguous across time zones and clock
    # changes, and lets us subtract two of them to get a duration.
    return datetime.now().astimezone()


def load():
    """Return the progress data, or an empty history if there's none yet."""
    if not PROGRESS_FILE.exists():
        return {"attempts": []}
    return json.loads(PROGRESS_FILE.read_text())


def save(progress):
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    # Write a temporary file, then rename it over the real one. A rename
    # either fully happens or doesn't, so a crash halfway through writing
    # can't leave a broken progress.json and wipe your history.
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress, indent=2) + "\n")
    tmp.replace(PROGRESS_FILE)


def open_attempt(progress, task_id):
    """Return your latest attempt at this task if it hasn't passed yet, else None."""
    for attempt in reversed(progress["attempts"]):
        if attempt["task_id"] == task_id:
            return None if attempt["passed"] else attempt
    return None


def start_attempt(task):
    """Start the clock on a new attempt at `task`.

    If you already have an unfinished attempt at this task, keep that one
    instead and return True. Re-running start to re-read the prompt
    shouldn't reset your time or your hint count.
    """
    progress = load()
    if open_attempt(progress, task["id"]) is not None:
        return True

    progress["attempts"].append({
        "task_id": task["id"],
        # Copied from the task file, not looked up later, so history
        # stays correct even if the task is edited or deleted.
        "concept": task["concept"],
        "started_at": _now().isoformat(timespec="seconds"),
        "passed": False,
        "seconds": None,  # filled in when a check passes
        "hints": 0,
        "failed_checks": 0,
    })
    save(progress)
    return False


def record_hint(task_id):
    """Add one to the hint count of your open attempt at this task."""
    progress = load()
    attempt = open_attempt(progress, task_id)
    # No open attempt (e.g. you already passed): nothing to count against.
    if attempt is None:
        return
    attempt["hints"] += 1
    save(progress)


def record_check(task_id, passed):
    """Record a check result on your open attempt at this task.

    A failed check adds one to failed_checks; the attempt stays open. A
    passing check closes the attempt and records how long it took. Returns
    the updated attempt, or None if there was no open attempt.
    """
    progress = load()
    attempt = open_attempt(progress, task_id)
    if attempt is None:
        return None

    if passed:
        started = datetime.fromisoformat(attempt["started_at"])
        attempt["passed"] = True
        attempt["seconds"] = round((_now() - started).total_seconds())
    else:
        attempt["failed_checks"] += 1
    save(progress)
    return attempt

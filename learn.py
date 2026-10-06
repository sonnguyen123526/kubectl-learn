#!/usr/bin/env python3
"""kubectl-learn: learn kubectl by doing real tasks on a real kind cluster."""

import argparse
import json
import random
import shlex
import sys
from collections import Counter
from pathlib import Path

import yaml

import kube
import progress
import report
from verifiers import checks


# --- Paths ------------------------------------------------------------------
# Paths are built from this file's location, not the current directory,
# so the tool works no matter where you run it from.

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
DATA_DIR = ROOT / "data"
CURRENT_FILE = DATA_DIR / "current.json"


# --- Tasks ------------------------------------------------------------------

# Every task file must define all of these.
REQUIRED_FIELDS = ("id", "title", "prompt", "difficulty", "concept", "hint", "verifier")

# These are optional. Each is a list of kubectl commands, and each command
# is a list of words, e.g. [delete, pod, web, --ignore-not-found].
#   cleanup: deletes everything the task uses, including what you created.
#   setup:   creates the task's starting point, for tasks that need one.
COMMAND_FIELDS = ("cleanup", "setup")


def load_tasks():
    """Read every tasks/*.yaml file and return the tasks as a list of dicts.

    Files are sorted by name, so a numeric prefix (01-, 02-, ...) sets the
    order the tasks come in.
    """
    tasks = []
    seen_ids = set()
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        with path.open() as f:
            # safe_load only builds plain types (dicts, lists, strings,
            # numbers). yaml.load can build arbitrary Python objects, which
            # we never want from a data file.
            task = yaml.safe_load(f)
        # Check the file now and name it in the error, instead of failing
        # later with a bare KeyError that doesn't say which file is wrong.
        if not isinstance(task, dict):
            raise ValueError(f"{path.name}: expected a set of key: value fields")
        missing = [field for field in REQUIRED_FIELDS if field not in task]
        if missing:
            raise ValueError(f"{path.name}: missing {', '.join(missing)}")
        for field in COMMAND_FIELDS:
            task.setdefault(field, [])
            if not all(isinstance(cmd, list) for cmd in task[field]):
                raise ValueError(f"{path.name}: each {field} command must be a list, e.g. [delete, pod, web]")
        # data/current.json stores the id, so two tasks can't share one.
        if task["id"] in seen_ids:
            raise ValueError(f"{path.name}: duplicate id {task['id']!r}")
        seen_ids.add(task["id"])
        tasks.append(task)
    return tasks


def find_task(tasks, task_id):
    """Return the task with this id, or None if there isn't one."""
    for task in tasks:
        if task["id"] == task_id:
            return task
    return None


# --- Current task -----------------------------------------------------------
# Each command runs as a separate process, so anything we want to remember
# between commands has to be written to disk. data/current.json holds the
# id of the task you're working on, e.g. {"task_id": "pod-web"}.

def save_current_task_id(task_id):
    DATA_DIR.mkdir(exist_ok=True)
    CURRENT_FILE.write_text(json.dumps({"task_id": task_id}, indent=2) + "\n")


def load_current_task_id():
    """Return the saved task id, or None if no task has been started."""
    if not CURRENT_FILE.exists():
        return None
    return json.loads(CURRENT_FILE.read_text())["task_id"]


def load_current_task():
    """Return the current task's dict, or print why there isn't one and return None."""
    task_id = load_current_task_id()
    if task_id is None:
        print("No current task. Run: kubectl-learn start", file=sys.stderr)
        return None

    task = find_task(load_tasks(), task_id)
    if task is None:
        # The task's file was renamed or deleted after you started it.
        print(f"Current task {task_id!r} is no longer in tasks/. Run: kubectl-learn start", file=sys.stderr)
    return task


def unfinished_task(tasks, history):
    """Return the current task if you haven't passed it yet, else None."""
    task = find_task(tasks, load_current_task_id())
    if task is not None and progress.open_attempt(history, task["id"]) is not None:
        return task
    return None


# --- Cluster setup ----------------------------------------------------------

# Deleting a namespace can take a while, so allow more than kube.run's
# default 30 seconds.
SETUP_TIMEOUT = 120


def run_cleanup(commands):
    """Run cleanup commands, printing each one so you can see what's deleted."""
    for cmd in commands:
        print(f"  $ {shlex.join(['kubectl', *cmd])}")
        kube.run(cmd, timeout=SETUP_TIMEOUT)


def run_setup(task):
    """Create the task's starting point.

    The commands aren't printed: for some tasks, like debugging, they would
    give the answer away. They're in the task's YAML file.
    """
    for cmd in task["setup"]:
        kube.run(cmd, timeout=SETUP_TIMEOUT)


# --- Verifiers --------------------------------------------------------------

def find_verifier(name):
    """Return the function in verifiers/checks.py called `name`, or None.

    getattr(module, "some_name") is the same as writing module.some_name,
    except the name is a string chosen at runtime, here read from a task
    file.
    """
    # Only check_* names count. Otherwise a task file could name a helper
    # like "_get", or "kube", which checks.py imports.
    if not name.startswith("check_"):
        return None
    func = getattr(checks, name, None)
    return func if callable(func) else None


# --- Choosing a task --------------------------------------------------------
# start picks a task at random, weighted toward the concepts you're weakest
# in. Each concept gets a weight between MIN_WEIGHT and 1:
#
#   weight = MIN_WEIGHT + (1 - MIN_WEIGHT) * (1 - mastery)
#
# mastery 0% or never tried -> 1.0, 70% -> 0.37, 100% -> 0.1. A concept
# you've mastered still comes back for review, just 10 times less often
# than one you haven't learned yet.

MIN_WEIGHT = 0.1


def concept_weight(concept_attempts):
    """Return a concept's weight, given your attempts at it (empty = never tried)."""
    if not concept_attempts:
        return 1.0
    return MIN_WEIGHT + (1 - MIN_WEIGHT) * (1 - report.mastery(concept_attempts))


def choose_task(tasks, attempts):
    """Pick the next task, weighted toward weak concepts.

    Returns (task, chance): chance is the probability this task had of
    being picked, so start can show it.
    """
    # Skip the task you just did, if there's any other: practice sticks
    # better after a gap than straight away.
    candidates = tasks
    if attempts and len(tasks) > 1:
        candidates = [task for task in tasks if task["id"] != attempts[-1]["task_id"]]

    # Split each concept's weight between its tasks, so a concept isn't
    # picked more often just because it has more tasks.
    tasks_per_concept = Counter(task["concept"] for task in candidates)
    weights = []
    for task in candidates:
        concept_attempts = [a for a in attempts if a["concept"] == task["concept"]]
        weights.append(concept_weight(concept_attempts) / tasks_per_concept[task["concept"]])

    # random.choices picks with probability weight / sum(weights). It
    # returns a list (it can pick several at once), hence the [0].
    task = random.choices(candidates, weights=weights)[0]
    chance = weights[candidates.index(task)] / sum(weights)
    return task, chance


# --- Command handlers -------------------------------------------------------
# Each subcommand gets its own function. argparse passes in the parsed
# arguments (`args`), which we don't use yet but will need in later steps.
# A handler returns None on success, or an exit code (like 1) on failure.

def cmd_start(args):
    tasks = load_tasks()
    if not tasks:
        print(f"No tasks found in {TASKS_DIR}", file=sys.stderr)
        return 1

    history = progress.load()
    attempts = history["attempts"]

    # Still working on a task? Carry on with it rather than picking a new
    # one, so re-running start to re-read the prompt doesn't skip the task.
    unfinished = unfinished_task(tasks, history)
    task = unfinished
    # Naming a task (`start pod-web`) overrides that, e.g. for a demo or to
    # practice something specific.
    if args.task_id is not None:
        task = find_task(tasks, args.task_id)
        if task is None:
            ids = ", ".join(t["id"] for t in tasks)
            print(f"There's no task {args.task_id!r}. The tasks are: {ids}", file=sys.stderr)
            return 1

    if unfinished is not None and task["id"] == unfinished["id"]:
        note = "Resuming your unfinished attempt. The clock has been running since you first started it."
    else:
        if task is not None:
            note = "You chose this task."
        else:
            task, chance = choose_task(tasks, attempts)
            concept_attempts = [a for a in attempts if a["concept"] == task["concept"]]
            if concept_attempts:
                reason = f"your {task['concept']} mastery is {report.mastery(concept_attempts):.0%}"
            else:
                reason = f"you haven't tried {task['concept']} yet"
            note = f"Picked because {reason} ({chance:.0%} chance this time)."

        # Reset the cluster to the task's starting point. Done before the
        # clock starts, so setup time doesn't count against you.
        try:
            if task["cleanup"]:
                print("Clearing out anything left from earlier attempts:")
                run_cleanup(task["cleanup"])
            if task["setup"]:
                print("Creating the task's starting resources.")
                run_setup(task)
        except kube.KubectlError as err:
            print(f"ERROR: couldn't set up the cluster.\n{err}", file=sys.stderr)
            return 1
        if task["cleanup"] or task["setup"]:
            print()

        save_current_task_id(task["id"])
        progress.start_attempt(task)

    print(f"Task: {task['title']}  (concept: {task['concept']}, difficulty: {task['difficulty']}/3)")
    print(note)
    print()
    # .strip() drops the trailing newline that YAML's ">" block style adds.
    print(task["prompt"].strip())
    print()
    print("Stuck? Run: kubectl-learn hint")
    print("Done?  Run: kubectl-learn check")


def cmd_hint(args):
    task = load_current_task()
    if task is None:
        return 1

    progress.record_hint(task["id"])
    print(f"Hint: {task['hint'].strip()}")


def cmd_check(args):
    task = load_current_task()
    if task is None:
        return 1

    verifier = find_verifier(task["verifier"])
    if verifier is None:
        print(
            f"Task {task['id']!r} names verifier {task['verifier']!r}, "
            "but verifiers/checks.py has no check_ function by that name.",
            file=sys.stderr,
        )
        return 1

    try:
        passed, message = verifier()
    except checks.NotYet as err:
        # Your work looks right; Kubernetes is still acting on it. Not
        # recorded: checking a few seconds early isn't a mistake.
        print(f"NOT YET: {err} Check again in a few seconds.")
        return 1
    except kube.KubectlError as err:
        # kubectl itself failed (cluster down, wrong context, ...). That
        # says nothing about your work, so it's an ERROR, not a FAIL.
        print(f"ERROR: couldn't check the cluster.\n{err}", file=sys.stderr)
        return 1

    # Recorded only after the verifier ran: an ERROR above isn't a result.
    attempt = progress.record_check(task["id"], passed)

    if passed:
        print(f"PASS: {message}")
        # None if this task was already passed: re-checking doesn't count again.
        if attempt is not None:
            print(
                f"Time: {report.format_duration(attempt['seconds'])}  "
                f"Hints: {attempt['hints']}  Failed checks: {attempt['failed_checks']}"
            )
            print("Next task: kubectl-learn start")
        return None

    print(f"FAIL: {message}")
    print("Stuck? Run: kubectl-learn hint")
    return 1


def cmd_report(args):
    attempts = progress.load()["attempts"]
    if not attempts:
        print("No attempts yet. Run: kubectl-learn start")
        return None

    print(report.render(attempts, load_tasks()))


def cmd_reset(args):
    tasks = load_tasks()
    # Every task's cleanup commands, each one once (tasks can share them),
    # in task order. Tuples, because lists can't be dict keys.
    commands = list(dict.fromkeys(tuple(cmd) for task in tasks for cmd in task["cleanup"]))
    task = unfinished_task(tasks, progress.load())

    try:
        print("Deleting everything the tasks use:")
        run_cleanup([list(cmd) for cmd in commands])
        # Put the current task's starting point back, so you can retry it.
        if task is not None and task["setup"]:
            print(f"\nRecreating the starting resources for your current task, {task['title']!r}.")
            run_setup(task)
    except kube.KubectlError as err:
        print(f"ERROR: couldn't reset the cluster.\n{err}", file=sys.stderr)
        return 1

    if task is not None:
        # Your progress isn't reset: retrying is part of the same attempt.
        print(f"\nReady to retry {task['title']!r}. The clock, hints and failed checks carry on.")
    else:
        print("\nDone. Run kubectl-learn start for a new task.")


# --- Parser setup -----------------------------------------------------------

def build_parser():
    # prog= sets the name shown in help and error messages.
    # Without it, argparse would show "learn.py".
    parser = argparse.ArgumentParser(
        prog="kubectl-learn",
        description="Learn kubectl by doing real tasks on a real kind cluster.",
    )

    # add_subparsers() creates a slot where exactly one subcommand goes.
    #   dest="command": store the chosen subcommand's name in args.command
    #   metavar="<command>": how the slot is shown in usage/help text
    #   required=True: running with no subcommand is an error, not a silent no-op
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", required=True
    )

    # Each add_parser() call registers one subcommand. It returns a full
    # ArgumentParser of its own, so each subcommand can get its own flags later.
    # help= is the one-line description shown in the main --help listing.
    start_parser = subparsers.add_parser("start", help="pick a task and show it")
    # set_defaults(func=...) attaches the handler to this subcommand.
    # After parsing, args.func will be whichever handler matches what was typed.
    start_parser.set_defaults(func=cmd_start)
    # nargs="?" makes the argument optional: args.task_id is None if left out.
    start_parser.add_argument(
        "task_id", nargs="?", help="start this task instead of letting kubectl-learn choose"
    )

    hint_parser = subparsers.add_parser("hint", help="show a hint for the current task")
    hint_parser.set_defaults(func=cmd_hint)

    check_parser = subparsers.add_parser("check", help="verify your work against the cluster")
    check_parser.set_defaults(func=cmd_check)

    report_parser = subparsers.add_parser("report", help="show progress and weak concepts")
    report_parser.set_defaults(func=cmd_report)

    reset_parser = subparsers.add_parser("reset", help="delete everything the tasks created, to retry")
    reset_parser.set_defaults(func=cmd_reset)

    return parser


def main(argv=None):
    parser = build_parser()
    # argv=None makes parse_args read sys.argv[1:] (the real command line).
    # Passing a list instead (e.g. ["start"]) is handy for testing.
    args = parser.parse_args(argv)
    # Call the handler that set_defaults attached. This is the "dispatch".
    # Handlers return None on success; `or 0` turns that into exit code 0.
    return args.func(args) or 0


# This block runs only when the file is executed directly
# (python learn.py ...), not when another file imports it.
if __name__ == "__main__":
    # sys.exit passes main()'s return value to the shell as the exit code.
    sys.exit(main())

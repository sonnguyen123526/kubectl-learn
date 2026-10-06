"""report: turn your attempt history into a summary of what you've learned.

Everything is calculated from the records in data/progress.json, so the
report can be rebuilt from that file at any time, and anyone can redo
the math by hand.
"""

from statistics import mean


# --- Mastery ----------------------------------------------------------------
# Each attempt gets a score from 0 to 1:
#
#   not passed (yet)  ->  0
#   passed            ->  1.0
#                         - HINT_PENALTY if you looked at the hint
#                         - FAILED_CHECK_PENALTY for each failed check,
#                           counting at most MAX_FAILED_CHECKS
#
# So a pass is worth 0.4 to 1.0, and a pass on your first check without
# the hint is worth 1.0. A concept's mastery is the average score of its
# attempts.

HINT_PENALTY = 0.3
FAILED_CHECK_PENALTY = 0.1
MAX_FAILED_CHECKS = 3

BAR_WIDTH = 10


def attempt_score(attempt):
    if not attempt["passed"]:
        return 0.0
    score = 1.0
    # Each task has a single hint, so reading it again costs nothing extra.
    if attempt["hints"] > 0:
        score -= HINT_PENALTY
    score -= FAILED_CHECK_PENALTY * min(attempt["failed_checks"], MAX_FAILED_CHECKS)
    return score


def mastery(attempts):
    """Return the average score of these attempts, from 0 to 1."""
    return mean(attempt_score(attempt) for attempt in attempts)


# --- Formatting -------------------------------------------------------------

def bar(fraction):
    """0.7 -> '[#######---]'."""
    # + 0.5 rounds to the nearest block. round() would send 0.25 down but
    # 0.35 up, because it rounds halves to the even number.
    filled = int(fraction * BAR_WIDTH + 0.5)
    return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + "]"


def format_duration(seconds):
    """Turn seconds into something readable: 45 -> '45s', 192 -> '3m 12s'."""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _plural(count, word):
    """(1, 'hint') -> '1 hint', (2, 'hint') -> '2 hints'."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _average_time(attempts):
    """Average seconds over the passed attempts, formatted, or '-' if none passed."""
    times = [attempt["seconds"] for attempt in attempts if attempt["passed"]]
    return format_duration(round(mean(times))) if times else "-"


def _why_weak(attempts):
    """Say what pulled a concept's mastery down."""
    reasons = []
    unfinished = sum(not attempt["passed"] for attempt in attempts)
    if unfinished:
        reasons.append(f"{unfinished} not passed yet")
    hinted = sum(attempt["passed"] and attempt["hints"] > 0 for attempt in attempts)
    if hinted:
        reasons.append(f"hint used on {hinted} of {_plural(len(attempts), 'attempt')}")
    failed = sum(attempt["failed_checks"] for attempt in attempts if attempt["passed"])
    if failed:
        reasons.append(_plural(failed, "failed check"))
    return ", ".join(reasons) or "no hints or failed checks"


# --- The report -------------------------------------------------------------

def render(attempts, tasks):
    """Build the report text from a non-empty list of attempts."""
    passed = [attempt for attempt in attempts if attempt["passed"]]
    first_try = sum(attempt["failed_checks"] == 0 for attempt in passed)
    # started_at looks like 2026-10-05T20:41:07-04:00; the first 10
    # characters are the date.
    first_day = min(attempt["started_at"][:10] for attempt in attempts)
    last_day = max(attempt["started_at"][:10] for attempt in attempts)

    # Concepts in course order (the order of the task files), then any
    # that only appear in your history because their task was removed.
    concepts = list(dict.fromkeys(
        [task["concept"] for task in tasks] + [attempt["concept"] for attempt in attempts]
    ))
    by_concept = {c: [a for a in attempts if a["concept"] == c] for c in concepts}
    width = max(len(concept) for concept in concepts + ["Concept"])

    lines = [
        f"Practice:   {first_day} to {last_day}",
        f"Attempts:   {len(attempts)}  ({len(passed)} passed, {len(attempts) - len(passed)} not passed yet)",
        f"Pass rate:  {len(passed) / len(attempts):.0%}",
    ]
    if passed:
        lines.append(f"First try:  {first_try} of {len(passed)} passes had no failed checks")

    lines += ["", f"  {'Concept':<{width}}  {'Mastery':<17}  {'Attempts':<10}  {'Avg time':>8}  Hints"]
    for concept in concepts:
        group = by_concept[concept]
        if not group:
            lines.append(f"  {concept:<{width}}  not started")
            continue
        score = mastery(group)
        hints = sum(attempt["hints"] for attempt in group)
        lines.append(
            f"  {concept:<{width}}  {bar(score)} {score:>4.0%}  "
            f"{_plural(len(group), 'attempt'):<10}  {_average_time(group):>8}  {hints}"
        )

    hinted = sum(attempt["hints"] > 0 for attempt in attempts)
    lines += [
        "",
        f"Average time per passed task: {_average_time(attempts)}",
        f"Hints used: {sum(attempt['hints'] for attempt in attempts)}"
        f"  (on {hinted} of {_plural(len(attempts), 'attempt')})",
    ]

    # sorted() keeps ties in course order, so equal scores list the
    # earlier concept first.
    started = [concept for concept in concepts if by_concept[concept]]
    weakest = sorted(started, key=lambda concept: mastery(by_concept[concept]))[:2]
    lines += ["", "Weakest concepts"]
    for rank, concept in enumerate(weakest, start=1):
        group = by_concept[concept]
        lines.append(f"  {rank}. {concept:<{width}}  {mastery(group):>4.0%}  {_why_weak(group)}")

    lines += [
        "",
        "Mastery = average attempt score. A pass scores 100, minus "
        f"{HINT_PENALTY * 100:.0f} for using the hint",
        f"and {FAILED_CHECK_PENALTY * 100:.0f} for each failed check (up to {MAX_FAILED_CHECKS}). "
        "An attempt not passed yet scores 0.",
    ]
    return "\n".join(lines)

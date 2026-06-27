"""Domain analytics for PetCare.

Pure functions over the model/store: age from birthdate, weight-trend
analysis, next-due reminder calculation, medication adherence and per-pet
activity summaries. Nothing here mutates the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence

from petcare.model import ActivityKind, LogEntry, Pet, Reminder
from petcare.store import Store


# --------------------------------------------------------------------- age
def age_in_years(birthdate: date, today: Optional[date] = None) -> int:
    """Whole years between ``birthdate`` and ``today`` (default: real today).

    Counts a birthday only once it has actually passed, so a pet born on
    2022-03-01 is 0 on 2023-02-28 and 1 on 2023-03-01.
    """
    today = today or date.today()
    if birthdate > today:
        raise ValueError("birthdate is in the future")
    years = today.year - birthdate.year
    # Subtract one if this year's birthday hasn't happened yet.
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        years -= 1
    return years


def age_in_months(birthdate: date, today: Optional[date] = None) -> int:
    """Whole months between ``birthdate`` and ``today``."""
    today = today or date.today()
    if birthdate > today:
        raise ValueError("birthdate is in the future")
    months = (today.year - birthdate.year) * 12 + (today.month - birthdate.month)
    if today.day < birthdate.day:
        months -= 1
    return months


def describe_age(birthdate: date, today: Optional[date] = None) -> str:
    """Human-friendly age string, e.g. ``"3 yr"`` or ``"7 mo"``."""
    years = age_in_years(birthdate, today)
    if years >= 1:
        return f"{years} yr"
    return f"{age_in_months(birthdate, today)} mo"


# --------------------------------------------------------------------- weight
@dataclass
class WeightTrend:
    """Result of analysing a series of weight measurements."""

    direction: str  # "gaining", "losing" or "stable"
    first_kg: float
    last_kg: float
    delta_kg: float       # last - first
    pct_change: float     # delta / first * 100
    samples: int


def weight_trend(
    series: Sequence[LogEntry] | Sequence[float],
    stable_threshold_pct: float = 2.0,
) -> Optional[WeightTrend]:
    """Classify a weight series as gaining / losing / stable.

    Accepts either a sequence of WEIGHT ``LogEntry`` (uses ``.value``,
    assumed already time-ordered) or a raw sequence of floats. A change
    within +/- ``stable_threshold_pct`` of the first reading is "stable".
    Returns ``None`` for fewer than two samples.
    """
    weights = _weights_from(series)
    if len(weights) < 2:
        return None
    first, last = weights[0], weights[-1]
    delta = last - first
    pct = (delta / first * 100.0) if first else 0.0
    if abs(pct) <= stable_threshold_pct:
        direction = "stable"
    elif delta > 0:
        direction = "gaining"
    else:
        direction = "losing"
    return WeightTrend(
        direction=direction,
        first_kg=first,
        last_kg=last,
        delta_kg=round(delta, 3),
        pct_change=round(pct, 2),
        samples=len(weights),
    )


def _weights_from(series: Sequence[LogEntry] | Sequence[float]) -> List[float]:
    out: List[float] = []
    for item in series:
        if isinstance(item, LogEntry):
            if item.value is not None:
                out.append(float(item.value))
        else:
            out.append(float(item))
    return out


# --------------------------------------------------------------------- reminders
@dataclass
class DueReminder:
    reminder: Reminder
    next_due: datetime
    overdue: bool
    overdue_by_hours: float


def next_due(
    reminder: Reminder,
    last_done: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> datetime:
    """Compute the next time ``reminder`` should fire.

    The schedule is anchored at ``reminder.start_at`` and repeats every
    ``interval_hours``. If ``last_done`` is given, the next due time is
    simply one interval after it. Otherwise we advance from ``start_at`` in
    whole intervals until we reach the first slot at or after ``now``.
    """
    now = now or datetime.now()
    interval = timedelta(hours=reminder.interval_hours)
    if last_done is not None:
        return last_done + interval
    due = reminder.start_at
    if due >= now:
        return due
    # Jump ahead in whole intervals to the first slot >= now.
    elapsed = now - reminder.start_at
    steps = int(elapsed // interval) + 1
    return reminder.start_at + steps * interval


def whats_due(
    store: Store,
    household_id: int,
    now: Optional[datetime] = None,
    horizon_hours: float = 24.0,
) -> List[DueReminder]:
    """Return reminders due now or within ``horizon_hours`` for a household.

    For each active reminder, the most recent matching log entry is treated
    as "last done"; the next-due time is derived from it (or from the
    schedule anchor if never done). Results are sorted by next-due time;
    overdue items naturally sort first.
    """
    now = now or datetime.now()
    horizon = now + timedelta(hours=horizon_hours)
    due: List[DueReminder] = []
    for reminder in store.list_reminders_for_household(household_id, active_only=True):
        last = _last_done_for(store, reminder, now)
        nxt = next_due(reminder, last_done=last, now=now)
        if nxt <= horizon:
            overdue = nxt < now
            by = (now - nxt).total_seconds() / 3600.0 if overdue else 0.0
            due.append(
                DueReminder(
                    reminder=reminder,
                    next_due=nxt,
                    overdue=overdue,
                    overdue_by_hours=round(by, 2),
                )
            )
    due.sort(key=lambda d: d.next_due)
    return due


_REMINDER_TO_ACTIVITY = {
    "medication": ActivityKind.MEDICATION,
    "feeding": ActivityKind.FEEDING,
    "walk": ActivityKind.WALK,
    "vaccination": ActivityKind.VET_VISIT,
    "vet_checkup": ActivityKind.VET_VISIT,
}


def _last_done_for(
    store: Store, reminder: Reminder, now: datetime
) -> Optional[datetime]:
    activity = _REMINDER_TO_ACTIVITY.get(reminder.kind.value)
    if activity is None:
        return None
    logs = store.list_logs(reminder.pet_id, kind=activity, until=now)
    return logs[-1].at if logs else None


# --------------------------------------------------------------------- adherence
@dataclass
class Adherence:
    expected: int
    actual: int
    rate: float  # actual / expected, capped at 1.0
    window_start: datetime
    window_end: datetime


def medication_adherence(
    reminder: Reminder,
    logs: Sequence[LogEntry],
    window_start: datetime,
    window_end: datetime,
) -> Adherence:
    """How well were scheduled medication doses actually administered?

    ``expected`` is the number of scheduled slots (every ``interval_hours``,
    anchored at ``reminder.start_at``) that fall inside the window.
    ``actual`` is the number of medication log entries in the same window,
    capped at ``expected`` (you can't be more than 100% adherent).
    """
    if window_end < window_start:
        raise ValueError("window_end precedes window_start")
    interval = timedelta(hours=reminder.interval_hours)

    # Count scheduled slots within [window_start, window_end].
    expected = 0
    slot = reminder.start_at
    if slot < window_start:
        elapsed = window_start - reminder.start_at
        steps = int(elapsed // interval)
        slot = reminder.start_at + steps * interval
        if slot < window_start:
            slot += interval
    while slot <= window_end:
        expected += 1
        slot += interval

    actual_logs = [
        e
        for e in logs
        if e.kind == ActivityKind.MEDICATION
        and window_start <= e.at <= window_end
    ]
    actual = min(len(actual_logs), expected)
    rate = (actual / expected) if expected else 1.0
    return Adherence(
        expected=expected,
        actual=actual,
        rate=round(rate, 4),
        window_start=window_start,
        window_end=window_end,
    )


# --------------------------------------------------------------------- summary
@dataclass
class ActivitySummary:
    pet: Pet
    counts: Dict[str, int]
    total: int
    last_activity_at: Optional[datetime]
    latest_weight_kg: Optional[float]


def activity_summary(
    store: Store,
    pet: Pet,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> ActivitySummary:
    """Per-pet roll-up: counts by activity kind, totals, latest weight."""
    assert pet.id is not None
    logs = store.list_logs(pet.id, since=since, until=until)
    counts: Dict[str, int] = {k.value: 0 for k in ActivityKind}
    for entry in logs:
        counts[entry.kind.value] += 1
    weights = [e for e in logs if e.kind == ActivityKind.WEIGHT and e.value is not None]
    return ActivitySummary(
        pet=pet,
        counts=counts,
        total=len(logs),
        last_activity_at=logs[-1].at if logs else None,
        latest_weight_kg=weights[-1].value if weights else pet.weight_kg,
    )

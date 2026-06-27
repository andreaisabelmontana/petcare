"""Domain analytics tests: age, weight trend, due reminders, adherence."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from petcare import analytics
from petcare.model import (
    ActivityKind,
    Household,
    LogEntry,
    Pet,
    Reminder,
    ReminderKind,
)
from petcare.store import Store


# --------------------------------------------------------------------- age
def test_age_in_years_before_and_after_birthday():
    bd = date(2022, 3, 1)
    # day before the 1st birthday
    assert analytics.age_in_years(bd, date(2023, 2, 28)) == 0
    # on the birthday
    assert analytics.age_in_years(bd, date(2023, 3, 1)) == 1
    # day after
    assert analytics.age_in_years(bd, date(2023, 3, 2)) == 1
    # several years later, before birthday
    assert analytics.age_in_years(bd, date(2026, 2, 1)) == 3
    # several years later, after birthday
    assert analytics.age_in_years(bd, date(2026, 6, 27)) == 4


def test_age_handles_leap_day_birthdate():
    bd = date(2020, 2, 29)
    # 2021 is not a leap year; the 1-year mark counts on Mar 1
    assert analytics.age_in_years(bd, date(2021, 2, 28)) == 0
    assert analytics.age_in_years(bd, date(2021, 3, 1)) == 1


def test_describe_age_uses_months_under_a_year():
    bd = date(2026, 1, 1)
    assert analytics.describe_age(bd, date(2026, 8, 1)) == "7 mo"
    assert analytics.describe_age(bd, date(2027, 6, 1)) == "1 yr"


def test_age_future_birthdate_raises():
    with pytest.raises(ValueError):
        analytics.age_in_years(date(2030, 1, 1), date(2026, 1, 1))


# --------------------------------------------------------------------- weight
def test_weight_trend_detects_gain():
    t = analytics.weight_trend([4.0, 4.2, 4.6, 5.0])
    assert t is not None
    assert t.direction == "gaining"
    assert t.delta_kg == pytest.approx(1.0)
    assert t.pct_change == pytest.approx(25.0)
    assert t.samples == 4


def test_weight_trend_detects_loss():
    t = analytics.weight_trend([30.0, 29.0, 27.5, 26.0])
    assert t.direction == "losing"
    assert t.delta_kg == pytest.approx(-4.0)
    assert t.pct_change < 0


def test_weight_trend_stable_within_threshold():
    # +1% over the series -> within the default 2% band
    t = analytics.weight_trend([10.0, 10.05, 9.98, 10.1])
    assert t.direction == "stable"


def test_weight_trend_reads_log_entry_values():
    entries = [
        LogEntry(1, ActivityKind.WEIGHT, datetime(2026, 1, 1), value=4.0),
        LogEntry(1, ActivityKind.WEIGHT, datetime(2026, 1, 8), value=4.4),
    ]
    t = analytics.weight_trend(entries)
    assert t.direction == "gaining"
    assert t.first_kg == 4.0 and t.last_kg == 4.4


def test_weight_trend_needs_two_samples():
    assert analytics.weight_trend([4.2]) is None
    assert analytics.weight_trend([]) is None


# --------------------------------------------------------------------- reminders
def _seed_household_with_pet() -> tuple[Store, int, int]:
    store = Store(":memory:")
    hh = store.add_household(Household(name="Olsen", join_code="X"))
    pet = store.add_pet(Pet(household_id=hh.id, name="Max", species="dog"))
    return store, hh.id, pet.id


def test_next_due_from_schedule_anchor():
    r = Reminder(
        pet_id=1,
        kind=ReminderKind.MEDICATION,
        label="meds 12h",
        interval_hours=12,
        start_at=datetime(2026, 1, 1, 8, 0),
    )
    # at 09:00 with no doses given, next slot is 20:00 the same day
    nxt = analytics.next_due(r, last_done=None, now=datetime(2026, 1, 1, 9, 0))
    assert nxt == datetime(2026, 1, 1, 20, 0)
    # after a dose at 08:00, next is 12h later
    nxt2 = analytics.next_due(r, last_done=datetime(2026, 1, 1, 8, 0))
    assert nxt2 == datetime(2026, 1, 1, 20, 0)


def test_whats_due_returns_overdue_and_upcoming_in_order():
    store, hid, pid = _seed_household_with_pet()
    # meds every 12h since yesterday 08:00, last dose logged yesterday 08:00
    store.add_reminder(
        Reminder(pid, ReminderKind.MEDICATION, "meds 12h", 12, datetime(2026, 1, 1, 8, 0))
    )
    store.add_log(LogEntry(pid, ActivityKind.MEDICATION, datetime(2026, 1, 1, 8, 0)))
    # annual vaccination starting today 18:00 -> upcoming
    store.add_reminder(
        Reminder(pid, ReminderKind.VACCINATION, "rabies", 24 * 365, datetime(2026, 1, 2, 18, 0))
    )
    # an inactive feeding reminder should be ignored
    store.add_reminder(
        Reminder(pid, ReminderKind.FEEDING, "breakfast", 24, datetime(2026, 1, 1, 7, 0), active=False)
    )

    now = datetime(2026, 1, 2, 12, 0)
    due = analytics.whats_due(store, hid, now=now, horizon_hours=24)
    labels = [d.reminder.label for d in due]
    # meds (next due 2026-01-01 20:00, overdue) then rabies (today 18:00)
    assert labels == ["meds 12h", "rabies"]
    assert due[0].overdue is True
    assert due[0].overdue_by_hours == pytest.approx(16.0)
    assert due[1].overdue is False


def test_whats_due_respects_horizon():
    store, hid, pid = _seed_household_with_pet()
    store.add_reminder(
        Reminder(pid, ReminderKind.VET_CHECKUP, "checkup", 24 * 30, datetime(2026, 2, 1, 9, 0))
    )
    now = datetime(2026, 1, 2, 12, 0)
    # far in the future -> not within a 24h horizon
    assert analytics.whats_due(store, hid, now=now, horizon_hours=24) == []
    # but visible within a 60-day horizon
    assert len(analytics.whats_due(store, hid, now=now, horizon_hours=24 * 60)) == 1


# --------------------------------------------------------------------- adherence
def test_medication_adherence_full_and_partial():
    r = Reminder(
        pet_id=1,
        kind=ReminderKind.MEDICATION,
        label="meds 12h",
        interval_hours=12,
        start_at=datetime(2026, 1, 1, 8, 0),
    )
    start = datetime(2026, 1, 1, 8, 0)
    end = datetime(2026, 1, 3, 8, 0)  # 48h -> slots at 8,20,8,20,8 = 5 expected

    # all 5 doses given -> 100%
    full = [
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 1, 8, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 1, 20, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 2, 8, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 2, 20, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 3, 8, 0)),
    ]
    a = analytics.medication_adherence(r, full, start, end)
    assert a.expected == 5
    assert a.actual == 5
    assert a.rate == pytest.approx(1.0)

    # 3 of 5 given (and a non-med entry ignored) -> 60%
    partial = full[:3] + [LogEntry(1, ActivityKind.WALK, datetime(2026, 1, 2, 9, 0))]
    b = analytics.medication_adherence(r, partial, start, end)
    assert b.expected == 5
    assert b.actual == 3
    assert b.rate == pytest.approx(0.6)


def test_adherence_caps_at_one():
    r = Reminder(1, ReminderKind.MEDICATION, "meds 24h", 24, datetime(2026, 1, 1, 8, 0))
    start = datetime(2026, 1, 1, 8, 0)
    end = datetime(2026, 1, 2, 8, 0)  # slots at day1 08:00 and day2 08:00 -> 2 expected
    # four doses logged (over-administered) still caps at expected
    logs = [
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 1, 8, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 1, 14, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 1, 20, 0)),
        LogEntry(1, ActivityKind.MEDICATION, datetime(2026, 1, 2, 8, 0)),
    ]
    a = analytics.medication_adherence(r, logs, start, end)
    assert a.expected == 2
    assert a.actual == 2
    assert a.rate == pytest.approx(1.0)


# --------------------------------------------------------------------- summary
def test_activity_summary_counts_and_latest_weight():
    store, hid, pid = _seed_household_with_pet()
    store.add_log(LogEntry(pid, ActivityKind.FEEDING, datetime(2026, 1, 1, 8, 0)))
    store.add_log(LogEntry(pid, ActivityKind.FEEDING, datetime(2026, 1, 1, 18, 0)))
    store.add_log(LogEntry(pid, ActivityKind.WEIGHT, datetime(2026, 1, 2, 8, 0), value=30.5))
    pet = store.get_pet(pid)
    s = analytics.activity_summary(store, pet)
    assert s.total == 3
    assert s.counts["feeding"] == 2
    assert s.counts["weight"] == 1
    assert s.latest_weight_kg == 30.5
    assert s.last_activity_at == datetime(2026, 1, 2, 8, 0)

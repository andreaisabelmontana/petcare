"""Build the committed sample household at data/sample.db.

Run from the repo root:  python data/seed_sample.py

This is the same household the CLI examples in the README operate on. It is
deterministic, so re-running it reproduces an identical database. The clock
the examples assume is 2026-06-22T19:00.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

# Allow running as `python data/seed_sample.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from petcare.model import (
    ActivityKind,
    Household,
    LogEntry,
    Member,
    Pet,
    Reminder,
    ReminderKind,
)
from petcare.store import Store

DB_PATH = os.path.join(os.path.dirname(__file__), "sample.db")
NOW = datetime(2026, 6, 22, 19, 0)
WEEK_START = NOW - timedelta(days=7)


def build() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    store = Store(DB_PATH)

    hh = store.add_household(Household(name="The Olsen household", join_code="PET-4Q7K"))
    store.add_member(Member(hh.id, "Andrea", role="owner"))
    store.add_member(Member(hh.id, "Sam", role="member"))

    luna = store.add_pet(
        Pet(hh.id, "Luna", "cat", "domestic shorthair", date(2022, 3, 1), 4.0)
    )
    max_ = store.add_pet(
        Pet(hh.id, "Max", "dog", "border collie", date(2019, 9, 15), 18.5)
    )

    store.add_reminder(
        Reminder(max_.id, ReminderKind.MEDICATION, "Apoquel (every 12h)",
                 12, WEEK_START.replace(hour=8, minute=0))
    )
    store.add_reminder(
        Reminder(luna.id, ReminderKind.VACCINATION, "Annual vaccination (FVRCP)",
                 24 * 365, datetime(2025, 6, 20, 10, 0))
    )

    luna_weights = [4.0, 4.1, 4.25, 4.4]
    for day in range(7):
        d = WEEK_START + timedelta(days=day)
        store.add_log(LogEntry(luna.id, ActivityKind.FEEDING, d.replace(hour=8), note="full bowl"))
        store.add_log(LogEntry(luna.id, ActivityKind.FEEDING, d.replace(hour=19), note="full bowl"))
        if day % 2 == 0:
            store.add_log(LogEntry(luna.id, ActivityKind.WEIGHT, d.replace(hour=9),
                                   value=luna_weights[day // 2]))

    missed_evenings = {2, 5}
    for day in range(7):
        d = WEEK_START + timedelta(days=day)
        store.add_log(LogEntry(max_.id, ActivityKind.FEEDING, d.replace(hour=8)))
        store.add_log(LogEntry(max_.id, ActivityKind.FEEDING, d.replace(hour=18)))
        store.add_log(LogEntry(max_.id, ActivityKind.WALK, d.replace(hour=17), note="park"))
        store.add_log(LogEntry(max_.id, ActivityKind.MEDICATION, d.replace(hour=8), note="Apoquel"))
        if day not in missed_evenings:
            store.add_log(LogEntry(max_.id, ActivityKind.MEDICATION, d.replace(hour=20), note="Apoquel"))

    store.close()
    print(f"wrote {DB_PATH}")


if __name__ == "__main__":
    build()

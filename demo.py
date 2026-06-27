"""End-to-end demo: seed a household, log a week of activity, run analytics.

Run with: python demo.py

Uses a fixed "now" so the printed output is deterministic. Writes nothing to
disk — everything runs in an in-memory database.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from petcare import analytics
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

# Pretend "now" is Mon 2026-06-22 19:00 — a week of activity precedes it.
NOW = datetime(2026, 6, 22, 19, 0)
WEEK_START = NOW - timedelta(days=7)


def seed() -> tuple[Store, int]:
    store = Store(":memory:")
    hh = store.add_household(Household(name="The Olsen household", join_code="PET-4Q7K"))
    store.add_member(Member(household_id=hh.id, name="Andrea", role="owner"))
    store.add_member(Member(household_id=hh.id, name="Sam", role="member"))

    luna = store.add_pet(
        Pet(hh.id, "Luna", "cat", breed="domestic shorthair",
            birthdate=date(2022, 3, 1), weight_kg=4.0)
    )
    max_ = store.add_pet(
        Pet(hh.id, "Max", "dog", breed="border collie",
            birthdate=date(2019, 9, 15), weight_kg=18.5)
    )

    # Max is on twice-daily medication; Luna is due her annual vaccination.
    store.add_reminder(
        Reminder(max_.id, ReminderKind.MEDICATION, "Apoquel (every 12h)",
                 interval_hours=12, start_at=WEEK_START.replace(hour=8, minute=0))
    )
    store.add_reminder(
        Reminder(luna.id, ReminderKind.VACCINATION, "Annual vaccination (FVRCP)",
                 interval_hours=24 * 365, start_at=datetime(2025, 6, 20, 10, 0))
    )

    # A week of activity.
    # Luna: fed twice a day, weighed every other day (slowly gaining).
    luna_weights = [4.0, 4.1, 4.25, 4.4]
    for day in range(7):
        d = WEEK_START + timedelta(days=day)
        store.add_log(LogEntry(luna.id, ActivityKind.FEEDING, d.replace(hour=8), note="full bowl"))
        store.add_log(LogEntry(luna.id, ActivityKind.FEEDING, d.replace(hour=19), note="full bowl"))
        if day % 2 == 0:
            store.add_log(
                LogEntry(luna.id, ActivityKind.WEIGHT, d.replace(hour=9),
                         value=luna_weights[day // 2])
            )

    # Max: fed twice a day, walked once a day, meds twice a day but he MISSED
    # two evening doses (days 2 and 5) -> adherence below 100%.
    missed_evenings = {2, 5}
    for day in range(7):
        d = WEEK_START + timedelta(days=day)
        store.add_log(LogEntry(max_.id, ActivityKind.FEEDING, d.replace(hour=8)))
        store.add_log(LogEntry(max_.id, ActivityKind.FEEDING, d.replace(hour=18)))
        store.add_log(LogEntry(max_.id, ActivityKind.WALK, d.replace(hour=17), note="park"))
        store.add_log(LogEntry(max_.id, ActivityKind.MEDICATION, d.replace(hour=8), note="Apoquel"))
        if day not in missed_evenings:
            store.add_log(LogEntry(max_.id, ActivityKind.MEDICATION, d.replace(hour=20), note="Apoquel"))

    return store, hh.id


def main() -> None:
    store, hid = seed()
    print(f"PetCare demo — household #{hid} as of {NOW.isoformat(timespec='minutes')}")
    print("=" * 64)

    print("\nMembers:")
    for m in store.list_members(hid):
        print(f"  - {m.name} ({m.role})")

    print("\nReminders due within 7 days:")
    due = analytics.whats_due(store, hid, now=NOW, horizon_hours=24 * 7)
    if not due:
        print("  (nothing due)")
    for d in due:
        pet = store.get_pet(d.reminder.pet_id)
        when = d.next_due.isoformat(timespec="minutes")
        if d.overdue:
            status = f"OVERDUE by {d.overdue_by_hours:g}h"
        else:
            status = f"in {(d.next_due - NOW).total_seconds() / 3600:.1f}h"
        print(f"  [{status:>16}] {pet.name}: {d.reminder.label} -> {when}")

    print("\nPer-pet summary:")
    for pet in store.list_pets(hid):
        print(f"\n  {pet.name} — {pet.species}, {pet.breed} "
              f"({analytics.describe_age(pet.birthdate, NOW.date())})")
        summ = analytics.activity_summary(store, pet, until=NOW)
        active = ", ".join(f"{k}={v}" for k, v in summ.counts.items() if v)
        print(f"    activity (7d): {summ.total} entries — {active}")

        weights = store.list_logs(pet.id, kind=ActivityKind.WEIGHT, until=NOW)
        trend = analytics.weight_trend(weights)
        if trend:
            print(f"    weight: {trend.first_kg:g} -> {trend.last_kg:g} kg "
                  f"({trend.direction}, {trend.delta_kg:+g} kg / {trend.pct_change:+g}%)")

        for r in store.list_reminders(pet.id):
            if r.kind != ReminderKind.MEDICATION:
                continue
            adh = analytics.medication_adherence(r, store.list_logs(pet.id), WEEK_START, NOW)
            print(f"    adherence ({r.label}): {adh.actual}/{adh.expected} doses "
                  f"= {adh.rate * 100:.0f}%")

    store.close()


if __name__ == "__main__":
    main()

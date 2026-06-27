"""CRUD and log-persistence tests for the SQLite store."""

from __future__ import annotations

from datetime import date, datetime

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


def make_store() -> tuple[Store, int]:
    store = Store(":memory:")
    hh = store.add_household(Household(name="Olsen", join_code="PET-4Q7K"))
    assert hh.id is not None
    return store, hh.id


def test_household_and_member_crud():
    store, hid = make_store()
    assert store.get_household(hid).name == "Olsen"
    store.add_member(Member(household_id=hid, name="Andrea", role="owner"))
    store.add_member(Member(household_id=hid, name="Sam"))
    members = store.list_members(hid)
    assert [m.name for m in members] == ["Andrea", "Sam"]
    assert members[0].role == "owner"


def test_pet_crud_roundtrip():
    store, hid = make_store()
    pet = store.add_pet(
        Pet(
            household_id=hid,
            name="Luna",
            species="cat",
            breed="tabby",
            birthdate=date(2022, 3, 1),
            weight_kg=4.2,
        )
    )
    assert pet.id is not None

    fetched = store.get_pet(pet.id)
    assert fetched is not None
    assert fetched.name == "Luna"
    assert fetched.birthdate == date(2022, 3, 1)
    assert fetched.weight_kg == 4.2

    # find by name is case-insensitive
    assert store.find_pet(hid, "luna").id == pet.id

    # update
    fetched.weight_kg = 4.5
    fetched.breed = "domestic shorthair"
    store.update_pet(fetched)
    again = store.get_pet(pet.id)
    assert again.weight_kg == 4.5
    assert again.breed == "domestic shorthair"

    # list
    store.add_pet(Pet(household_id=hid, name="Max", species="dog"))
    assert [p.name for p in store.list_pets(hid)] == ["Luna", "Max"]

    # delete
    assert store.delete_pet(pet.id) is True
    assert store.get_pet(pet.id) is None
    assert [p.name for p in store.list_pets(hid)] == ["Max"]


def test_log_persistence_and_filtering():
    store, hid = make_store()
    pet = store.add_pet(Pet(household_id=hid, name="Luna", species="cat"))
    assert pet.id is not None

    store.add_log(LogEntry(pet.id, ActivityKind.FEEDING, datetime(2026, 1, 1, 8, 0), note="full bowl"))
    store.add_log(LogEntry(pet.id, ActivityKind.WALK, datetime(2026, 1, 1, 9, 0)))
    store.add_log(LogEntry(pet.id, ActivityKind.WEIGHT, datetime(2026, 1, 2, 8, 0), value=4.3))

    all_logs = store.list_logs(pet.id)
    assert len(all_logs) == 3
    # ordered by time ascending
    assert [e.kind for e in all_logs] == [
        ActivityKind.FEEDING,
        ActivityKind.WALK,
        ActivityKind.WEIGHT,
    ]
    # values and notes survive the round-trip
    assert all_logs[0].note == "full bowl"
    assert all_logs[2].value == 4.3

    # filter by kind
    feedings = store.list_logs(pet.id, kind=ActivityKind.FEEDING)
    assert len(feedings) == 1

    # filter by time window
    day2 = store.list_logs(pet.id, since=datetime(2026, 1, 2, 0, 0))
    assert len(day2) == 1
    assert day2[0].kind == ActivityKind.WEIGHT


def test_reminder_persistence():
    store, hid = make_store()
    pet = store.add_pet(Pet(household_id=hid, name="Max", species="dog"))
    assert pet.id is not None
    store.add_reminder(
        Reminder(
            pet_id=pet.id,
            kind=ReminderKind.MEDICATION,
            label="Apoquel 12h",
            interval_hours=12,
            start_at=datetime(2026, 1, 1, 8, 0),
        )
    )
    inactive = store.add_reminder(
        Reminder(
            pet_id=pet.id,
            kind=ReminderKind.VACCINATION,
            label="Rabies (annual)",
            interval_hours=24 * 365,
            start_at=datetime(2025, 6, 1, 0, 0),
            active=False,
        )
    )
    assert len(store.list_reminders(pet.id, active_only=True)) == 1
    assert len(store.list_reminders(pet.id, active_only=False)) == 2

    store.set_reminder_active(inactive.id, True)
    assert len(store.list_reminders(pet.id, active_only=True)) == 2

    # household-wide aggregation
    assert len(store.list_reminders_for_household(hid)) == 2

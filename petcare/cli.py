"""Command-line interface for PetCare.

Subcommands:
    add-pet   register a pet in a household
    log       record an activity (feeding/walk/medication/weight/vet_visit)
    due       show reminders due now or within a horizon
    stats     per-pet summary: age, weight trend, activity counts, adherence

The household and database are selected with ``--db`` and ``--household``.
A committed sample household lives in ``data/sample.db`` (household id 1).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from typing import List, Optional

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

DEFAULT_DB = os.path.join("data", "sample.db")


def _now(args: argparse.Namespace) -> datetime:
    if getattr(args, "now", None):
        return datetime.fromisoformat(args.now)
    return datetime.now()


def _resolve_pet(store: Store, household_id: int, name: str) -> Pet:
    pet = store.find_pet(household_id, name)
    if pet is None:
        print(f"error: no pet named {name!r} in household {household_id}", file=sys.stderr)
        raise SystemExit(2)
    return pet


# --------------------------------------------------------------------- add-pet
def cmd_add_pet(store: Store, args: argparse.Namespace) -> int:
    if store.get_household(args.household) is None:
        store.add_household(Household(name="My household", join_code="LOCAL"))
    birthdate = date.fromisoformat(args.birthdate) if args.birthdate else None
    pet = store.add_pet(
        Pet(
            household_id=args.household,
            name=args.name,
            species=args.species,
            breed=args.breed,
            birthdate=birthdate,
            weight_kg=args.weight,
        )
    )
    extra = ""
    if birthdate:
        extra = f", {analytics.describe_age(birthdate)}"
    print(f"added pet #{pet.id}: {pet.name} ({pet.species}{extra})")
    return 0


# --------------------------------------------------------------------- log
def cmd_log(store: Store, args: argparse.Namespace) -> int:
    pet = _resolve_pet(store, args.household, args.pet)
    assert pet.id is not None
    at = datetime.fromisoformat(args.at) if args.at else _now(args)
    kind = ActivityKind(args.kind)
    entry = store.add_log(
        LogEntry(
            pet_id=pet.id,
            kind=kind,
            at=at,
            note=args.note,
            value=args.value,
        )
    )
    detail = f" = {args.value}kg" if kind == ActivityKind.WEIGHT and args.value else ""
    if kind == ActivityKind.WEIGHT and args.value:
        pet.weight_kg = args.value
        store.update_pet(pet)
    print(f"logged #{entry.id}: {pet.name} {kind.value}{detail} at {at.isoformat(timespec='minutes')}")
    return 0


# --------------------------------------------------------------------- due
def cmd_due(store: Store, args: argparse.Namespace) -> int:
    now = _now(args)
    due = analytics.whats_due(store, args.household, now=now, horizon_hours=args.horizon)
    if not due:
        print(f"nothing due within {args.horizon:g}h (as of {now.isoformat(timespec='minutes')})")
        return 0
    print(f"due within {args.horizon:g}h (as of {now.isoformat(timespec='minutes')}):")
    for d in due:
        pet = store.get_pet(d.reminder.pet_id)
        name = pet.name if pet else f"pet#{d.reminder.pet_id}"
        if d.overdue:
            status = f"OVERDUE by {d.overdue_by_hours:g}h"
        else:
            in_h = (d.next_due - now).total_seconds() / 3600.0
            status = f"in {in_h:.1f}h"
        when = d.next_due.isoformat(timespec="minutes")
        print(f"  [{status}] {name}: {d.reminder.label} -> {when}")
    return 0


# --------------------------------------------------------------------- stats
def cmd_stats(store: Store, args: argparse.Namespace) -> int:
    now = _now(args)
    pets: List[Pet]
    if args.pet:
        pets = [_resolve_pet(store, args.household, args.pet)]
    else:
        pets = store.list_pets(args.household)
    if not pets:
        print(f"no pets in household {args.household}")
        return 0
    for i, pet in enumerate(pets):
        assert pet.id is not None
        if i:
            print()
        line = f"{pet.name} — {pet.species}"
        if pet.breed:
            line += f", {pet.breed}"
        if pet.birthdate:
            line += f" ({analytics.describe_age(pet.birthdate, now.date())})"
        print(line)

        summ = analytics.activity_summary(store, pet, until=now)
        active = {k: v for k, v in summ.counts.items() if v}
        breakdown = ", ".join(f"{k}={v}" for k, v in active.items()) or "none"
        print(f"  activity: {summ.total} entries ({breakdown})")

        weights = store.list_logs(pet.id, kind=ActivityKind.WEIGHT, until=now)
        trend = analytics.weight_trend(weights)
        if trend:
            print(
                f"  weight: {trend.first_kg:g} -> {trend.last_kg:g} kg "
                f"({trend.direction}, {trend.delta_kg:+g} kg / {trend.pct_change:+g}%)"
            )
        elif summ.latest_weight_kg is not None:
            print(f"  weight: {summ.latest_weight_kg:g} kg (need 2+ readings for a trend)")

        for reminder in store.list_reminders(pet.id):
            if reminder.kind != ReminderKind.MEDICATION:
                continue
            window_start = now - timedelta(hours=args.window)
            adh = analytics.medication_adherence(
                reminder, store.list_logs(pet.id), window_start, now
            )
            print(
                f"  adherence ({reminder.label}, last {args.window:g}h): "
                f"{adh.actual}/{adh.expected} = {adh.rate * 100:.0f}%"
            )
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="petcare", description="Household pet management.")
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("--household", type=int, default=1, help="household id (default: 1)")
    p.add_argument("--now", help="override the clock (ISO-8601), for testing/demos")
    sub = p.add_subparsers(dest="command", required=True)

    ap = sub.add_parser("add-pet", help="register a pet")
    ap.add_argument("name")
    ap.add_argument("species")
    ap.add_argument("--breed")
    ap.add_argument("--birthdate", help="YYYY-MM-DD")
    ap.add_argument("--weight", type=float, help="weight in kg")
    ap.set_defaults(func=cmd_add_pet)

    lp = sub.add_parser("log", help="record an activity")
    lp.add_argument("pet", help="pet name")
    lp.add_argument("kind", choices=[k.value for k in ActivityKind])
    lp.add_argument("--note")
    lp.add_argument("--value", type=float, help="weight in kg (for the weight kind)")
    lp.add_argument("--at", help="timestamp (ISO-8601); default: now")
    lp.set_defaults(func=cmd_log)

    dp = sub.add_parser("due", help="show reminders due soon")
    dp.add_argument("--horizon", type=float, default=24.0, help="lookahead hours (default 24)")
    dp.set_defaults(func=cmd_due)

    sp = sub.add_parser("stats", help="per-pet summary")
    sp.add_argument("--pet", help="limit to one pet by name")
    sp.add_argument("--window", type=float, default=168.0, help="adherence window hours (default 168 = 7d)")
    sp.set_defaults(func=cmd_stats)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    with Store(args.db) as store:
        return int(args.func(store, args))


if __name__ == "__main__":
    raise SystemExit(main())

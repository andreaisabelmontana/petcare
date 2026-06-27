"""Domain types for PetCare.

These are plain dataclasses describing the records the store persists.
Timestamps are stored as ISO-8601 strings in SQLite and surfaced here as
`datetime` / `date` objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional


class ActivityKind(str, Enum):
    """The kinds of activity that can be logged against a pet."""

    FEEDING = "feeding"
    WALK = "walk"
    MEDICATION = "medication"
    WEIGHT = "weight"
    VET_VISIT = "vet_visit"


class ReminderKind(str, Enum):
    """The kinds of recurring reminder a pet can have."""

    MEDICATION = "medication"
    VACCINATION = "vaccination"
    FEEDING = "feeding"
    WALK = "walk"
    VET_CHECKUP = "vet_checkup"


@dataclass
class Household:
    name: str
    join_code: str
    id: Optional[int] = None


@dataclass
class Member:
    household_id: int
    name: str
    role: str = "member"  # e.g. "owner", "member"
    id: Optional[int] = None


@dataclass
class Pet:
    household_id: int
    name: str
    species: str
    breed: Optional[str] = None
    birthdate: Optional[date] = None
    weight_kg: Optional[float] = None
    id: Optional[int] = None


@dataclass
class LogEntry:
    pet_id: int
    kind: ActivityKind
    at: datetime
    # Free-text note, e.g. "full bowl", drug name for medication, etc.
    note: Optional[str] = None
    # For WEIGHT entries this carries the measured weight in kg.
    value: Optional[float] = None
    # Who logged it (member id), optional.
    member_id: Optional[int] = None
    id: Optional[int] = None


@dataclass
class Reminder:
    pet_id: int
    kind: ReminderKind
    label: str
    # Recurrence is expressed as a fixed interval in hours.
    # e.g. meds every 12h -> 12; annual vaccination -> 24 * 365.
    interval_hours: int
    # The reference point the schedule counts from.
    start_at: datetime
    active: bool = True
    id: Optional[int] = None

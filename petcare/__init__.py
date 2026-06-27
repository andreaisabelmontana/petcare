"""PetCare — household pet management with logging, reminders, and analytics.

A SQLite-backed application core for tracking pets, household members,
activity logs (feeding, walks, medication, weight, vet visits), and
scheduled reminders, plus domain analytics: age, weight trends,
reminder due-dates, and medication adherence.
"""

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
from petcare import analytics

__all__ = [
    "ActivityKind",
    "Household",
    "LogEntry",
    "Member",
    "Pet",
    "Reminder",
    "ReminderKind",
    "Store",
    "analytics",
]

__version__ = "1.0.0"

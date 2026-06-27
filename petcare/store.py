"""SQLite-backed persistence for PetCare.

`Store` owns a single connection and exposes CRUD for households, members,
pets, log entries and reminders. It performs no domain analytics itself —
see :mod:`petcare.analytics` for that. Schema is created on first use.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Iterable, List, Optional

from petcare.model import (
    ActivityKind,
    Household,
    LogEntry,
    Member,
    Pet,
    Reminder,
    ReminderKind,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS household (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    join_code  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS member (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id  INTEGER NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member'
);

CREATE TABLE IF NOT EXISTS pet (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id  INTEGER NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    species       TEXT NOT NULL,
    breed         TEXT,
    birthdate     TEXT,
    weight_kg     REAL
);

CREATE TABLE IF NOT EXISTS log_entry (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id     INTEGER NOT NULL REFERENCES pet(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    at         TEXT NOT NULL,
    note       TEXT,
    value      REAL,
    member_id  INTEGER REFERENCES member(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS reminder (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id          INTEGER NOT NULL REFERENCES pet(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    label           TEXT NOT NULL,
    interval_hours  INTEGER NOT NULL,
    start_at        TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_log_pet_at ON log_entry(pet_id, at);
CREATE INDEX IF NOT EXISTS ix_reminder_pet ON reminder(pet_id);
"""


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Store:
    """A SQLite-backed PetCare store.

    Pass ``":memory:"`` for an ephemeral database (used by the tests) or a
    file path for a persistent one.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------- household
    def add_household(self, household: Household) -> Household:
        cur = self._conn.execute(
            "INSERT INTO household (name, join_code) VALUES (?, ?)",
            (household.name, household.join_code),
        )
        self._conn.commit()
        household.id = int(cur.lastrowid)
        return household

    def get_household(self, household_id: int) -> Optional[Household]:
        row = self._conn.execute(
            "SELECT * FROM household WHERE id = ?", (household_id,)
        ).fetchone()
        return self._row_to_household(row) if row else None

    # ----------------------------------------------------------------- member
    def add_member(self, member: Member) -> Member:
        cur = self._conn.execute(
            "INSERT INTO member (household_id, name, role) VALUES (?, ?, ?)",
            (member.household_id, member.name, member.role),
        )
        self._conn.commit()
        member.id = int(cur.lastrowid)
        return member

    def list_members(self, household_id: int) -> List[Member]:
        rows = self._conn.execute(
            "SELECT * FROM member WHERE household_id = ? ORDER BY id",
            (household_id,),
        ).fetchall()
        return [self._row_to_member(r) for r in rows]

    # ----------------------------------------------------------------- pet
    def add_pet(self, pet: Pet) -> Pet:
        cur = self._conn.execute(
            """INSERT INTO pet (household_id, name, species, breed, birthdate, weight_kg)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                pet.household_id,
                pet.name,
                pet.species,
                pet.breed,
                pet.birthdate.isoformat() if pet.birthdate else None,
                pet.weight_kg,
            ),
        )
        self._conn.commit()
        pet.id = int(cur.lastrowid)
        return pet

    def get_pet(self, pet_id: int) -> Optional[Pet]:
        row = self._conn.execute(
            "SELECT * FROM pet WHERE id = ?", (pet_id,)
        ).fetchone()
        return self._row_to_pet(row) if row else None

    def find_pet(self, household_id: int, name: str) -> Optional[Pet]:
        row = self._conn.execute(
            "SELECT * FROM pet WHERE household_id = ? AND name = ? COLLATE NOCASE",
            (household_id, name),
        ).fetchone()
        return self._row_to_pet(row) if row else None

    def list_pets(self, household_id: int) -> List[Pet]:
        rows = self._conn.execute(
            "SELECT * FROM pet WHERE household_id = ? ORDER BY id",
            (household_id,),
        ).fetchall()
        return [self._row_to_pet(r) for r in rows]

    def update_pet(self, pet: Pet) -> Pet:
        if pet.id is None:
            raise ValueError("cannot update a pet without an id")
        self._conn.execute(
            """UPDATE pet SET name = ?, species = ?, breed = ?,
               birthdate = ?, weight_kg = ? WHERE id = ?""",
            (
                pet.name,
                pet.species,
                pet.breed,
                pet.birthdate.isoformat() if pet.birthdate else None,
                pet.weight_kg,
                pet.id,
            ),
        )
        self._conn.commit()
        return pet

    def delete_pet(self, pet_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM pet WHERE id = ?", (pet_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ----------------------------------------------------------------- log
    def add_log(self, entry: LogEntry) -> LogEntry:
        cur = self._conn.execute(
            """INSERT INTO log_entry (pet_id, kind, at, note, value, member_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.pet_id,
                entry.kind.value,
                _iso(entry.at),
                entry.note,
                entry.value,
                entry.member_id,
            ),
        )
        self._conn.commit()
        entry.id = int(cur.lastrowid)
        return entry

    def list_logs(
        self,
        pet_id: int,
        kind: Optional[ActivityKind] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[LogEntry]:
        sql = "SELECT * FROM log_entry WHERE pet_id = ?"
        params: list[object] = [pet_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        if since is not None:
            sql += " AND at >= ?"
            params.append(_iso(since))
        if until is not None:
            sql += " AND at <= ?"
            params.append(_iso(until))
        sql += " ORDER BY at ASC, id ASC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_log(r) for r in rows]

    # ----------------------------------------------------------------- reminder
    def add_reminder(self, reminder: Reminder) -> Reminder:
        cur = self._conn.execute(
            """INSERT INTO reminder (pet_id, kind, label, interval_hours, start_at, active)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                reminder.pet_id,
                reminder.kind.value,
                reminder.label,
                reminder.interval_hours,
                _iso(reminder.start_at),
                1 if reminder.active else 0,
            ),
        )
        self._conn.commit()
        reminder.id = int(cur.lastrowid)
        return reminder

    def list_reminders(
        self, pet_id: int, active_only: bool = True
    ) -> List[Reminder]:
        sql = "SELECT * FROM reminder WHERE pet_id = ?"
        params: list[object] = [pet_id]
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY id"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_reminder(r) for r in rows]

    def list_reminders_for_household(
        self, household_id: int, active_only: bool = True
    ) -> List[Reminder]:
        out: List[Reminder] = []
        for pet in self.list_pets(household_id):
            assert pet.id is not None
            out.extend(self.list_reminders(pet.id, active_only=active_only))
        return out

    def set_reminder_active(self, reminder_id: int, active: bool) -> None:
        self._conn.execute(
            "UPDATE reminder SET active = ? WHERE id = ?",
            (1 if active else 0, reminder_id),
        )
        self._conn.commit()

    # ----------------------------------------------------------------- mappers
    @staticmethod
    def _row_to_household(row: sqlite3.Row) -> Household:
        return Household(id=row["id"], name=row["name"], join_code=row["join_code"])

    @staticmethod
    def _row_to_member(row: sqlite3.Row) -> Member:
        return Member(
            id=row["id"],
            household_id=row["household_id"],
            name=row["name"],
            role=row["role"],
        )

    @staticmethod
    def _row_to_pet(row: sqlite3.Row) -> Pet:
        return Pet(
            id=row["id"],
            household_id=row["household_id"],
            name=row["name"],
            species=row["species"],
            breed=row["breed"],
            birthdate=date.fromisoformat(row["birthdate"]) if row["birthdate"] else None,
            weight_kg=row["weight_kg"],
        )

    @staticmethod
    def _row_to_log(row: sqlite3.Row) -> LogEntry:
        return LogEntry(
            id=row["id"],
            pet_id=row["pet_id"],
            kind=ActivityKind(row["kind"]),
            at=_parse_dt(row["at"]),
            note=row["note"],
            value=row["value"],
            member_id=row["member_id"],
        )

    @staticmethod
    def _row_to_reminder(row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            pet_id=row["pet_id"],
            kind=ReminderKind(row["kind"]),
            label=row["label"],
            interval_hours=row["interval_hours"],
            start_at=_parse_dt(row["start_at"]),
            active=bool(row["active"]),
        )

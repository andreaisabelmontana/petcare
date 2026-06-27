# PetCare

A household pet-management application core in Python: a SQLite-backed store
for pets, household members, activity logs and recurring reminders, plus the
domain analytics that make the data useful — age, weight trends, what's due,
and medication adherence. Standard library only; pytest for the tests.

> **Scope note.** The showcase page advertised a Flask + Azure deployment with
> CI/CD and Prometheus metrics. That pipeline is *not* in this repo. What lives
> here is the real, runnable application **core**: the data model, persistence,
> analytics, a CLI, and tests. No web server, no cloud — just code you can run.

## Data model

Five record types, persisted to SQLite (`petcare/store.py`):

| Table        | Fields                                                                 |
|--------------|------------------------------------------------------------------------|
| `household`  | name, unique join code                                                 |
| `member`     | household, name, role (`owner` / `member`)                             |
| `pet`        | household, name, species, breed, birthdate, weight_kg                  |
| `log_entry`  | pet, kind, timestamp, note, value, member                              |
| `reminder`   | pet, kind, label, interval_hours, start_at (anchor), active            |

Activity kinds: `feeding`, `walk`, `medication`, `weight`, `vet_visit`.
Reminder kinds: `medication`, `vaccination`, `feeding`, `walk`, `vet_checkup`.
Timestamps are stored as ISO-8601 text; foreign keys cascade on delete.

## Reminders

A reminder is a fixed-interval schedule anchored at `start_at` and repeating
every `interval_hours` — e.g. meds every 12h (`interval_hours=12`) or an annual
vaccination (`interval_hours=24*365`). The **what's-due** query
(`analytics.whats_due`) walks each active reminder, finds the most recent
matching log entry as "last done", computes the next-due time from it, and
returns everything due now or within a horizon — overdue items sorted first.

## Analytics (`petcare/analytics.py`)

- **Age** — `age_in_years` / `age_in_months` / `describe_age`, counting a
  birthday only once it has actually passed (leap-day safe).
- **Weight trend** — `weight_trend` classifies a series as gaining / losing /
  stable (a change within ±2% of the first reading is "stable") and reports the
  delta and percentage change.
- **Next due** — `next_due` projects a reminder's schedule to the next slot,
  either one interval after the last completion or forward from the anchor.
- **Medication adherence** — `medication_adherence` counts scheduled dose slots
  in a window vs. doses actually logged (capped at 100%).
- **Activity summary** — `activity_summary` rolls up per-pet counts by kind,
  totals, last activity and latest weight.

All analytics are pure functions; they never mutate the database.

## CLI

```
python -m petcare.cli [--db PATH] [--household ID] [--now ISO] <command>

  add-pet NAME SPECIES [--breed B] [--birthdate YYYY-MM-DD] [--weight KG]
  log     PET KIND [--note N] [--value KG] [--at ISO]
  due     [--horizon HOURS]
  stats   [--pet NAME] [--window HOURS]
```

`--now` overrides the clock so `due`/`stats` are reproducible. A committed
sample household lives at `data/sample.db` (rebuild with
`python data/seed_sample.py`).

### Real example — against the committed sample household

```
$ python -m petcare.cli --db data/sample.db --now 2026-06-22T19:00 stats
Luna — cat, domestic shorthair (4 yr)
  activity: 18 entries (feeding=14, weight=4)
  weight: 4 -> 4.4 kg (gaining, +0.4 kg / +10%)

Max — dog, border collie (6 yr)
  activity: 33 entries (feeding=14, walk=7, medication=12)
  weight: 18.5 kg (need 2+ readings for a trend)
  adherence (Apoquel (every 12h), last 168h): 11/14 = 79%

$ python -m petcare.cli --db data/sample.db --now 2026-06-22T19:00 due
due within 24h (as of 2026-06-22T19:00):
  [OVERDUE by 11h] Max: Apoquel (every 12h) -> 2026-06-22T08:00
```

## Demo

`python demo.py` seeds a two-pet household, logs a week of activity, then prints
due reminders, weight trends and adherence:

```
PetCare demo — household #1 as of 2026-06-22T19:00
================================================================

Members:
  - Andrea (owner)
  - Sam (member)

Reminders due within 7 days:
  [  OVERDUE by 11h] Max: Apoquel (every 12h) -> 2026-06-22T08:00

Per-pet summary:

  Luna — cat, domestic shorthair (4 yr)
    activity (7d): 18 entries — feeding=14, weight=4
    weight: 4 -> 4.4 kg (gaining, +0.4 kg / +10%)

  Max — dog, border collie (6 yr)
    activity (7d): 33 entries — feeding=14, walk=7, medication=12
    adherence (Apoquel (every 12h)): 11/14 doses = 79%
```

(Luna is gaining ~10% over the week; Max missed two evening doses, so his
twice-daily adherence lands at 11 of 14.)

## Tests

```
$ pip install pytest
$ python -m pytest -q
...................                                                       [100%]
19 passed in 0.11s
```

Covers: household/member/pet CRUD and log persistence; age across birthday and
leap-day boundaries; weight-trend gain/loss/stable detection; `whats_due`
ordering, overdue detection and horizon; adherence (full / partial / capped);
and activity summaries.

## Layout

```
petcare/        package: model, store (SQLite), analytics, cli
tests/          pytest suite
data/           sample.db + seed_sample.py
demo.py         end-to-end walkthrough
requirements.txt
index.html      project showcase page (GitHub Pages)
```

## License

MIT — see [LICENSE](LICENSE).

# PetCare — Interactive Showcase

An interactive static showcase for **PetCare**, a household pet management web app: create or join a
household, add pets, and log feeding, vet visits and more — backed by a full production pipeline.

🔗 **Live site:** https://andreaisabelmontana.github.io/petcare/

## What it does
- **Households** — create or join with a unique join code; manage members.
- **Pets** — add, edit, and delete the pets your household looks after.
- **Log entries** — record feeding, vet visits, walks, meds and more per pet.
- **Accounts** — login, signup, and profile management; REST API + UI routes.
- **Production-grade** — 91% test coverage, CI/CD, Docker, `/health` + Prometheus `/metrics`, deployed on Azure.

**Stack:** Flask (Python 3.12) · PostgreSQL Flexible (Azure) · SQLAlchemy + Flask-Migrate · Pytest · GitHub Actions + Docker · Prometheus · Microsoft Azure.

## About this repo
An original, hand-built static site (single `index.html`, no framework) presenting the project,
with a scripted interactive household dashboard (pick a pet → log entries to a live timeline).
Built from scratch; the demo uses sample data.

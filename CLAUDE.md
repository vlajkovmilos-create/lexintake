# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

LexIntake is an AI client-intake SaaS for Serbian law offices. A prospective client chats with a Claude-powered assistant (`upitnik.html`); when the conversation ends, the backend extracts a structured case analysis, stores it, emails the lawyer (Resend), and makes a PDF report available on the lawyer's dashboard. Subscriptions are billed through Lemon Squeezy.

**All code identifiers, routes, DB columns, comments, commit messages and UI text are in Serbian (Latin script).** Follow that convention: e.g. `ruter`, `advokat`, `prijem`, `podaci`, `/prijem/poruka`, `status_pretplate`. Commit messages are short Serbian imperatives ("Popravi …", "Dodaj …", "Ukloni …").

## Layout

- `backend/` – FastAPI app (Python 3.11, see `runtime.txt`). Deployed to Render (`render.yaml`, `Procfile`) as `lexintake-backend`.
- `docs/` – static frontend (plain HTML/CSS/vanilla JS, no build step), served by GitHub Pages (`.nojekyll`). `index.html` is the landing page; `pages/` holds `prijava` (login), `registracija`, `tabla` (dashboard), `podesavanja` (settings), `upitnik` (client chat).

## Commands

Run everything from `backend/` (imports are package-relative from `app`, and the SQLite path / `.env` are resolved relative to the CWD):

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload        # local dev server, docs at /docs
```

There is no test suite, linter, or formatter configured.

Required env vars (read from `backend/.env` via pydantic-settings; the app fails at import time without them): `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `SECRET_KEY`. Optional: `DATABASE_URL` (defaults to `sqlite:///./lexintake.db`; PostgreSQL via psycopg2 is also supported), `FROM_EMAIL`, `LEMONSQUEEZY_WEBHOOK_SECRET` (webhook requests are all rejected if empty).

## Backend architecture

- `app/main.py` – creates tables with `Base.metadata.create_all`, then runs `migriraj_bazu()`, an ad-hoc migration that `ALTER TABLE advokati ADD COLUMN`s any missing subscription columns. There is no Alembic: **when adding a column to an existing table, add it to `nove_kolone` in `migriraj_bazu()` too**, otherwise existing databases won't get it.
- `app/models/__init__.py` – two models: `Advokat` (lawyer account + subscription state) and `Prijem` (one completed client intake, including the raw conversation in `razgovor_json`).
- `app/routes/` – thin routers (each module exposes `ruter`), business logic lives in `app/services/`. Services and `database.py` call `get_settings()` and create clients (Anthropic, Resend, ReportLab fonts) at module import time.

### Intake flow (`routes/prijem.py` + `services/ai.py`)

- The chat is **stateless on the server**: the frontend sends the full `istorija` (message list) on every `POST /prijem/poruka` and gets the updated list back. An empty history returns a hard-coded greeting without calling the model.
- Only lawyers with `status_pretplate` in `probni_period`/`aktivna` can receive intakes (403 otherwise).
- The system prompt in `SISTEM_PORUKA` tells the model to end the conversation with a sentence starting with the sentinel `RAZGOVOR_ZAVRŠEN:`. The route detects that string to mark the intake finished — keep the prompt and the check in sync.
- On completion `_sacuvaj_prijem` calls `generisi_analizu` (second model call that must return a JSON object whose keys map 1:1 to `Prijem` columns), saves the row, then emails the lawyer. Analysis and email failures are swallowed so the intake is still saved.
- Model is hard-coded as `claude-sonnet-4-6` in `services/ai.py`.

### Auth

JWT (HS256, 24h, `sub` = advokat id) issued by `/auth/registracija` and `/auth/prijava`. Only `GET /auth/ja` actually validates the token; the other routes (`/prijem/lista/{advokat_id}`, `/prijem/detalji/…`, `/prijem/status/…`, `/prijem/pdf/…`, `/auth/azuriraj/{advokat_id}`) take IDs from the URL without checking the token.

### Payments

`POST /placanje/webhook` verifies the Lemon Squeezy HMAC-SHA256 `X-Signature`, matches the buyer to an `Advokat` by email, and maps product name → `plan` via `MAPA_PROIZVODA` and LS status → `status_pretplate` (`probni_period` / `aktivna` / `otkazana` / `istekla`). New registrations start with a 14-day trial.

### PDF

`services/pdf.py` builds the report with ReportLab and registers DejaVu fonts from `/usr/share/fonts/truetype/dejavu/` at import time (needed for Serbian diacritics) — that path must exist on the host. Download filenames are ASCII-sanitized by `_ocisti_ime_fajla` because non-ASCII chars break the `Content-Disposition` header.

## Frontend ↔ backend contract

- Each page hard-codes `API_URL = "https://lexintake-backend.onrender.com"`; change it per page to point at a local backend.
- Session state lives in `localStorage`: `lex_token`, `lex_ime`, `lex_email`, `lex_advokat_id` (the id is decoded client-side from the JWT payload after login/registration).
- The client chat link is `pages/upitnik.html?advokat=<id>`.
- Response field names used by the pages (e.g. `odgovor`, `istorija`, `zavrseno`, `prijem_id`, `detail`) are the contract — renaming them in the backend requires updating the HTML pages.

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
pip install -r requirements-dev.txt  # requirements.txt + pytest/httpx
uvicorn app.main:app --reload        # local dev server on :8000, docs at /docs
python -m pytest                     # all tests
python -m pytest tests/test_prijem.py::test_ceo_tok_razgovora   # single test
```

Tests (`backend/tests/`) use a temporary SQLite DB and replace Claude/Resend with fakes via the `lazni_ai` fixture in `conftest.py` (it monkeypatches the names imported into `services/prijem.py`), so they cost nothing. No linter/formatter is configured.

For the frontend, serve `docs/` locally (e.g. `cd docs && python -m http.server 5500`); `docs/js/zajednicko.js` automatically points `API_URL` at `http://localhost:8000` when the page is opened from localhost.

Required env vars (read from `backend/.env` via pydantic-settings; the app fails at import time without them): `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `SECRET_KEY`. Optional (see `app/config.py`): `DATABASE_URL` (defaults to `sqlite:///./lexintake.db`; production uses PostgreSQL on Neon via psycopg2), `AI_MODEL` (default `claude-sonnet-5-5`), `FROM_EMAIL` (must be on a domain verified in Resend), `LEMONSQUEEZY_WEBHOOK_SECRET` (webhook requests are all rejected if empty), `FRONTEND_URL` (links in emails), `CORS_ORIGINI`, and the abuse limits `MAX_*`.

## Backend architecture

- `app/main.py` – creates tables with `Base.metadata.create_all`, then runs `migriraj_bazu()`, an ad-hoc migration that adds missing columns to existing tables and backfills them. There is no Alembic: **when adding a column to an existing table, add it to `nove_kolone` in `migriraj_bazu()` too**, using types valid in both SQLite and PostgreSQL (`TIMESTAMP`, not `DATETIME`). Also registers a `RequestValidationError` handler so every 422 has a single Serbian string in `detail`.
- `app/models/__init__.py` – `Advokat` (lawyer account, `javni_kod` for the public intake link, subscription state, white-label `logo`/`boja`, hashed API key), `Prijem` (one completed intake; `razgovor_json` is the display transcript, `analiza_status` = `u_obradi`/`gotova`/`neuspesna`, `dodeljen_id` = team member handling it), `Razgovor` (an in-progress or finished chat session) and `Pozivnica` (team invite; only the token hash is stored).
- **Offices/teams:** there is no separate office table. The owner's `Advokat` row *is* the office: team members have `vlasnik_id` pointing to it, and `advokat.kancelarija_id` (= `vlasnik_id or id`) is what intakes (`Prijem.advokat_id`), the intake link, subscription, branding and API key hang off. Use `vlasnik_kancelarije()` for office-level data and `samo_vlasnik` (routes/kancelarija.py) for owner-only actions. Plan limits live in `FUNKCIJE_PLANA` (`services/placanje.py`; trial includes everything).
- `app/routes/` – thin routers (each module exposes `ruter`), business logic lives in `app/services/`. Services and `database.py` call `get_settings()` and create clients (Anthropic, Resend, ReportLab fonts) at module import time.
- `app/utils/ogranicenje.py` – in-memory sliding-window rate limiter (per process; fine for one Render instance).

### Intake flow (`routes/prijem.py` + `services/prijem.py` + `services/ai.py`)

- The client opens `upitnik.html?k=<javni_kod>`, gives consent, and `POST /prijem/razgovor` creates a `Razgovor` (greeting and system prompt are frozen in the row). Each `POST /prijem/poruka` sends only `sesija_id` + `poruka`; **the history lives on the server** in `Razgovor.poruke_json`, in exactly the shape sent to the Claude API (assistant turns are full content-block lists, including thinking blocks). Keep it append-only — never rewrite earlier messages or the system prompt mid-conversation (preserved-thinking check on newer models). `GET /prijem/razgovor/{sesija_id}` restores a chat after a page reload.
- Claude calls go through `client.beta.messages.create` with `fallbacks="default"` (beta `server-side-fallback-2026-07-01`), `effort` low for chat / medium for analysis. A `refusal` stop reason is not stored; the client gets a polite fallback message.
- Lawyers can receive intakes while `status_pretplate` is `probni_period` (until `datum_isteka_probe`), `aktivna`, or `otkazana` (until `datum_isteka_pretplate`); `osvezi_status_pretplate` flips expired ones to `istekla`. Starter plan has a monthly cap (`LIMIT_PRIJEMA_MESECNO`), plus per-lawyer/day and per-IP limits from settings.
- The system prompt in `SISTEM_PORUKA` tells the model to end with a sentence starting with the sentinel `RAZGOVOR_ZAVRŠEN:`. `nastavi_razgovor` detects it and strips it from the text shown to the client — keep the prompt and the check in sync. A hard cap (`MAX_PORUKA_PO_RAZGOVORU`) closes the chat without a model call.
- On completion `sacuvaj_prijem` stores the `Prijem` immediately (`analiza_status="u_obradi"`), and `obradi_analizu` runs as a FastAPI background task with its own DB session: `generisi_analizu` (structured output via `output_config.format` + `SEMA_ANALIZE`, keys map 1:1 to `Prijem` columns, values truncated to column lengths), then the email to the lawyer. Lawyers can re-run a failed analysis (`POST /prijem/analiza/{id}`) or delete an intake (`DELETE /prijem/{id}`). Unfinished conversations older than `DANA_CUVANJA_NEDOVRSENIH` are deleted.

### Auth

JWT (PyJWT, HS256, 24h, `sub` = advokat id) issued by `/auth/registracija` and `/auth/prijava`; passwords are bcrypt. Every lawyer route depends on `trenutni_advokat` (`services/auth.py`), which reads the `Authorization: Bearer` header — lawyer IDs never come from the URL, and intakes of other lawyers return 404. Emails are stored and compared lowercase.

### Team, white-label, public API (`routes/kancelarija.py`, `routes/api.py`, `services/kancelarija.py`)

- Invites: owner `POST /kancelarija/pozivnica` → email with `pages/pozivnica.html?t=<token>` → `POST /kancelarija/pozivnica/prihvati` creates the member account. New-intake emails go to every office member with `obavestenja` on.
- White-label (plan Kancelarija): logo stored as a PNG/JPEG/WebP data URL (≤200 KB, verified with Pillow) + hex color; `brending()` returns them for the questionnaire (`/prijem/kancelarija/{kod}`) and the PDF only while the plan allows it.
- Public REST API under `/api/v1` authenticated with `Authorization: Bearer lex_…` (separate from lawyer JWTs), read-only, rate-limited, disabled when the subscription lapses.
- Language: the chat replies in Cyrillic if the client writes Cyrillic; English is allowed only for `probni`/`pro`/`kancelarija` (decided when the conversation starts). Analysis is always Serbian Latin.

### Payments

`POST /placanje/webhook` verifies the Lemon Squeezy HMAC-SHA256 `X-Signature`, handles only `subscription_*` events, finds the lawyer by `meta.custom_data.advokat_id` (set by the checkout links on `podesavanja.html`) or by email, maps product name → `plan` via `MAPA_PROIZVODA` and LS status → `status_pretplate` via `MAPA_STATUSA`, and stores `ends_at` in `datum_isteka_pretplate`. New registrations start with a 14-day trial.

### PDF

`services/pdf.py` builds the report with ReportLab using the DejaVu fonts bundled in `app/fonti/` (needed for Serbian diacritics; don't use the built-in Helvetica). All text goes through `_t()` (XML escape) before `Paragraph`. Download filenames are ASCII-sanitized by `_ocisti_ime_fajla` because non-ASCII chars break the `Content-Disposition` header (exposed via CORS so the dashboard can read it).

## Frontend ↔ backend contract

- `docs/js/zajednicko.js` is loaded by every app page: `API_URL` (localhost vs. Render), `esc()`/`escRedovi()` (**escape everything that goes into `innerHTML`** — the data comes from clients and the model), `porukaGreske()`, `apiAdvokat()` (adds the token, logs out on 401) and the session helpers.
- Session state lives in `localStorage`: `lex_token`, `lex_ime`, `lex_email`, `lex_advokat_id` (from `advokat_id` in the login/registration response). The client chat keeps its `sesija_id` in `sessionStorage`.
- The client chat link is `pages/upitnik.html?k=<javni_kod>` (shown on `podesavanja.html`). Email links use `pages/tabla.html?prijem=<id>`; unauthenticated users go through `prijava.html?nazad=…` and come back.
- Response field names used by the pages (e.g. `odgovor`, `sesija_id`, `zavrseno`, `prijem_id`, `analiza_status`, `detail`) are the contract — renaming them in the backend requires updating the HTML pages.
- `pages/politika-privatnosti.html` and `pages/uslovi-koriscenja.html` are **drafts** (marked NACRT) with placeholders that must be filled and legally reviewed.
- Emails are sent from `lex.vlajkov.rs` (Resend, EU region); `FROM_EMAIL` must stay on that verified domain.

# Gradus IQ

AI-powered career and academic companion for Texas A&M students.
Dallas AI Group 6 | 2026 Summer Cohort.

[![CI](https://github.com/bonaguidin/GradusIQ/actions/workflows/ci.yml/badge.svg)](https://github.com/bonaguidin/GradusIQ/actions/workflows/ci.yml)

© 2026 GradusIQ. All rights reserved. Unauthorized copying, modification, or distribution of this software, in whole or in part, is prohibited.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- Node.js 20+ for the React/Vite frontend
- An OpenRouter API key for the primary Gradus IQ AI path
- A shared `GRADUSIQ_PROXY_SECRET` for the Vite/Vercel server-side proxy and backend.

---

## Setup

```bash
# 1. Install backend dependencies
uv sync

# 2. Configure your API key
cp .env.example .env
# then edit .env and replace "your-key-here" with your actual key

# 3. Install frontend dependencies
cd frontend
npm install
cd ..
```

---

## Running the app

The app is two processes — a Python backend and a React frontend — run in
separate terminals. Both need to be running for the dashboard's live
analysis calls (FIT/GAP/SHIFT/PROFESSOR_COMMENTS) to work.

**Terminal 1 — backend** (FastAPI bridge, port 8000):

```bash
uv run uvicorn GradusIQ_career.api:app --reload --port 8000
```

**Terminal 2 — frontend** (Vite dev server):

```bash
cd frontend
npm run dev
```

Vite prints a local URL (typically `http://localhost:5173`). Open it in a
browser — you'll land on the login page with a student dropdown
(mock/profile-select auth, no real credentials). Pick a student to enter
the dashboard. The Vite dev server proxies `/api/*` requests to
`localhost:8000` and attaches `GRADUSIQ_PROXY_SECRET` server-side (configured
in `frontend/vite.config.ts`). The secret is deliberately not `VITE_`-prefixed
and is never available to browser modules.

## Secure demo deployment

The active frontend is React + Vite. In production the browser calls a
same-origin Vercel Function, `frontend/api/proxy.mjs`; it does not call Render
directly. The function validates the requested student/feature route, forwards
it to Render, and adds `X-GradusIQ-Proxy-Secret` from server-only environment
configuration. Render rejects missing or incorrect credentials with HTTP 401
using constant-time comparison.

Configure these in **Vercel** and redeploy:

```bash
GRADUSIQ_BACKEND_URL=https://your-render-service.example
GRADUSIQ_PROXY_SECRET=<same-strong-random-value-as-render>
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-anon-key>
RESEND_API_KEY=<server-only-key>   # bug/feature report emails
```

The two `VITE_`-prefixed values are read at import time by
`frontend/src/lib/supabase.ts`, which throws if either is unset — so a missing
one breaks the browser bundle at load, not at request time. They are baked into
the client bundle at build time and are **not** duplicates of the
`SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` pair in the Render block below:
different layer, configured separately, even where the values coincide.

Configure these in **Render** and restart/redeploy:

```bash
GRADUSIQ_PROXY_SECRET=<same-strong-random-value-as-vercel>
GRADUSIQ_ALLOWED_ORIGINS=https://your-vercel-domain.example
GRADUSIQ_RATE_LIMIT_REQUESTS=10
GRADUSIQ_RATE_LIMIT_WINDOW_SECONDS=60
GRADUSIQ_MAX_CONCURRENT_AI_REQUESTS=2
OPENROUTER_API_KEY=<server-only-key>
TAVILY_API_KEY=<server-only-key>
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-anon-key>
```

`SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` fail differently from the rest of
this list: they are read per request by `GradusIQ_career/supabase_client.py`'s
`_required_env`, not at startup. Omitting them still lets the service boot and
serve `/health` and the demo slug routes, while every session-scoped
`/api/v2/student/me/*` request returns `503 {"detail":"SUPABASE_URL is not
set."}`. Use the publishable (anon) key — never the secret/service-role key,
which would bypass the RLS every one of those routes depends on.

The rate limit is a bounded sliding window shared by trusted proxy requests in
one backend process. The concurrency semaphore is also per process. Neither is
keyed per client, and neither is distributed across workers or Render
instances, so both ceilings are **per process**: N workers serve N x the
configured limit.

Two mechanisms enforce that assumption rather than merely documenting it:

- **`Procfile`** pins the start command to `--workers 1`.
- **`create_app()`** raises `AIConfigError` at construction if `WEB_CONCURRENCY`
  is set to anything other than `1`, catching platforms that set worker count
  by environment variable instead of a start-command flag. The deploy fails
  loudly instead of quietly serving a multiplied limit.

Before scaling horizontally — more workers *or* more instances — move both the
limiter and the concurrency gate to a shared external store (e.g. Redis).
Raising worker count alone will now fail startup, by design.

CORS allows only explicitly configured browser origins and is defense in depth,
not authentication. `/health` is the only intentionally public backend route.

The Vercel function is configured for a 300-second maximum duration. Confirm
that the selected Vercel plan supports that duration, or lower the live-model
timeout to the plan limit before deployment.

### Cache and live-generation behavior

The five committed demo cache files cover FIT, GAP, and SHIFT. An authenticated
individual-feature request returns a matching successful cache entry before
constructing an OpenRouter client or taking a live-AI concurrency slot. Cache
entries are checked against the requested student ID, feature name, success
status, empty error list, and current feature output contract. A malformed,
failed, mismatched, or stale entry is treated as a cache miss.

There is no whole-student analysis HTTP endpoint. `PROFESSOR_COMMENTS` has no
committed cache and therefore requires live OpenRouter configuration. Unknown
students return 404. On any other cache miss, live generation requires
`OPENROUTER_API_KEY`; GAP role research may additionally use Tavily before
falling back to its static role requirements.

### Current demo boundaries

- Canvas data and profile-select authentication are mocked for the demo.
- Supabase is live, but only on the session-scoped path: a runtime client
  (`GradusIQ_career/supabase_client.py`), an applied schema (10 migrations under
  `supabase/migrations/`), and RLS-scoped `/api/v2/student/me/*` routes. The
  demo dashboard described above is unaffected — it still reads mock JSON from
  `data/students/` under the profile-select auth in the preceding bullet.
- Adzuna/JSearch job-posting integration remains planned and is not executable.
- PDF/DOCX export is not implemented in the active application.
- Registered AI features are FIT, GAP, SHIFT, and PROFESSOR_COMMENTS.

### Node version

The frontend requires **Node.js 20+** (pinned in `frontend/.nvmrc` and
`frontend/package.json`'s `engines` field). If you use
[nvm](https://github.com/nvm-sh/nvm), run `nvm use` from the `frontend/`
directory to switch automatically, or `nvm use 20` from anywhere.

Running `npm run dev` on an older Node version (e.g. 16 or 18) fails with
a cryptic error rather than a clear version check:

```
TypeError: crypto$2.getRandomValues is not a function
```

If you see this, it means your active Node is too old — run `node --version`
to check, then switch to Node 20+ and retry.

---

## Validating data

```bash
uv run python data/catalog/validate_catalog.py
uv run python data/students/validate_students.py
```

## Unified student profile

All academic and career features should build on the same JSON record in
`data/students/`. The schema contract lives in
`data/reference/unified_student_schema.md`.

The student validator checks the shared foundation fields, including academic
record counts, career fields, and profile completeness gates used by the
dashboard and future prompt/UI code.

## Design standards

Building a new page, tab or feature? Follow [docs/DESIGN.md](docs/DESIGN.md):
the tokens, card surface, buttons, loading/empty/error states, motion and
copy rules the app uses, with a checklist to run before opening a PR.

---

## Other commands

| Command                                            | What it does                              |
|----------------------------------------------------|-------------------------------------------|
| `uv run python data/catalog/fetch_smu_catalog.py`  | Fetch the SMU course catalog              |
| `uv run python data/catalog/import_catalog.py`     | Import normalized catalog JSON into the DB |

## AI Architecture

Gradus IQ uses OpenRouter as the primary app AI gateway.

### Role-Based Model Routing

Model routing is centralized in `GradusIQ_career/ai/model_config.py` and can be
overridden with `GRADUSIQ_MODEL_*` environment variables.

| Role | Purpose | Default model family |
|---------|---------|---------|
| orchestrator | Workflow orchestration | Deepseek R1 |
| career | FIT / GAP / SHIFT career analysis | Qwen3 235B A22B Thinking 2507 OR DeepSeek R1 |
| academic | Academic analysis features | Qwen3 235B A22B Thinking 2507 |
| parsing | JSON normalization and cleanup | Qwen3 32B |
| chat | Student chat responses | TODO |
| report | Report synthesis | Gemini 2.5 Flash Lite |

### Environment Variables

Required for the primary app AI path:

```bash
OPENROUTER_API_KEY=your-openrouter-key-here
```

Optional role overrides:

```bash
GRADUSIQ_MODEL_ORCHESTRATOR=
GRADUSIQ_MODEL_CAREER=
GRADUSIQ_MODEL_ACADEMIC=
GRADUSIQ_MODEL_PARSING=
GRADUSIQ_MODEL_CHAT=
GRADUSIQ_MODEL_REPORT=
```

Supabase is implemented and separate from the OpenRouter path documented above:
`GradusIQ_career/supabase_client.py` builds a session-scoped client for the
`/api/v2/student/me/*` routes, against the applied schema in
`supabase/migrations/`. It reads none of the variables listed here — see the
Vercel and Render blocks under "Secure demo deployment" for the two pairs it
does need.

© 2026 GradusIQ. All rights reserved. Unauthorized copying, modification, or distribution of this software, in whole or in part, is prohibited.

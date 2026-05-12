# ORCA

**ORCA** (Operational Response & Channel Analytics) is an internal operations tool for Slack-backed support analytics, optional RAG question answering, and controlled multi-channel broadcast.

This repository supports two deployment personalities:

- **Internal mode** — live Slack APIs, embeddings ingest, RAG answers, real broadcasts. Requires secrets via environment variables (see `.env.example`).
- **Demo mode** — set `DEMO_MODE=true` to serve **synthetic** analytics and **simulate** ingest, ask, and broadcast with **no external side effects**.

## Features

- **Analytics** — first-response and follow-up response metrics, peak-time heatmaps, API traffic patterns, endpoint mix (from the same sampled window as Slack analytics when not in demo mode).
- **ORCA Copilot** — short narrative insight block on top of analytics + insights.
- **API traffic patterns** — daily call trend and “spike / drop-off / steady” style hints (demo data illustrates each pattern per channel).
- **Broadcast** — multi-channel send with confirmation; in demo mode the send is simulated and always succeeds.

## Architecture

| Layer | Stack |
|-------|--------|
| API | **Python 3**, **FastAPI**, **Uvicorn** |
| UI | **Static HTML/CSS/JS** served from `/ui` (no React build step in-repo) |
| Data (demo) | `data/demo_dataset.py`, `data/demo_companies.py` |
| UI I/O | `ui/dataProvider.js` (all `fetch` calls); optional TypeScript mirror `data/dataProvider.ts` for contracts / future tooling |

## Configuration

Copy `.env.example` to `.env` for local development. **Never commit `.env`.**

- **`DEMO_MODE`**: when `true`, the server never calls Slack for analytics/insights, never runs RAG for `/ask`, and never posts broadcasts; the UI shows the **Demo Environment** banner when this mode is active.
- **`PORT`**: listen port for Uvicorn (default `8000` in Docker; sample Compose maps host `3000` → container `8000`).

## Demo deployment

Use this for **Lightsail**, laptops, or any host with Docker. Demo mode uses **synthetic** analytics and **simulated** ingest, ask, and broadcast — **no real Slack writes** and **no RAG / external LLM calls** for `/ask`.

### Local Docker

1. Ensure Docker Compose is installed.
2. From the repo root, create `.env` if you do not already have one:

   ```bash
   bash scripts/ensure-docker-env.sh
   ```

   By default this copies `.env.example` (includes `DEMO_MODE=true` and `PORT=8000`). On **public demo** servers use a **minimal** `.env` (only those two lines) so you never inject production Slack/OpenAI keys into the container. Edit `.env` for internal mode (secrets + `DEMO_MODE=false`).

3. Build and run:

   ```bash
   docker compose config
   docker compose up -d --build
   docker compose logs -f
   ```

4. Open the UI: **`http://localhost:3000/ui/`**

5. Healthcheck: **`http://localhost:3000/health`** — expect `{"status":"ok","demoMode":true}` when demo is enabled.

6. Optional automated checks (requires `curl`; uses `BASE_URL`, default `http://127.0.0.1:3000`):

   ```bash
   bash scripts/validate-demo-deployment.sh
   ```

### Manual demo checklist

- Header shows **Demo Environment — identifiers masked, data simulated** when `demoMode` is true.
- **`GET /health`** returns `"status":"ok"` and correct `demoMode`.
- **Broadcast** confirm flow completes with a simulated success line (see API `message` field).
- **Channel labels** in Analytics / Broadcast use masked names where configured (`makeba-support` → `client-a-support`, etc.).
- **Analytics** loads without Slack (synthetic bundle).

### Internal / live mode

Unchanged: set **`DEMO_MODE=false`** or remove it in `.env`, provide Slack/OpenAI variables per `.env.example`, and run the same stack — the app uses live Slack and real writes again.

## Run locally

### Python (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit secrets for internal mode
export DEMO_MODE=true       # omit for internal Slack mode
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open **`http://127.0.0.1:8000/ui/`**.

### npm convenience scripts

After Python dependencies are installed, you can start the API with:

```bash
npm run dev   # uvicorn reload on port 8000 (requires python3 + pip deps on PATH)
```

There are **no Node module dependencies** for the UI; `package.json` exists only for these helper scripts.

### Docker

```bash
bash scripts/ensure-docker-env.sh   # creates .env from .env.example if missing
docker compose up -d --build
```

Then open **`http://localhost:3000/ui/`** and **`http://localhost:3000/health`** (see `docker-compose.yml` port mapping `3000:8000`).

More detail: **`DEPLOYMENT.md`**.

## Identifier masking (demo UI)

When `DEMO_MODE` is on, the browser maps display-only labels (for example `makeba-support` → `client-a-support`, `nuvion-braid` → `client-b-support`) in **`ui/channelMask.js`**. API payloads are unchanged; only labels shown in the UI are aliased.

## License / ops

Add your org’s license and support contacts as needed.

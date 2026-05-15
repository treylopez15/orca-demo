# ORCA – Operational Response & Channel Analytics

🚀 **Live Demo:** [http://44.203.210.245:3000](http://44.203.210.245:3000)  
📦 **GitHub:** [github.com/treylopez15/orca-demo](https://github.com/treylopez15/orca-demo)

---

## 1. Overview

ORCA (Operational Response & Channel Analytics) is a lightweight analytics and assistant layer for Slack-based teams.

It helps teams:

- understand response performance across channels  
- identify peak activity and bottlenecks  
- query historical conversations using an AI-style interface  

This public demo runs in **demo mode**, using simulated data to safely showcase functionality without exposing real Slack data.

This project demonstrates end-to-end system design, including API development, frontend integration, analytics modeling, and cloud deployment.

### Demo data model

- **`data/mock_slack.txt`** — a **static, hand-authored Slack-style transcript** (multi-channel threads, realistic names and timestamps). It is **not** live Slack; it exists so demos stay repeatable and safe to share.
- **Search & Ask (demo)** — `POST /ask` and `POST /api/ask` in demo mode **read that file**, score lines against your question, then return an **analysis-style summary** in the form **“Based on Slack discussions in #channel, …”** — simulating grounded Q&A without embeddings or an external model.
- **Analytics / Copilot** in demo mode still use the separate **synthetic** numeric dataset in `data/demo_dataset.py` so charts always render; the mock file is for **conversational** answers only.

---

## 2. Live Demo

**Live app:** [http://44.203.210.245:3000](http://44.203.210.245:3000) — opens the ORCA UI (root redirects to `/ui/`).

### Demo Walkthrough

1. Open the app at the link above.  
2. Go to **Search & ingest** and click **Ingest Slack messages** (simulated in demo mode).  
3. Ask a question, for example:  
   - *“what is an api?”*  
   - *“what caused the wire rejection?”*  
4. Open **Analytics** to view response metrics, peak activity, API traffic patterns, and the Copilot summary.

### Suggested demo questions

These match the demo transcript and return substantive answers—good for a first run:

- *"what caused the wire failure?"*
- *"why was ACH delayed?"*
- *"are there any system issues?"*

**Also worth trying (about two minutes):**

- Confirm the header shows **Demo Environment — identifiers masked, data simulated** when demo mode is active.  
- **Broadcast** — select channels, compose a message, confirm; in demo mode nothing is posted to Slack.

---

## 3. Features

| Area | What it does |
|------|----------------|
| **Slack ingestion** | In **internal** mode, pulls thread history and builds embeddings for RAG. In **demo** mode, ingest is **mocked**—no Slack API calls for that action. |
| **Question answering** | In **internal** mode, `/ask` uses retrieval + LLM over indexed Slack text. In **demo** mode, use **Ask** to query a **mock Slack transcript** (`data/mock_slack.txt`) via keyword-style retrieval and summarization — simulates RAG safely without real data or external APIs. |
| **Analytics dashboard** | First- and follow-up **response times**, **peak message times** (heatmap-style), **API traffic** trends, top endpoints, and an **ORCA Copilot** insight strip. Demo mode uses a **deterministic synthetic dataset** so charts always populate. |
| **Broadcast** | Multi-channel message flow with **confirmation** before send. In demo mode, the send is **simulated** and returns success without posting to Slack. |

---

## 4. How to Use (UI Guide)

For someone opening the app for the first time:

1. **Open the app** — use the [live demo](http://44.203.210.245:3000) link at the top.  
2. **Search & ingest** — click **Ingest Slack messages**, then use **Ask** with a short question (see Demo Walkthrough for examples).  
3. **Broadcast** — pick channels, write a message, send, then **confirm** in the modal.  
4. **Analytics** — click **Refresh** if needed; use **Channel** and **Timezone** to explore KPIs, charts, traffic status, and Copilot.

---

## 5. Technical Architecture

- **FastAPI** backend for API and data handling  
- **Static frontend** (HTML / CSS / JS) for a lightweight UI — network calls are centralized in `ui/dataProvider.js`  
- **Dockerized** for consistent local and cloud deployment (`Dockerfile`, `docker-compose.yml`)  
- **Hosted on AWS Lightsail** for cost-efficient public access (host port **3000** → container **8000**)

**Data flow:** UI → FastAPI endpoints → (mocked Slack ingestion / analytics layer in demo, or live Slack + compute in internal mode) → structured JSON → rendered in the UI.

---

## 6. API Endpoints (selected)

| Method & path | Purpose |
|---------------|---------|
| **`POST /api/ingest`** | Demo-oriented ingest stub. Returns a fixed **success** payload with sample channel names and a fake indexed count. **Active when `DEMO_MODE=true`**; otherwise **404** so production stacks don’t depend on mock data. |
| **`POST /api/ask`** | JSON `{ "question": "..." }` → `{ "answer": "..." }`. **Demo-only.** Answers are built from **`data/mock_slack.txt`** (keyword retrieval + short summaries). **`POST /ask`** uses the same logic in demo mode for the web UI. |
| **`GET /health`** | Liveness probe: `{ "status": "ok", "demoMode": true|false }`. Safe for load balancers and scripts. |

Additional routes (broadcast, analytics, insights, roles, config, etc.) live in **`main.py`**; operators can see **`DEPLOYMENT.md`** for runbooks.

---

## 7. Running Locally

```bash
git clone https://github.com/treylopez15/orca-demo.git
cd orca-demo
printf '%s\n' 'DEMO_MODE=true' 'PORT=8000' > .env
docker compose up -d --build
```

Open:

- **App:** [http://localhost:3000/ui/](http://localhost:3000/ui/) (or [http://localhost:3000](http://localhost:3000))  
- **Health:** [http://localhost:3000/health](http://localhost:3000/health)

If `docker compose` is unavailable, try **`docker-compose`**. Ensure Docker is running before `up`.

---

## 8. Notes on Demo Mode

- **No real Slack data** for analytics, insights, ingest, ask, or broadcast when `DEMO_MODE=true`.  
- **Responses are simulated** or synthetic so reviewers always see a full UI.  
- **Safe for interviews and portfolio reviews** — no tokens or customer payloads; the UI can **mask** a few channel display names in demo.

For **production-style** use, set `DEMO_MODE=false`, add Slack and model credentials per **`.env.example`**, and deploy the same stack.

---

## 9. Why This Project

This project was built to demonstrate the ability to **design and deploy a complete, user-facing system** — from API design and data modeling to UI integration and cloud deployment.

It also reflects a focus on building **practical internal tools** that improve visibility, response efficiency, and operational insight for teams. The **demo mode** layer shows the same rigor applied to **safe public demos** without maintaining a separate codebase.

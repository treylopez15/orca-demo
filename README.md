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

This demo runs on a **controlled dataset** designed to reflect real Slack workflows while keeping the environment **consistent and reproducible across runs**.

This project demonstrates end-to-end system design, including API development, frontend integration, analytics modeling, and cloud deployment.

### Demo data model

ORCA uses a **structured Slack-style dataset** (`data/mock_slack.txt`) representing multi-channel conversations across payments, engineering, and operations.

The Ask functionality performs **keyword-based retrieval and synthesis** over this dataset, mirroring how a production system **queries and summarizes** Slack conversations.

**Analytics** are derived from indexed conversation activity and interaction patterns within the dataset, allowing the dashboard to reflect **realistic response behavior** and **team activity trends**.

---

## 2. Live Demo

**Live app:** [http://44.203.210.245:3000](http://44.203.210.245:3000) — opens the ORCA UI (root redirects to `/ui/`).

### Demo Walkthrough

1. Open the app at the link above.  
2. Go to **Search & ingest** and click **Ingest Slack messages** (runs the controlled ingest path; no live Slack calls are made in this configuration).  
3. Ask a question, for example:  
   - *“what is an api?”*  
   - *“what caused the wire rejection?”*  
4. Open **Analytics** to view response metrics, peak activity, API traffic patterns, and the Copilot summary.

### Suggested demo questions

These prompts align with the **controlled transcript** and return substantive answers on a first run:

- *"what caused the wire failure?"*
- *"why was ACH delayed?"*
- *"are there any system issues?"*

**Also worth trying (about two minutes):**

- Confirm the header shows **Demo Environment — identifiers masked** when browsing the hosted instance.  
- **Broadcast** — select channels, compose a message, confirm; in this deployment the confirm step completes **without outbound Slack writes**.

---

## 3. Features

| Area | What it does |
|------|----------------|
| **Slack ingestion** | In **internal** mode, pulls thread history and builds embeddings for RAG. With **`DEMO_MODE=true`**, ingestion returns a **deterministic success response** without calling the Slack API. |
| **Question answering** | In **internal** mode, `/ask` uses retrieval + LLM over indexed Slack text. In the **controlled deployment**, Ask runs **keyword retrieval and synthesis** over `data/mock_slack.txt`—the same retrieval-and-summarize shape as production RAG, backed by representative conversation text. |
| **Analytics dashboard** | First- and follow-up **response times**, **peak message times** (heatmap-style), **API traffic** trends, top endpoints, and an **ORCA Copilot** insight strip—driven by **indexed conversation-derived metrics** and structured patterns so KPIs mirror realistic team activity. |
| **Broadcast** | Multi-channel message flow with **confirmation** before send. With **`DEMO_MODE=true`**, the action completes locally **without posting** to Slack. |

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

**Data flow:** UI → FastAPI endpoints → (controlled dataset + analytics layer when `DEMO_MODE=true`, or **live Slack** + compute when `DEMO_MODE=false`) → structured JSON → rendered in the UI.

---

## 6. API Endpoints (selected)

| Method & path | Purpose |
|---------------|---------|
| **`POST /api/ingest`** | Returns a structured **success** payload with representative channel labels and indexed counts. **`DEMO_MODE=true` only**; otherwise **404** so production installs do not depend on this stub. |
| **`POST /api/ask`** | JSON `{ "question": "..." }` → `{ "answer": "..." }`. **`DEMO_MODE=true` only.** Answers are assembled from **`data/mock_slack.txt`** via retrieval and summarization. **`POST /ask`** follows the same path for the web UI in that configuration. |
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

With **`DEMO_MODE=true`**, ORCA operates entirely against the **bundled controlled dataset** and in-process endpoints: Slack APIs and outbound writes are not invoked for Ask, ingest, analytics refresh, or broadcast.

To run against a **live Slack workspace** with real ingestion, RAG, and broadcast, set **`DEMO_MODE=false`** and configure Slack and model credentials per **`.env.example`**. The application surface stays the same; only the backing data plane changes.

---

## 9. Why This Project

This project was built to demonstrate the ability to **design and deploy a complete, user-facing system** — from API design and data modeling to UI integration and cloud deployment.

It also reflects a focus on building **practical internal tools** that improve visibility, response efficiency, and operational insight for teams. **One codebase** supports both Slack-backed operation and **this controlled deployment** so demonstrations stay repeatable without a forked UI or API layer.

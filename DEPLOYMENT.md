# ORCA deployment (Docker / AWS Lightsail)

ORCA ships as a **FastAPI** application with a static browser UI. For public demos, set **`DEMO_MODE=true`** in `.env` so Slack, RAG, and real broadcasts are **not** used for those routes.

## Quick start (Docker)

1. Install [Docker](https://docs.docker.com/get-docker/) and Docker Compose on the host.
2. Clone this repository on the server.
3. From the repo root, ensure `.env` exists (Compose loads it at **runtime** via `env_file`; it is **not** copied into the image — see **`.dockerignore`**):

   ```bash
   bash scripts/ensure-docker-env.sh
   ```

   This copies **`.env.example`** → **`.env`** only when `.env` is missing. The example includes **`DEMO_MODE=true`** and **`PORT=8000`**. On shared or public demo hosts, prefer a **minimal** `.env` (only those two variables) so production secrets are never loaded into the container.

4. Validate compose and start:

   ```bash
   docker compose config
   docker compose up -d --build
   docker compose logs -f
   ```

5. Open the app at **`http://<host>:3000/ui/`** (Compose maps host **3000** → container **8000**).

6. Healthcheck: **`http://<host>:3000/health`** — JSON `{"status":"ok","demoMode":...}`.

7. Optional: **`bash scripts/validate-demo-deployment.sh`** (defaults to `BASE_URL=http://127.0.0.1:3000`).

To stop:

```bash
docker compose down
```

## Demo vs internal

| Mode | `DEMO_MODE` | Behavior |
|------|-------------|------------|
| Public demo | `true` | Synthetic analytics/insights, simulated ingest/ask/broadcast, **no Slack API** for those paths. |
| Internal | `false` or unset | Full Slack ingestion, RAG `/ask`, live broadcast — requires secrets in `.env` (see `.env.example`). |

## AWS Lightsail (Ubuntu)

1. Create an **Ubuntu** Lightsail instance (512 MB+ is enough for demo traffic).
2. In the Lightsail **Networking** tab, add a firewall rule: **TCP 3000** (or your chosen host port).
3. SSH into the instance:

   ```bash
   ssh ubuntu@<lightsail-public-ip>
   ```

4. Install Docker, Compose plugin, and Git:

   ```bash
   sudo apt update
   sudo apt install -y docker.io docker-compose-plugin git
   sudo usermod -aG docker "$USER"
   ```

   Log out and back in so the `docker` group applies (or use `sudo docker` for the session).

5. Clone the repo (replace with your URL):

   ```bash
   git clone https://github.com/your-org/slack_rag_bot.git
   cd slack_rag_bot
   ```

6. Create `.env` for demo (public hosts: **only** these two lines so secrets are not passed into the container):

   ```bash
   printf '%s\n' 'DEMO_MODE=true' 'PORT=8000' > .env
   ```

   Or run **`bash scripts/ensure-docker-env.sh`** to copy from **`.env.example`** when `.env` is missing.

   **Security:** `docker compose` reads `.env` at runtime. Do **not** bake a file with production API keys into a public image; keep a **minimal** `.env` on demo VMs. The **`.dockerignore`** excludes `.env` from the **build context** so secrets are not copied into image layers by `COPY . .`

7. Start the stack:

   ```bash
   docker compose up -d --build
   ```

8. Open:

   - App: **`http://<lightsail-public-ip>:3000/ui/`**
   - Health: **`http://<lightsail-public-ip>:3000/health`**

For HTTPS or a custom domain, add **Lightsail load balancing** or a small reverse proxy (Caddy / nginx) in front and terminate TLS there.

## Dockerfile (reference)

- Base: **`python:3.12-slim`**
- Installs **`requirements.txt`**
- **`EXPOSE 8000`**
- Runs **`uvicorn main:app`** on host `0.0.0.0` and port **`${PORT:-8000}`**

## Environment

- **`PORT`**: port **inside** the container (default **8000**). Sample Compose maps **`3000:8000`**.
- **`DEMO_MODE`**: `true` / `1` / `yes` enables demo-safe behavior (case-insensitive).

Internal deployments: copy **`.env.example`** → **`.env`**, fill Slack and OpenAI variables, set **`DEMO_MODE=false`**.

## Local Python (no Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEMO_MODE=true
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Then open **`http://127.0.0.1:8000/ui/`** and **`http://127.0.0.1:8000/health`**.

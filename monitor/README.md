# Honcho Memory Monitor

A read-only web GUI for inspecting a running Honcho deployment. It connects
directly to the Postgres database over a **read-only** connection (every
connection opens with `default_transaction_read_only=on`, so Postgres itself
rejects any accidental write) and surfaces what the public API hides: the
`(observer, observed)` collections and their conclusions, the deriver queue,
and vector sync state.

## Views

- **Dashboard** — global counts, per-workspace table, queue-by-task breakdown, vector sync health.
- **Workspace** — drill into a workspace's peers and sessions.
- **Peer** — the memory pairs (collections) a peer observes or is observed by.
- **Collection** — the conclusions (documents) of a `(observer, observed)` pair, filterable by `explicit` / `deductive` / `inductive`.
- **Session** — full message timeline with pagination.
- **Queue & Deriver** — pending/failed items by task type, active work units, oldest backlog age.
- **Embeddings** — `sync_state` breakdown for `message_embeddings` and `documents`.
- **Search** — full-text search across messages and conclusions.

## Run

Via Docker Compose (adds the `monitor` service alongside the API/deriver):

```bash
docker compose up -d --build monitor
# open http://localhost:8080
```

Standalone (needs a reachable Postgres):

```bash
pip install -r requirements.txt
MONITOR_DB_CONNECTION_URI=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres \
  uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Configuration is one env var:

| Variable | Default | Description |
| --- | --- | --- |
| `MONITOR_DB_CONNECTION_URI` | `postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres` | SQLAlchemy URL for the Honcho database |

The connection is forced read-only via the `default_transaction_read_only=on`
server option regardless of the credentials supplied.

## Structure

```
monitor/
├── Dockerfile          # python:3.13-slim + uvicorn
├── requirements.txt
├── app/
│   ├── main.py         # FastAPI app + read-only SQL endpoints
│   └── db.py           # read-only SQLAlchemy engine
└── static/             # vendored Tailwind + Alpine, SPA (no build step)
    ├── index.html
    ├── app.js
    ├── style.css
    ├── tailwind.js     # vendored Tailwind Play CDN (offline-safe)
    └── alpine.js       # vendored Alpine.js
```

import datetime
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .db import engine

app = FastAPI(title="Honcho Memory Monitor", docs_url="/api/docs", openapi_url="/api/openapi.json")

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


def run(sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def run_one(sql: str, **params: Any) -> dict[str, Any] | None:
    rows = run(sql, **params)
    return rows[0] if rows else None


def ensure_workspace(name: str) -> None:
    if not run_one("SELECT 1 FROM workspaces WHERE name = :name", name=name):
        raise HTTPException(status_code=404, detail=f"workspace '{name}' not found")


def ensure_peer(ws: str, peer: str) -> None:
    if not run_one(
        "SELECT 1 FROM peers WHERE workspace_name = :ws AND name = :peer",
        ws=ws,
        peer=peer,
    ):
        raise HTTPException(status_code=404, detail=f"peer '{peer}' not found")


def ensure_session(ws: str, session: str) -> None:
    if not run_one(
        "SELECT 1 FROM sessions WHERE workspace_name = :ws AND name = :session",
        ws=ws,
        session=session,
    ):
        raise HTTPException(status_code=404, detail=f"session '{session}' not found")


def ensure_collection(ws: str, observer: str, observed: str) -> None:
    if not run_one(
        "SELECT 1 FROM collections WHERE workspace_name = :ws AND observer = :observer AND observed = :observed",
        ws=ws,
        observer=observer,
        observed=observed,
    ):
        raise HTTPException(status_code=404, detail="collection not found")


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with engine.connect():
            return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    totals = run_one(
        """
        SELECT
          (SELECT count(*) FROM workspaces) AS workspaces,
          (SELECT count(*) FROM peers) AS peers,
          (SELECT count(*) FROM sessions) AS sessions,
          (SELECT count(*) FROM sessions WHERE is_active) AS active_sessions,
          (SELECT count(*) FROM messages) AS messages,
          (SELECT coalesce(sum(token_count), 0)::bigint FROM messages) AS tokens,
          (SELECT count(*) FROM collections) AS collections,
          (SELECT count(*) FROM documents WHERE deleted_at IS NULL) AS conclusions,
          (SELECT count(*) FROM queue WHERE NOT processed) AS queue_pending,
          (SELECT count(*) FROM queue WHERE processed AND error IS NOT NULL) AS queue_failed
        """
    )
    sync = run(
        """
        SELECT kind, sync_state, count(*)::bigint AS count
        FROM (
          SELECT 'message' AS kind, sync_state FROM message_embeddings
          UNION ALL
          SELECT 'document' AS kind, sync_state FROM documents WHERE deleted_at IS NULL
        ) s
        GROUP BY kind, sync_state
        ORDER BY kind, sync_state
        """
    )
    queue = run(
        """
        SELECT task_type,
          count(*) FILTER (WHERE NOT processed) AS pending,
          count(*) FILTER (WHERE processed) AS processed,
          count(*) FILTER (WHERE processed AND error IS NOT NULL) AS failed,
          count(*) AS total
        FROM queue
        GROUP BY task_type
        ORDER BY pending DESC, task_type
        """
    )
    workspaces = run(
        """
        SELECT w.name,
          w.created_at,
          (SELECT count(*) FROM peers p WHERE p.workspace_name = w.name) AS peers,
          (SELECT count(*) FROM sessions s WHERE s.workspace_name = w.name) AS sessions,
          (SELECT count(*) FROM messages m WHERE m.workspace_name = w.name) AS messages,
          (SELECT coalesce(sum(m.token_count), 0)::bigint FROM messages m
             WHERE m.workspace_name = w.name) AS tokens,
          (SELECT count(*) FROM collections c WHERE c.workspace_name = w.name) AS collections,
          (SELECT count(*) FROM documents d WHERE d.workspace_name = w.name AND d.deleted_at IS NULL)
            AS conclusions
        FROM workspaces w
        ORDER BY w.created_at
        """
    )
    return {
        "totals": totals,
        "sync": sync,
        "queue": queue,
        "workspaces": workspaces,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/api/workspaces")
def workspaces() -> list[dict[str, Any]]:
    return run(
        """
        SELECT w.id, w.name, w.created_at,
          (SELECT count(*) FROM peers p WHERE p.workspace_name = w.name) AS peers,
          (SELECT count(*) FROM sessions s WHERE s.workspace_name = w.name) AS sessions,
          (SELECT count(*) FROM messages m WHERE m.workspace_name = w.name) AS messages,
          (SELECT count(*) FROM collections c WHERE c.workspace_name = w.name) AS collections,
          (SELECT count(*) FROM documents d WHERE d.workspace_name = w.name AND d.deleted_at IS NULL)
            AS conclusions
        FROM workspaces w
        ORDER BY w.created_at
        """
    )


@app.get("/api/workspaces/{name}")
def workspace_detail(name: str) -> dict[str, Any]:
    ensure_workspace(name)
    detail = run_one(
        """
        SELECT w.id, w.name, w.created_at, w.metadata, w.configuration,
          (SELECT count(*) FROM peers p WHERE p.workspace_name = w.name) AS peers,
          (SELECT count(*) FROM sessions s WHERE s.workspace_name = w.name) AS sessions,
          (SELECT count(*) FROM sessions s WHERE s.workspace_name = w.name AND s.is_active) AS active_sessions,
          (SELECT count(*) FROM messages m WHERE m.workspace_name = w.name) AS messages,
          (SELECT coalesce(sum(m.token_count), 0)::bigint FROM messages m
             WHERE m.workspace_name = w.name) AS tokens,
          (SELECT count(*) FROM collections c WHERE c.workspace_name = w.name) AS collections,
          (SELECT count(*) FROM documents d WHERE d.workspace_name = w.name AND d.deleted_at IS NULL)
            AS conclusions
        FROM workspaces w
        WHERE w.name = :name
        """,
        name=name,
    )
    return {"workspace": detail}


@app.get("/api/workspaces/{name}/peers")
def peers(name: str, q: str = "", limit: int = Query(200, ge=1, le=1000)) -> list[dict[str, Any]]:
    ensure_workspace(name)
    where = "p.workspace_name = :ws"
    if q:
        where += " AND (p.name ILIKE :q OR p.id ILIKE :q)"
    return run(
        f"""
        SELECT p.id, p.name, p.created_at, p.metadata, p.configuration,
          (SELECT count(*) FROM messages m WHERE m.peer_name = p.name AND m.workspace_name = p.workspace_name)
            AS message_count,
          (SELECT max(m.created_at) FROM messages m
             WHERE m.peer_name = p.name AND m.workspace_name = p.workspace_name) AS last_message_at,
          (SELECT count(*) FROM collections c WHERE c.workspace_name = p.workspace_name
             AND (c.observer = p.name OR c.observed = p.name)) AS collection_count
        FROM peers p
        WHERE {where}
        ORDER BY p.created_at DESC
        LIMIT :limit
        """,
        ws=name,
        q=f"%{q}%" if q else "",
        limit=limit,
    )


@app.get("/api/workspaces/{name}/sessions")
def sessions(
    name: str, q: str = "", limit: int = Query(100, ge=1, le=1000)
) -> list[dict[str, Any]]:
    ensure_workspace(name)
    where = "s.workspace_name = :ws"
    if q:
        where += " AND (s.name ILIKE :q OR s.id ILIKE :q)"
    return run(
        f"""
        SELECT s.id, s.name, s.is_active, s.created_at, s.metadata, s.configuration,
          (SELECT count(*) FROM messages m WHERE m.session_name = s.name AND m.workspace_name = s.workspace_name)
            AS message_count,
          (SELECT max(m.created_at) FROM messages m
             WHERE m.session_name = s.name AND m.workspace_name = s.workspace_name) AS last_message_at,
          (SELECT count(*) FROM session_peers sp WHERE sp.session_name = s.name AND sp.workspace_name = s.workspace_name)
            AS peer_count
        FROM sessions s
        WHERE {where}
        ORDER BY s.created_at DESC
        LIMIT :limit
        """,
        ws=name,
        q=f"%{q}%" if q else "",
        limit=limit,
    )


@app.get("/api/workspaces/{name}/sessions/{session}/messages")
def session_messages(
    name: str, session: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    ensure_workspace(name)
    ensure_session(name, session)
    sess = run_one(
        "SELECT name, is_active, created_at FROM sessions WHERE workspace_name = :ws AND name = :session",
        ws=name,
        session=session,
    )
    total = run_one(
        "SELECT count(*) AS n FROM messages WHERE workspace_name = :ws AND session_name = :session",
        ws=name,
        session=session,
    )["n"]
    rows = run(
        """
        SELECT m.id, m.public_id, m.seq_in_session, m.content, m.peer_name, m.token_count,
               m.created_at, m.metadata, m.internal_metadata
        FROM messages m
        WHERE m.workspace_name = :ws AND m.session_name = :session
        ORDER BY m.seq_in_session
        LIMIT :limit OFFSET :offset
        """,
        ws=name,
        session=session,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "is_active": sess["is_active"],
        "created_at": sess["created_at"],
        "messages": rows,
    }


@app.get("/api/workspaces/{name}/memories")
def workspace_memories(name: str) -> dict[str, Any]:
    ensure_workspace(name)
    rows = run(
        """
        SELECT p.id, p.name, p.created_at, p.internal_metadata,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = p.workspace_name AND d.observed = p.name
               AND d.deleted_at IS NULL) AS conclusions_about,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = p.workspace_name AND d.observer = p.name
               AND d.deleted_at IS NULL) AS conclusions_by,
          (SELECT count(*) FROM collections c
             WHERE c.workspace_name = p.workspace_name
               AND (c.observer = p.name OR c.observed = p.name)) AS collections,
          (SELECT count(*) FROM messages m
             WHERE m.workspace_name = p.workspace_name AND m.peer_name = p.name) AS message_count,
          (SELECT max(m.created_at) FROM messages m
             WHERE m.workspace_name = p.workspace_name AND m.peer_name = p.name) AS last_message_at
        FROM peers p
        WHERE p.workspace_name = :ws
        ORDER BY p.created_at DESC
        """,
        ws=name,
    )
    metas = {
        p["name"]: (p["internal_metadata"] or {})
        for p in run("SELECT name, internal_metadata FROM peers WHERE workspace_name = :ws", ws=name)
    }
    peers = []
    for r in rows:
        meta = r.pop("internal_metadata") or {}
        r["self_card"] = meta.get("peer_card")
        cards_about = []
        for observer, om in metas.items():
            if observer == r["name"]:
                continue
            card = om.get(f"{r['name']}_peer_card")
            if card:
                cards_about.append({"observer": observer, "card": card})
        r["cards_about"] = cards_about
        peers.append(r)
    return {"workspace": name, "peers": peers}


@app.get("/api/workspaces/{name}/graph")
def workspace_graph(
    name: str,
    mode: str = Query("collections", pattern="^(collections|conclusions)$"),
    limit: int = Query(150, ge=1, le=1000),
) -> dict[str, Any]:
    """Cytoscape-style elements for the memory graph of a workspace.

    mode=collections (default): peer nodes joined by weighted memory edges.
    mode=conclusions: each conclusion becomes a node, connected observer →
    conclusion → observed.
    """
    ensure_workspace(name)
    peers = run(
        """
        SELECT p.id, p.name, p.created_at, p.internal_metadata,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = p.workspace_name AND d.observed = p.name
               AND d.deleted_at IS NULL) AS conclusions_about,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = p.workspace_name AND d.observer = p.name
               AND d.deleted_at IS NULL) AS conclusions_by,
          (SELECT count(*) FROM messages m
             WHERE m.workspace_name = p.workspace_name AND m.peer_name = p.name) AS message_count,
          (SELECT count(*) FROM session_peers sp
             WHERE sp.workspace_name = p.workspace_name AND sp.peer_name = p.name) AS session_count
        FROM peers p
        WHERE p.workspace_name = :ws
        """,
        ws=name,
    )
    collections = run(
        """
        SELECT c.observer, c.observed,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = c.workspace_name AND d.observer = c.observer
               AND d.observed = c.observed AND d.deleted_at IS NULL) AS docs,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = c.workspace_name AND d.observer = c.observer
               AND d.observed = c.observed AND d.deleted_at IS NULL AND d.level = 'explicit') AS explicit,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = c.workspace_name AND d.observer = c.observer
               AND d.observed = c.observed AND d.deleted_at IS NULL
               AND d.level IN ('deductive', 'inductive')) AS inferred
        FROM collections c
        WHERE c.workspace_name = :ws
        """,
        ws=name,
    )
    elements: list[dict[str, Any]] = []
    for p in peers:
        meta = p.pop("internal_metadata") or {}
        card = meta.get("peer_card") or []
        elements.append(
            {
                "data": {
                    "id": f"peer:{p['name']}",
                    "kind": "peer",
                    "name": p["name"],
                    "peer_id": p["id"],
                    "conclusions_about": p["conclusions_about"],
                    "conclusions_by": p["conclusions_by"],
                    "message_count": p["message_count"],
                    "session_count": p["session_count"],
                    "card_len": len(card),
                    "created_at": p["created_at"],
                }
            }
        )
    for c in collections:
        explicit = c["explicit"]
        inferred = c["inferred"]
        source = f"peer:{c['observer']}"
        target = f"peer:{c['observed']}"
        if explicit:
            elements.append(
                {
                    "data": {
                        "id": f"exp:{c['observer']}->{c['observed']}",
                        "source": source,
                        "target": target,
                        "kind": "memory",
                        "mtype": "explicit",
                        "label": f"{explicit}",
                        "docs": explicit,
                        "explicit": explicit,
                        "inferred": inferred,
                    }
                }
            )
        if inferred:
            elements.append(
                {
                    "data": {
                        "id": f"inf:{c['observer']}->{c['observed']}",
                        "source": source,
                        "target": target,
                        "kind": "memory",
                        "mtype": "inferred",
                        "label": f"{inferred}",
                        "docs": inferred,
                        "explicit": explicit,
                        "inferred": inferred,
                    }
                }
            )
    if mode == "conclusions":
        docs = run(
            """
            SELECT d.id, d.observer, d.observed, d.level, d.created_at,
                   d.content, d.source_ids
            FROM documents d
            WHERE d.workspace_name = :ws AND d.deleted_at IS NULL
            ORDER BY d.created_at DESC
            LIMIT :limit
            """,
            ws=name,
            limit=limit,
        )
        con_elements: list[dict[str, Any]] = []
        for d in docs:
            cid = f"con:{d['id']}"
            con_elements.append(
                {
                    "data": {
                        "id": cid,
                        "kind": "conclusion",
                        "level": d["level"],
                        "content": d["content"],
                        "observer": d["observer"],
                        "observed": d["observed"],
                        "created_at": d["created_at"],
                        "label": (d["content"] or "").strip().replace("\n", " ")[:40],
                    }
                }
            )
            con_elements.append(
                {
                    "data": {
                        "id": f"hold:{d['id']}",
                        "source": f"peer:{d['observer']}",
                        "target": cid,
                        "kind": "claim",
                        "mtype": d["level"],
                    }
                }
            )
            con_elements.append(
                {
                    "data": {
                        "id": f"about:{d['id']}",
                        "source": cid,
                        "target": f"peer:{d['observed']}",
                        "kind": "about",
                        "mtype": d["level"],
                    }
                }
            )
        return {
            "workspace": name,
            "mode": "conclusions",
            "elements": [
                e for e in elements if e["data"].get("kind") != "memory"
            ] + con_elements,
            "peer_count": len(peers),
            "conclusion_count": len(docs),
        }
    return {
        "workspace": name,
        "mode": "collections",
        "elements": elements,
        "peer_count": len(peers),
        "edge_count": len(collections),
    }


@app.get("/api/workspaces/{name}/peers/{peer}/collections")
def peer_collections(name: str, peer: str) -> dict[str, Any]:
    ensure_workspace(name)
    ensure_peer(name, peer)
    peer_row = run_one(
        "SELECT id, created_at, internal_metadata FROM peers WHERE workspace_name = :ws AND name = :peer",
        ws=name,
        peer=peer,
    )
    meta = peer_row["internal_metadata"] or {}
    self_card = meta.get("peer_card")
    cards_about = []
    for o in run(
        "SELECT name, internal_metadata FROM peers WHERE workspace_name = :ws AND name != :peer",
        ws=name,
        peer=peer,
    ):
        card = (o["internal_metadata"] or {}).get(f"{peer}_peer_card")
        if card:
            cards_about.append({"observer": o["name"], "card": card})
    collections = run(
        """
        SELECT c.id, c.observer, c.observed, c.created_at, c.metadata,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = c.workspace_name AND d.observer = c.observer
               AND d.observed = c.observed AND d.deleted_at IS NULL) AS total_docs,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = c.workspace_name AND d.observer = c.observer
               AND d.observed = c.observed AND d.deleted_at IS NULL AND d.level = 'explicit')
            AS explicit_docs,
          (SELECT count(*) FROM documents d
             WHERE d.workspace_name = c.workspace_name AND d.observer = c.observer
               AND d.observed = c.observed AND d.deleted_at IS NULL AND d.level IN ('deductive', 'inductive'))
            AS inferred_docs
        FROM collections c
        WHERE c.workspace_name = :ws AND (c.observer = :peer OR c.observed = :peer)
        ORDER BY c.created_at DESC
        """,
        ws=name,
        peer=peer,
    )
    return {
        "peer": peer,
        "peer_id": peer_row["id"],
        "created_at": peer_row["created_at"],
        "self_card": self_card,
        "cards_about": cards_about,
        "collections": collections,
    }


@app.get("/api/workspaces/{name}/collections/{observer}/{observed}/documents")
def collection_documents(
    name: str,
    observer: str,
    observed: str,
    level: str | None = Query(None, pattern="^(explicit|deductive|inductive)$"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    ensure_workspace(name)
    ensure_collection(name, observer, observed)
    where = "d.workspace_name = :ws AND d.observer = :observer AND d.observed = :observed AND d.deleted_at IS NULL"
    params: dict[str, Any] = {"ws": name, "observer": observer, "observed": observed}
    if level:
        where += " AND d.level = :level"
        params["level"] = level
    total = run_one(f"SELECT count(*) AS n FROM documents d WHERE {where}", **params)["n"]
    rows = run(
        f"""
        SELECT d.id, d.content, d.level, d.times_derived, d.created_at, d.source_ids,
               d.session_name, d.sync_state, d.internal_metadata
        FROM documents d
        WHERE {where}
        ORDER BY d.created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        **params,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "documents": rows}


@app.get("/api/queue")
def queue() -> dict[str, Any]:
    by_type = run(
        """
        SELECT task_type,
          count(*) FILTER (WHERE NOT processed) AS pending,
          count(*) FILTER (WHERE processed) AS processed,
          count(*) FILTER (WHERE processed AND error IS NOT NULL) AS failed,
          count(*) AS total
        FROM queue
        GROUP BY task_type
        ORDER BY task_type
        """
    )
    pending = run(
        """
        SELECT id, task_type, workspace_name, work_unit_key, session_id, message_id,
               created_at, error
        FROM queue
        WHERE NOT processed
        ORDER BY created_at DESC
        LIMIT 200
        """
    )
    failed = run(
        """
        SELECT id, task_type, workspace_name, work_unit_key, session_id, message_id,
               created_at, error
        FROM queue
        WHERE processed AND error IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 200
        """
    )
    oldest_pending = run_one(
        """
        SELECT id, task_type, workspace_name, created_at,
               EXTRACT(EPOCH FROM (now() - created_at))::bigint AS age_seconds
        FROM queue
        WHERE NOT processed
        ORDER BY created_at
        LIMIT 1
        """
    )
    active = run_one("SELECT count(*) AS n FROM active_queue_sessions")
    return {
        "by_type": by_type,
        "pending": pending,
        "failed": failed,
        "oldest_pending": oldest_pending,
        "active_queue_sessions": active["n"],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/api/embeddings")
def embeddings() -> dict[str, Any]:
    message_sync = run(
        """
        SELECT sync_state, count(*)::bigint AS count,
               min(created_at) AS oldest, max(last_sync_at) AS last_sync
        FROM message_embeddings
        GROUP BY sync_state
        ORDER BY sync_state
        """
    )
    document_sync = run(
        """
        SELECT sync_state, count(*)::bigint AS count,
               min(created_at) AS oldest, max(last_sync_at) AS last_sync
        FROM documents
        WHERE deleted_at IS NULL
        GROUP BY sync_state
        ORDER BY sync_state
        """
    )
    return {
        "message_embeddings": message_sync,
        "documents": document_sync,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1),
    workspace: str | None = None,
    kind: str = Query("messages", pattern="^(messages|conclusions|all)$"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    ws_cond = " AND workspace_name = :ws" if workspace else ""
    ws = workspace
    results: dict[str, Any] = {"query": q, "workspace": workspace, "kind": kind}
    if kind in ("messages", "all"):
        results["messages"] = run(
            f"""
            SELECT m.public_id AS id, m.content, m.peer_name, m.session_name, m.workspace_name,
                   m.created_at, m.token_count,
                   ts_rank(to_tsvector('english', m.content), websearch_to_tsquery('english', :q)) AS rank
            FROM messages m
            WHERE to_tsvector('english', m.content) @@ websearch_to_tsquery('english', :q)
              {ws_cond}
            ORDER BY rank DESC, m.created_at DESC
            LIMIT :limit
            """,
            q=q,
            ws=ws,
            limit=limit,
        )
    if kind in ("conclusions", "all"):
        results["conclusions"] = run(
            f"""
            SELECT d.id, d.content, d.level, d.observer, d.observed, d.session_name,
                   d.workspace_name, d.created_at, d.source_ids, d.times_derived,
                   ts_rank(to_tsvector('english', d.content), websearch_to_tsquery('english', :q)) AS rank
            FROM documents d
            WHERE d.deleted_at IS NULL
              AND to_tsvector('english', d.content) @@ websearch_to_tsquery('english', :q)
              {ws_cond}
            ORDER BY rank DESC, d.created_at DESC
            LIMIT :limit
            """,
            q=q,
            ws=ws,
            limit=limit,
        )
    return results


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

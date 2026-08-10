function monitor() {
  return {
    route: [],
    loading: false,
    error: "",
    healthOk: false,
    healthLoading: true,

    overview: null,
    ws: null,
    wsTab: "peers",
    peers: [],
    sessions: [],

    collections: null,
    collectionDocs: null,
    level: "all",
    expandDoc: null,

    memories: [],

    graphData: null,
    graphInfo: null,
    graphSel: null,
    graphMode: "collections",

    sessionMsgs: null,
    sessionActive: true,
    pageSize: 100,

    queueData: null,
    embData: null,

    search: { q: "", kind: "all", workspace: "" },
    searchWorkspaces: [],
    searchResults: null,

    wsName: "",

    init() {
      this.parseRoute();
      this.checkHealth();
      this.load();
      window.addEventListener("hashchange", () => {
        this.parseRoute();
        this.load();
      });
      this.healthTimer = setInterval(() => this.checkHealth(), 15000);
    },

    parseRoute() {
      const h = location.hash.replace(/^#\/?/, "");
      this.route = h ? h.split("/").filter(Boolean) : [];
    },

    nav(path) {
      location.hash = path;
    },

    async api(path, opts) {
      const res = await fetch(path, opts);
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const body = await res.json();
          if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        } catch (_) {}
        throw new Error(`${res.status} ${detail}`);
      }
      return res.json();
    },

    async checkHealth() {
      this.healthLoading = true;
      try {
        const h = await this.api("/api/health");
        this.healthOk = h.status === "ok";
      } catch (_) {
        this.healthOk = false;
      } finally {
        this.healthLoading = false;
      }
    },

    async load() {
      this.loading = true;
      this.error = "";
      this.expandDoc = null;
      try {
        const r = this.route;
        if (!r.length) {
          await this.loadOverview();
        } else if (r[0] === "ws") {
          const name = r[1];
          this.wsName = name;
          if (r[2] === "peer") {
            await this.loadPeerCollections(name, r[3]);
          } else if (r[2] === "session") {
            await this.loadSession(name, r[3]);
          } else if (r[2] === "collection") {
            this.colObserver = r[3];
            this.colObserved = r[4];
            this.level = "all";
            await this.loadCollection("all");
          } else {
            await this.loadWorkspace(name);
          }
        } else if (r[0] === "queue") {
          await this.loadQueue();
        } else if (r[0] === "embeddings") {
          await this.loadEmbeddings();
        } else if (r[0] === "search") {
          await this.loadSearchWorkspaces();
        }
      } catch (e) {
        this.error = e.message || String(e);
      } finally {
        this.loading = false;
      }
    },

    async loadOverview() {
      this.overview = await this.api("/api/overview");
      if (this.overview) this.checkHealth();
    },

    async loadWorkspace(name) {
      const data = await this.api(`/api/workspaces/${encodeURIComponent(name)}`);
      this.ws = data.workspace;
      this.wsTab = "peers";
      await this.loadPeers("");
    },

    async loadPeers(q) {
      this.peers = await this.api(
        `/api/workspaces/${encodeURIComponent(this.ws.name)}/peers` +
          (q ? `?q=${encodeURIComponent(q)}` : "")
      );
    },

    async loadSessions(q) {
      this.sessions = await this.api(
        `/api/workspaces/${encodeURIComponent(this.ws.name)}/sessions` +
          (q ? `?q=${encodeURIComponent(q)}` : "")
      );
    },

    async loadPeerCollections(ws, peer) {
      this.collections = await this.api(
        `/api/workspaces/${encodeURIComponent(ws)}/peers/${encodeURIComponent(peer)}/collections`
      );
    },

    async loadMemories() {
      const data = await this.api(
        `/api/workspaces/${encodeURIComponent(this.ws.name)}/memories`
      );
      this.memories = data.peers || [];
    },

    async loadGraph() {
      const data = await this.api(
        `/api/workspaces/${encodeURIComponent(this.ws.name)}/graph?mode=${this.graphMode}`
      );
      this.graphData = data;
      this.graphInfo = {
        mode: data.mode,
        peers: data.peer_count,
        edges: data.edge_count,
        conclusions: data.conclusion_count,
        explicit_edges: (data.elements || []).filter((e) => e.data && e.data.mtype === "explicit").length,
        inferred_edges: (data.elements || []).filter((e) => e.data && e.data.mtype === "inferred").length,
      };
      this.$nextTick(() => this.renderGraph());
    },

    switchGraphMode(mode) {
      this.graphMode = mode;
      this.graphSel = null;
      this.loadGraph();
    },

    renderGraph() {
      const el = document.getElementById("memory-graph");
      if (!el || !this.graphData) return;
      if (this.cy) {
        this.cy.destroy();
        this.cy = null;
      }
      const cy = (this.cy = cytoscape({
        container: el,
        elements: this.graphData.elements,
        style: [
          {
            selector: 'node[kind = "peer"]',
            style: {
              "background-color": "#0d1522",
              "border-width": 2.5,
              "border-color": "#35c6d9",
              label: "data(name)",
              "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
              "font-size": 11,
              "font-weight": "600",
              color: "#35c6d9",
              "text-valign": "center",
              "text-halign": "center",
              width: "mapData(conclusions_about, 0, 100, 48, 80)",
              height: "mapData(conclusions_about, 0, 100, 48, 80)",
            },
          },
          {
            selector: 'node[kind = "conclusion"]',
            style: {
              shape: "diamond",
              "background-color": "#1e293b",
              "border-width": 2,
              "border-color": "#64748b",
              width: 22,
              height: 22,
            },
          },
          {
            selector: 'node[kind = "conclusion"]:selected',
            style: {
              label: "data(label)",
              "font-size": 9,
              "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
              color: "#cbd5e1",
              "text-valign": "bottom",
              "text-margin-y": 4,
              "text-max-width": 160,
              "text-wrap": "wrap",
            },
          },
          {
            selector: 'node[kind = "conclusion"][level = "explicit"]',
            style: {
              "border-color": "#35c6d9",
              "background-color": "rgba(53, 198, 217, 0.12)",
            },
          },
          {
            selector: 'node[kind = "conclusion"][level = "deductive"]',
            style: {
              "border-color": "#a78bfa",
              "background-color": "rgba(167, 139, 250, 0.12)",
            },
          },
          {
            selector: 'node[kind = "conclusion"][level = "inductive"]',
            style: {
              "border-color": "#f5b75a",
              "background-color": "rgba(245, 183, 90, 0.12)",
            },
          },
          {
            selector: "edge",
            style: {
              width: "mapData(docs, 0, 100, 2, 5)",
              "curve-style": "bezier",
              "target-arrow-shape": "triangle",
              "arrow-scale": 1.1,
              label: "data(label)",
              "font-size": 10,
              "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
              "font-weight": "600",
              "text-background-color": "#070b10",
              "text-background-opacity": 0.9,
              "text-background-padding": 4,
              "text-rotation": "autorotate",
            },
          },
          {
            selector: 'edge[mtype = "explicit"]',
            style: {
              "line-color": "rgba(53, 198, 217, 0.6)",
              "target-arrow-color": "#35c6d9",
              color: "#35c6d9",
            },
          },
          {
            selector: 'edge[mtype = "inferred"]',
            style: {
              "line-color": "rgba(167, 139, 250, 0.6)",
              "target-arrow-color": "#a78bfa",
              color: "#a78bfa",
            },
          },
          {
            selector: 'edge[kind = "claim"]',
            style: {
              width: 1,
              "line-color": "rgba(148, 163, 184, 0.35)",
              "target-arrow-color": "rgba(148, 163, 184, 0.45)",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.8,
            },
          },
          {
            selector: 'edge[kind = "about"]',
            style: {
              width: 1,
              "line-color": "rgba(148, 163, 184, 0.25)",
              "target-arrow-color": "rgba(148, 163, 184, 0.35)",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.8,
            },
          },
          {
            selector: "edge:selected",
            style: {
              "line-color": "#f5b75a",
              "target-arrow-color": "#f5b75a",
              color: "#f5b75a",
              width: 6,
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 4,
              "border-color": "#f5b75a",
              "background-color": "#1b2536",
            },
          },
        ],
        layout: {
          name: "cose",
          animate: true,
          animationDuration: 600,
          nodeRepulsion: () => 12000,
          idealEdgeLength: () => 140,
          gravity: 0.35,
          padding: 50,
        },
        minZoom: 0.3,
        maxZoom: 3,
        wheelSensitivity: 0.2,
      }));

      cy.on("tap", "node", (evt) => {
        const d = evt.target.data();
        if (d.kind === "peer") {
          this.graphSel = {
            kind: "peer",
            name: d.name,
            id: d.peer_id,
            about: d.conclusions_about,
            by: d.conclusions_by,
          };
        } else if (d.kind === "conclusion") {
          this.graphSel = {
            kind: "conclusion",
            id: d.id,
            level: d.level,
            content: d.content,
            observer: d.observer,
            observed: d.observed,
            created_at: d.created_at,
          };
        }
      });
      cy.on("tap", "edge", (evt) => {
        const d = evt.target.data();
        if (d.kind === "memory") {
          this.graphSel = {
            kind: "memory",
            mtype: d.mtype,
            observer: d.source.replace("peer:", ""),
            observed: d.target.replace("peer:", ""),
            docs: d.explicit + d.inferred,
            explicit: d.explicit,
            inferred: d.inferred,
          };
        }
      });
      cy.on("tap", (evt) => {
        if (evt.target === cy) this.graphSel = null;
      });
    },

    graphSelectPeer(name) {
      this.nav(`/ws/${encodeURIComponent(this.ws.name)}/peer/${encodeURIComponent(name)}`);
    },

    async loadCollection(level) {
      this.level = level || "all";
      const lvl = level === "all" ? "" : `&level=${level}`;
      this.collectionDocs = await this.api(
        `/api/workspaces/${encodeURIComponent(this.wsName)}/collections/${encodeURIComponent(
          this.colObserver
        )}/${encodeURIComponent(this.colObserved)}/documents?limit=500${lvl}`
      );
    },

    async loadSession(ws, session) {
      this.sessionOffset = 0;
      const data = await this.api(
        `/api/workspaces/${encodeURIComponent(ws)}/sessions/${encodeURIComponent(session)}/messages?limit=${this.pageSize}&offset=0`
      );
      data.session = session;
      this.sessionMsgs = data;
      this.sessionActive = data.is_active;
    },

    async sessionPage(dir) {
      const next = Math.max(0, this.sessionMsgs.offset + dir * this.pageSize);
      const data = await this.api(
        `/api/workspaces/${encodeURIComponent(this.wsName)}/sessions/${encodeURIComponent(
          this.sessionMsgs.session
        )}/messages?limit=${this.pageSize}&offset=${next}`
      );
      data.session = this.sessionMsgs.session;
      this.sessionMsgs = data;
      this.sessionActive = data.is_active;
    },

    async loadQueue() {
      this.queueData = await this.api("/api/queue");
    },

    async loadEmbeddings() {
      this.embData = await this.api("/api/embeddings");
    },

    async loadSearchWorkspaces() {
      this.searchWorkspaces = await this.api("/api/workspaces");
    },

    async runSearch() {
      if (!this.search.q.trim()) return;
      this.searchResults = null;
      const params = new URLSearchParams({
        q: this.search.q.trim(),
        kind: this.search.kind,
      });
      if (this.search.workspace) params.set("workspace", this.search.workspace);
      this.searchResults = await this.api(`/api/search?${params.toString()}`);
    },

    // ---- derived helpers ----
    get statCards() {
      if (!this.overview) return [];
      const t = this.overview.totals;
      return [
        { label: "Workspaces", value: this.fmt(t.workspaces), hint: "root scopes", tone: "text-amber2" },
        { label: "Peers", value: this.fmt(t.peers), hint: "humans + agents", tone: "text-cyan2" },
        { label: "Sessions", value: this.fmt(t.sessions), hint: t.active_sessions + " active", tone: "text-slate-200" },
        { label: "Messages", value: this.fmt(t.messages), hint: "all history", tone: "text-slate-200" },
        { label: "Tokens", value: this.fmt(t.tokens), hint: "total usage", tone: "text-violet-300" },
        { label: "Conclusions", value: this.fmt(t.conclusions), hint: t.collections + " collections", tone: "text-amber2" },
        { label: "Queue pending", value: this.fmt(t.queue_pending), hint: "backlog", tone: t.queue_pending ? "text-amber2" : "text-emerald-400" },
        { label: "Queue failed", value: this.fmt(t.queue_failed), hint: "errors", tone: t.queue_failed ? "text-red-400" : "text-emerald-400" },
      ];
    },

    syncOf(kind) {
      if (!this.overview) return [];
      return this.overview.sync.filter((s) => s.kind === kind);
    },

    syncPct(kind, row) {
      const rows = this.syncOf(kind);
      const total = rows.reduce((a, b) => a + b.count, 0);
      return total ? Math.round((row.count / total) * 100) : 0;
    },

    get qPending() {
      return this.queueData ? this.queueData.by_type.reduce((a, b) => a + b.pending, 0) : 0;
    },

    get qFailed() {
      return this.queueData ? this.queueData.by_type.reduce((a, b) => a + b.failed, 0) : 0;
    },

    get oldestPendingAge() {
      const o = this.queueData && this.queueData.oldest_pending;
      if (!o || o.age_seconds == null) return "—";
      const s = o.age_seconds;
      if (s < 60) return s + "s";
      if (s < 3600) return Math.floor(s / 60) + "m";
      if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
      return Math.floor(s / 86400) + "d";
    },

    get oldestPendingTask() {
      const o = this.queueData && this.queueData.oldest_pending;
      return o ? `${o.task_type} · ws:${o.workspace_name || "—"}` : "";
    },

    // ---- formatters ----
    fmt(n) {
      if (n == null) return "0";
      return Number(n).toLocaleString("en-US");
    },

    time(iso) {
      if (!iso) return "—";
      const d = new Date(iso);
      if (isNaN(d)) return "—";
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    },

    json(obj) {
      try {
        return JSON.stringify(obj, null, 2);
      } catch (_) {
        return String(obj);
      }
    },

    initials(name) {
      if (!name) return "?";
      return name.slice(0, 2).toUpperCase();
    },

    isAgent(m) {
      const md = m.metadata || {};
      return md.is_agent === true || md.isAgent === true;
    },

    pct(a, b) {
      return b ? Math.round((a / b) * 100) : 0;
    },
  };
}

document.addEventListener("alpine:init", () => {
  Alpine.data("monitor", monitor);
});

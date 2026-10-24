"""SQLite persistence: catalog cache, knowledge base, alphas, and learning memory."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS operators (name TEXT PRIMARY KEY, raw TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS datasets (
  id TEXT, region TEXT, delay INTEGER, universe TEXT, name TEXT, description TEXT,
  category TEXT, subcategory TEXT, coverage REAL, field_count INTEGER, alpha_count INTEGER,
  user_count INTEGER, value_score REAL, themes TEXT, updated_at REAL,
  PRIMARY KEY (id, region, delay, universe));
CREATE TABLE IF NOT EXISTS fields (
  id TEXT, region TEXT, delay INTEGER, universe TEXT, dataset TEXT, category TEXT,
  subcategory TEXT, type TEXT, description TEXT, coverage REAL, date_coverage REAL,
  alpha_count INTEGER, user_count INTEGER, themes TEXT, updated_at REAL,
  PRIMARY KEY (id, region, delay, universe));
CREATE INDEX IF NOT EXISTS fields_by_dataset ON fields(dataset, region, delay, universe);
CREATE TABLE IF NOT EXISTS dataset_sync (
  dataset TEXT, region TEXT, delay INTEGER, universe TEXT, synced_at REAL, n INTEGER,
  PRIMARY KEY (dataset, region, delay, universe));
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, kind TEXT, title TEXT, source TEXT, text TEXT, meta TEXT, added_at REAL);
CREATE TABLE IF NOT EXISTS chunks (doc_id TEXT, idx INTEGER, text TEXT, PRIMARY KEY (doc_id, idx));
CREATE TABLE IF NOT EXISTS examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, expression TEXT, settings TEXT,
  UNIQUE (source, expression));
CREATE TABLE IF NOT EXISTS hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT, title TEXT, body TEXT,
  categories TEXT, keywords TEXT, created_at REAL, tries INTEGER DEFAULT 0,
  wins REAL DEFAULT 0, status TEXT DEFAULT 'new');
CREATE TABLE IF NOT EXISTS alphas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, payload_hash TEXT UNIQUE, canonical TEXT,
  expression TEXT, settings TEXT, hypothesis_id INTEGER, parent_id INTEGER, origin TEXT,
  model TEXT, theme TEXT, region TEXT, delay INTEGER, universe TEXT, fields TEXT,
  operators TEXT, categories TEXT, datasets TEXT, op_count INTEGER, pp_op_count INTEGER,
  description TEXT, rationale TEXT, status TEXT, issues TEXT, brain_id TEXT,
  sim_message TEXT, stats TEXT, checks TEXT, classifications TEXT, pp_status TEXT,
  pp_reasons TEXT, score REAL, created_at REAL, simulated_at REAL, shape TEXT, shape_class TEXT,
  route TEXT, reg_status TEXT, reg_reasons TEXT);
CREATE INDEX IF NOT EXISTS alphas_status ON alphas(status);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, model TEXT, purpose TEXT, ok INTEGER,
  reward REAL, error TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, latency REAL);
CREATE TABLE IF NOT EXISTS model_stats (
  model TEXT PRIMARY KEY, alpha REAL, beta REAL, calls INTEGER, failures INTEGER,
  last_error TEXT, last_used REAL);
CREATE TABLE IF NOT EXISTS issue_stats (
  code TEXT, subject TEXT, count INTEGER, last_seen REAL, PRIMARY KEY (code, subject));
"""

JSON_COLS = {"settings", "fields", "operators", "categories", "datasets", "issues", "stats", "checks",
             "classifications", "pp_reasons", "reg_reasons", "themes", "body", "keywords", "meta", "raw"}


def _dump(v):
    return json.dumps(v, default=str) if v is not None else None


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    out = dict(r)
    for k, v in out.items():
        if k in JSON_COLS and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return out


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Columns added after a database was created."""
        have = {r[1] for r in self.db.execute("PRAGMA table_info(alphas)").fetchall()}
        for col in ("shape", "shape_class", "route", "reg_status", "reg_reasons"):
            if col not in have:
                self.db.execute(f"ALTER TABLE alphas ADD COLUMN {col} TEXT")

    def close(self):
        self.db.close()

    def q(self, sql: str, args=()) -> list[dict]:
        return [_row(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        return _row(self.db.execute(sql, args).fetchone())

    # -- kv -------------------------------------------------------------------
    def kv_get(self, key: str, default=None, max_age_s: float | None = None):
        r = self.db.execute("SELECT value, updated_at FROM kv WHERE key=?", (key,)).fetchone()
        if r is None or (max_age_s is not None and time.time() - r["updated_at"] > max_age_s):
            return default
        return json.loads(r["value"])

    def kv_set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (key, _dump(value), time.time()))
        self.db.commit()

    # -- catalog --------------------------------------------------------------
    def upsert_operators(self, ops: list[dict]) -> None:
        now = time.time()
        self.db.execute("DELETE FROM operators")
        self.db.executemany("INSERT INTO operators VALUES (?,?,?)", [(o["name"], _dump(o), now) for o in ops])
        self.db.commit()

    def operators(self) -> list[dict]:
        return [json.loads(r["raw"]) for r in self.db.execute("SELECT raw FROM operators ORDER BY name")]

    def upsert_datasets(self, rows: list[dict], scope: dict) -> None:
        now = time.time()
        self.db.executemany(
            "INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(d["id"], scope["region"], scope["delay"], scope["universe"], d.get("name"), d.get("description"),
              (d.get("category") or {}).get("id"), (d.get("subcategory") or {}).get("id"), d.get("coverage"),
              d.get("fieldCount"), d.get("alphaCount"), d.get("userCount"), d.get("valueScore"),
              _dump(d.get("themes") or []), now) for d in rows])
        self.db.commit()

    def datasets(self, scope: dict, categories: set | None = None) -> list[dict]:
        rows = self.q("SELECT * FROM datasets WHERE region=? AND delay=? AND universe=? ORDER BY id",
                      (scope["region"], scope["delay"], scope["universe"]))
        return [r for r in rows if categories is None or r["category"] in categories]

    def upsert_fields(self, rows: list[dict], scope: dict) -> None:
        now = time.time()
        self.db.executemany(
            "INSERT OR REPLACE INTO fields VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(f["id"], scope["region"], scope["delay"], scope["universe"], (f.get("dataset") or {}).get("id"),
              (f.get("category") or {}).get("id"), (f.get("subcategory") or {}).get("id"), f.get("type"),
              f.get("description"), f.get("coverage"), f.get("dateCoverage"), f.get("alphaCount"),
              f.get("userCount"), _dump(f.get("themes") or []), now) for f in rows])
        self.db.commit()

    def fields(self, scope: dict, dataset: str | None = None) -> list[dict]:
        sql = "SELECT * FROM fields WHERE region=? AND delay=? AND universe=?"
        args = [scope["region"], scope["delay"], scope["universe"]]
        if dataset:
            sql += " AND dataset=?"
            args.append(dataset)
        return self.q(sql + " ORDER BY id", args)

    def field(self, field_id: str, scope: dict) -> dict | None:
        return self.one("SELECT * FROM fields WHERE id=? AND region=? AND delay=? AND universe=?",
                        (field_id, scope["region"], scope["delay"], scope["universe"]))

    def mark_dataset_synced(self, dataset: str, scope: dict, n: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO dataset_sync VALUES (?,?,?,?,?,?)",
                        (dataset, scope["region"], scope["delay"], scope["universe"], time.time(), n))
        self.db.commit()

    def dataset_synced_at(self, dataset: str, scope: dict) -> float | None:
        r = self.db.execute("SELECT synced_at FROM dataset_sync WHERE dataset=? AND region=? AND delay=? AND universe=?",
                            (dataset, scope["region"], scope["delay"], scope["universe"])).fetchone()
        return r["synced_at"] if r else None

    # -- knowledge ------------------------------------------------------------
    def add_document(self, doc_id: str, kind: str, title: str, source: str, text: str,
                     chunks: list[str], meta: dict | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?)",
                        (doc_id, kind, title, source, text, _dump(meta or {}), time.time()))
        self.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        self.db.executemany("INSERT INTO chunks VALUES (?,?,?)", [(doc_id, i, c) for i, c in enumerate(chunks)])
        self.db.commit()

    def documents(self, kind: str | None = None) -> list[dict]:
        if kind:
            return self.q("SELECT id, kind, title, source, meta, added_at FROM documents WHERE kind=? ORDER BY added_at", (kind,))
        return self.q("SELECT id, kind, title, source, meta, added_at FROM documents ORDER BY added_at")

    def document(self, doc_id: str) -> dict | None:
        return self.one("SELECT * FROM documents WHERE id=?", (doc_id,))

    def chunks(self, kind: str | None = None, doc_id: str | None = None) -> list[dict]:
        sql = "SELECT c.doc_id, c.idx, c.text, d.title, d.kind FROM chunks c JOIN documents d ON d.id=c.doc_id"
        conds, args = [], []
        if kind:
            conds.append("d.kind=?")
            args.append(kind)
        if doc_id:
            conds.append("c.doc_id=?")
            args.append(doc_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        return self.q(sql + " ORDER BY c.doc_id, c.idx", args)

    def add_example(self, source: str, expression: str, settings: dict | None) -> None:
        self.db.execute("INSERT OR IGNORE INTO examples (source, expression, settings) VALUES (?,?,?)",
                        (source, expression, _dump(settings or {})))
        self.db.commit()

    def examples(self) -> list[dict]:
        return self.q("SELECT * FROM examples ORDER BY id")

    # -- hypotheses -----------------------------------------------------------
    def add_hypothesis(self, paper_id: str, h: dict) -> int:
        cur = self.db.execute(
            "INSERT INTO hypotheses (paper_id, title, body, categories, keywords, created_at) VALUES (?,?,?,?,?,?)",
            (paper_id, h.get("title", "untitled"), _dump(h), _dump(h.get("candidate_categories") or []),
             _dump(h.get("keywords") or []), time.time()))
        self.db.commit()
        return cur.lastrowid

    def hypotheses(self, paper_id: str | None = None) -> list[dict]:
        if paper_id:
            return self.q("SELECT * FROM hypotheses WHERE paper_id=? ORDER BY id", (paper_id,))
        return self.q("SELECT * FROM hypotheses ORDER BY id")

    def hypothesis(self, hid: int) -> dict | None:
        return self.one("SELECT * FROM hypotheses WHERE id=?", (hid,))

    def bump_hypothesis(self, hid: int, tries: int = 0, wins: float = 0.0) -> None:
        self.db.execute("UPDATE hypotheses SET tries=tries+?, wins=wins+?, status='tried' WHERE id=?", (tries, wins, hid))
        self.db.commit()

    # -- alphas ---------------------------------------------------------------
    def add_alpha(self, row: dict) -> int | None:
        row = dict(row)
        row.setdefault("created_at", time.time())
        cols = list(row)
        vals = [_dump(row[c]) if c in JSON_COLS else row[c] for c in cols]
        try:
            cur = self.db.execute(f"INSERT INTO alphas ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        except sqlite3.IntegrityError:
            return None
        self.db.commit()
        return cur.lastrowid

    def update_alpha(self, aid: int, **cols) -> None:
        if not cols:
            return
        sets = ", ".join(f"{c}=?" for c in cols)
        vals = [_dump(v) if c in JSON_COLS else v for c, v in cols.items()]
        self.db.execute(f"UPDATE alphas SET {sets} WHERE id=?", vals + [aid])
        self.db.commit()

    def alpha(self, aid: int) -> dict | None:
        return self.one("SELECT * FROM alphas WHERE id=?", (aid,))

    def alpha_by_hash(self, payload_hash: str) -> dict | None:
        return self.one("SELECT * FROM alphas WHERE payload_hash=?", (payload_hash,))

    def alphas(self, status: str | None = None, limit: int | None = None, order: str = "id") -> list[dict]:
        sql = "SELECT * FROM alphas"
        args: list = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.q(sql, args)

    # -- llm accounting -------------------------------------------------------
    def record_llm_call(self, model: str, purpose: str, ok: bool, reward: float, error: str | None,
                        usage: dict | None, latency: float) -> None:
        usage = usage or {}
        self.db.execute(
            "INSERT INTO llm_calls (ts, day, model, purpose, ok, reward, error, prompt_tokens, completion_tokens, latency) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (time.time(), date.today().isoformat(), model, purpose, int(ok), reward, error,
             usage.get("prompt_tokens"), usage.get("completion_tokens"), latency))
        self.db.commit()

    def llm_calls_today(self) -> int:
        r = self.db.execute("SELECT COUNT(*) AS n FROM llm_calls WHERE day=?", (date.today().isoformat(),)).fetchone()
        return r["n"]

    def llm_calls_since(self, ts: float) -> int:
        return self.db.execute("SELECT COUNT(*) AS n FROM llm_calls WHERE ts>=?", (ts,)).fetchone()["n"]

    def model_stat(self, model: str) -> dict:
        r = self.one("SELECT * FROM model_stats WHERE model=?", (model,))
        return r or {"model": model, "alpha": 0.0, "beta": 0.0, "calls": 0, "failures": 0, "last_error": None}

    def update_model_stat(self, model: str, reward: float, error: str | None = None) -> None:
        s = self.model_stat(model)
        self.db.execute("INSERT OR REPLACE INTO model_stats VALUES (?,?,?,?,?,?,?)",
                        (model, s["alpha"] + reward, s["beta"] + (1 - reward), s["calls"] + 1,
                         s["failures"] + (1 if error else 0), error or s.get("last_error"), time.time()))
        self.db.commit()

    # -- issue memory ---------------------------------------------------------
    def record_issue(self, code: str, subject: str) -> None:
        self.db.execute("INSERT INTO issue_stats VALUES (?,?,1,?) ON CONFLICT(code, subject) "
                        "DO UPDATE SET count=count+1, last_seen=excluded.last_seen", (code, subject or "", time.time()))
        self.db.commit()

    def top_issues(self, n: int = 12, codes: tuple[str, ...] | None = None) -> list[dict]:
        if codes:
            marks = ",".join("?" * len(codes))
            return self.q(f"SELECT * FROM issue_stats WHERE code IN ({marks}) ORDER BY count DESC LIMIT ?", (*codes, n))
        return self.q("SELECT * FROM issue_stats ORDER BY count DESC LIMIT ?", (n,))

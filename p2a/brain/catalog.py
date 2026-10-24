"""Sync the live BRAIN catalog into the local store.

Everything the LLM is allowed to use comes from here: operators (+ their documentation
pages and official examples), the simulation settings schema, data categories,
datasets, data fields, and the BRAIN Learn pages.
"""
from __future__ import annotations

import time

from ..fastexpr import Catalog, FieldInfo, Rules
from ..store import Store
from ..util import chunk_text, console, html_to_text
from .client import BrainClient, BrainError

SCOPE_KEYS = ("instrumentType", "region", "delay", "universe")


def scope_params(scope: dict) -> dict:
    return {k: scope[k] for k in SCOPE_KEYS if k in scope}


def blocks_to_text(content, on_example=None) -> str:
    parts = []
    for b in content or []:
        t, v = b.get("type"), b.get("value")
        if t in ("TEXT", "HTML", "RAW_HTML") and isinstance(v, str):
            parts.append(html_to_text(v))
        elif t == "HEADING" and isinstance(v, dict):
            parts.append("## " + str(v.get("content", "")))
        elif t == "TABLE" and isinstance(v, dict):
            parts.append("\n".join(" | ".join(str(c) for c in row) for row in v.get("data", [])))
        elif t == "SIMULATION_EXAMPLE" and isinstance(v, dict):
            code = v.get("regular") or ""
            if code:
                parts.append(f"Example alpha: {code}")
                if on_example:
                    on_example(code, v.get("settings") or {})
        elif t == "EQUATION" and v:
            parts.append(str(v))
    return "\n\n".join(p for p in parts if p and p.strip())


def row_to_field(row: dict) -> FieldInfo:
    return FieldInfo(id=row["id"], type=(row.get("type") or "MATRIX").upper(), dataset=row.get("dataset"),
                     category=row.get("category"), coverage=row.get("coverage"),
                     description=row.get("description") or "")


class CatalogSync:
    def __init__(self, client: BrainClient | None, store: Store, cfg):
        self.client = client
        self.store = store
        self.cfg = cfg

    # -- operators ------------------------------------------------------------
    def sync_operators(self, with_docs: bool = True) -> int:
        ops = self.client.get_json("/operators")
        self.store.upsert_operators(ops)
        if with_docs:
            documented = [o for o in ops if o.get("documentation")]
            for i, op in enumerate(documented, 1):
                console.print(f"  operator docs {i}/{len(documented)}: {op['name']}", end="\r")
                try:
                    d = self.client.get_json(op["documentation"])
                except BrainError:
                    continue
                text = blocks_to_text(d.get("content"), on_example=lambda c, s, n=op["name"]: self.store.add_example(f"operator:{n}", c, s))
                if text:
                    self.store.add_document(f"op:{op['name']}", "operator_doc", op["name"], op["documentation"], text,
                                            chunk_text(text, size=1200))
            console.print()
        return len(ops)

    # -- settings / categories / datasets -------------------------------------
    def sync_settings(self) -> dict:
        r = self.client.request("OPTIONS", "/simulations")
        if r.status_code >= 400:
            raise BrainError(f"OPTIONS /simulations -> HTTP {r.status_code}", r)
        children = r.json()["actions"]["POST"]["settings"]["children"]
        self.store.kv_set("settings_options", children)
        return children

    def sync_categories(self) -> list:
        cats = self.client.get_json("/data-categories")
        self.store.kv_set("data_categories", cats)
        return cats

    def sync_datasets(self, scope: dict) -> int:
        rows = list(self.client.paginate("/data-sets", scope_params(scope)))
        self.store.upsert_datasets(rows, scope)
        return len(rows)

    # -- fields -----------------------------------------------------------------
    def ensure_fields(self, dataset_id: str, scope: dict, max_age_days: float = 14) -> int:
        ts = self.store.dataset_synced_at(dataset_id, scope)
        if ts and time.time() - ts < max_age_days * 86400:
            return 0
        if self.client is None:
            return 0
        rows = list(self.client.paginate("/data-fields", {**scope_params(scope), "dataset.id": dataset_id}))
        self.store.upsert_fields(rows, scope)
        self.store.mark_dataset_synced(dataset_id, scope, len(rows))
        return len(rows)

    def search_fields(self, query: str, scope: dict, dataset: str | None = None, limit: int = 50) -> list[dict]:
        if self.client is None:
            return []
        params = {**scope_params(scope), "search": query}
        if dataset:
            params["dataset.id"] = dataset
        try:
            rows = list(self.client.paginate("/data-fields", params, max_items=limit))
        except BrainError:
            return []
        self.store.upsert_fields(rows, scope)
        return rows

    def lookup_field(self, field_id: str, scope: dict) -> FieldInfo | None:
        cached = self.store.field(field_id, scope)
        if cached:
            return row_to_field(cached)
        if self.client is None:
            return None
        try:
            d = self.client.get_json(f"/data-fields/{field_id}")
        except BrainError:
            return None
        avail = [x for x in d.get("data") or [] if x.get("region") == scope["region"]
                 and int(x.get("delay", -1)) == int(scope["delay"])]
        if not avail:
            return None
        best = next((x for x in avail if x.get("universe") == scope["universe"]), avail[0])
        row = {"id": d["id"], "dataset": d.get("dataset"), "category": d.get("category"),
               "subcategory": d.get("subcategory"), "type": d.get("type"), "description": d.get("description"),
               "coverage": best.get("coverage"), "dateCoverage": best.get("dateCoverage"),
               "alphaCount": best.get("alphaCount"), "userCount": best.get("userCount"), "themes": best.get("themes")}
        self.store.upsert_fields([row], scope)
        # BRAIN may spell the id differently (case); return its canonical record and let the caller compare ids
        return row_to_field(self.store.field(d["id"], scope))

    # -- docs -------------------------------------------------------------------
    def sync_tutorials(self) -> int:
        tutorials = list(self.client.paginate("/tutorials", {}, page_size=50))
        n = 0
        pages = [(t, p) for t in tutorials for p in t.get("pages", [])]
        for i, (t, p) in enumerate(pages, 1):
            console.print(f"  learn pages {i}/{len(pages)}: {p['id'][:50]}", end="\r")
            try:
                d = self.client.get_json(f"/tutorial-pages/{p['id']}")
            except BrainError:
                continue
            text = blocks_to_text(d.get("content"), on_example=lambda c, s, pid=p["id"]: self.store.add_example(f"tutorial:{pid}", c, s))
            if text:
                self.store.add_document(f"doc:{p['id']}", "brain_doc", d.get("title") or p.get("title", p["id"]),
                                        f"/tutorial-pages/{p['id']}", text, chunk_text(text, size=1200),
                                        meta={"tutorial": t.get("title"), "category": t.get("category")})
                n += 1
        console.print()
        return n

    def sync_all(self, scope: dict, docs: bool = True, grouping_fields=()) -> dict:
        summary = {}
        console.print("[bold]Syncing BRAIN catalog[/bold]")
        summary["operators"] = self.sync_operators(with_docs=docs and self.cfg.get("brain.docs.sync_operator_docs", True))
        summary["settings"] = len(self.sync_settings())
        summary["categories"] = len(self.sync_categories())
        summary["datasets"] = self.sync_datasets(scope)
        for g in grouping_fields:
            self.lookup_field(g, scope)
        if docs and self.cfg.get("brain.docs.sync_tutorials", True):
            summary["learn_pages"] = self.sync_tutorials()
        self.store.kv_set(f"synced:{scope['region']}:{scope['delay']}:{scope['universe']}", time.time())
        return summary


def build_catalog(store: Store, scope: dict, rules: Rules, sync: CatalogSync | None = None) -> Catalog:
    """Catalog for the validator: synced operators + every cached field for the scope.

    Unknown identifiers are looked up live (GET /data-fields/{id}) when a client is available,
    so a correct field outside the shortlist is accepted while invented names are rejected.
    """
    ops = store.operators()
    if not ops:
        raise RuntimeError("operator catalog is empty - run `p2a sync` first")
    fields = [row_to_field(r) for r in store.fields(scope)]
    lookup = (lambda name: sync.lookup_field(name, scope)) if sync and sync.client else None
    return Catalog(ops, rules, fields, field_lookup=lookup)

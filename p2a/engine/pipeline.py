"""The Engine: wires catalog, knowledge, LLM, validator, simulator and memory together."""
from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path

from ..brain import BrainClient, CatalogSync, SimJob, Simulator, build_catalog
from ..config import Config, brain_credentials, openrouter_key
from ..fastexpr import Rules
from ..knowledge import ingest as ingest_sources
from ..llm import BudgetExhausted, LLMError, OpenRouter
from ..store import Store
from ..util import console, esc
from .context import Context
from .evaluator import evaluate
from .generator import Generator
from .hypotheses import extract_hypotheses
from .memory import Memory
from .refiner import Refiner
from .themes import ThemeSpec, active_themes, constraints_for, load_themes

PLATFORM_ALPHA_URL = "https://platform.worldquantbrain.com/alpha/{}"


def _same_scope(a: dict, b: dict) -> bool:
    return (a["region"], a["universe"], int(a["delay"])) == (b["region"], b["universe"], int(b["delay"]))


def _epoch(stamp) -> float | None:
    """Seconds since the epoch of a BRAIN timestamp such as 2026-10-20T10:11:12-04:00."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None

class Engine:
    def __init__(self, cfg: Config, offline: bool = False, interactive: bool = True):
        self.cfg = cfg
        self.store = Store(cfg.data_dir / "p2a.sqlite")
        self.client = None if offline else BrainClient(cfg, brain_credentials(), interactive)
        self.sync = CatalogSync(self.client, self.store, cfg)
        self.llm = OpenRouter(cfg, self.store, openrouter_key())
        self.rules = Rules.from_config(cfg.section("fastexpr"))
        self.memory = Memory(self.store, cfg)
        self._sim: Simulator | None = None
        self._catalogs: dict = {}

    # -- scope / theme / context ------------------------------------------------------------
    def scope(self, region: str | None = None, universe: str | None = None, delay: int | None = None) -> dict:
        t = self.cfg.section("target")
        s = {"instrumentType": t.get("instrumentType", "EQUITY"), "region": region or t.get("region", "USA"),
             "universe": universe or t.get("universe", "TOP3000"),
             "delay": int(delay if delay is not None else t.get("delay", 1))}
        if region and not universe:
            # another region without a universe: the target's universe may not exist there (CHN has TOP2000U, DEU
            # TOP500, ...), so take the region's first universe from BRAIN's settings options
            from ..brain.settings import allowed_values
            opts = self.store.kv_get("settings_options") or {}
            allowed = allowed_values(opts, "universe", s) if opts else None
            if allowed and s["universe"] not in allowed:
                s["universe"] = allowed[0]
        return s

    def themes(self, scope: dict) -> list[ThemeSpec]:
        return load_themes(self.cfg, self.store, scope)

    def resolve_theme(self, scope: dict, name: str | None = None, use_theme: bool = True) -> ThemeSpec | None:
        if not use_theme:
            return None
        specs = self.themes(scope)
        if name:
            for s in specs:
                if s.name.lower() == name.lower() or name.lower() in s.name.lower():
                    return s
            raise ValueError(f"theme '{name}' not found; known: {[s.name for s in specs]}")
        active = active_themes(specs)
        ok = [s for s in active if not s.scope_problems(scope)]
        if ok:
            return ok[0]
        if active:
            console.print("[yellow]Active Power Pool themes do not fit this scope:[/yellow]")
            for s in active:
                console.print(f"  {s.name}: {'; '.join(s.scope_problems(scope))}")
        else:
            console.print("[yellow]No active Power Pool theme found (config.yaml themes / API tags).[/yellow]")
        return None

    def context(self, scope: dict, theme: ThemeSpec | None, route: str = "power_pool") -> Context:
        key = (scope["region"], scope["delay"], scope["universe"])
        if key not in self._catalogs:
            self._catalogs[key] = build_catalog(self.store, scope, self.rules, self.sync if self.client else None)
        pp = self.cfg.section("power_pool")
        if route == "regular":
            # production alphas: no theme, any data category; only the simplicity limits of the regular section
            rc = self.cfg.section("regular")
            theme = None
            constraints = constraints_for(None, {"max_operators": rc.get("max_operators"),
                                                 "max_unique_fields": rc.get("max_fields"),
                                                 # BRAIN's regular operatorCount counts every operator, ts_backfill
                                                 # included (#771: 59 by BRAIN, 49 with the Power Pool exclusions)
                                                 "excluded_operators": rc.get("excluded_operators") or [],
                                                 "grouping_fields": pp.get("grouping_fields")})
            constraints.label = "regular"
        elif pp.get("enabled", True):
            constraints = constraints_for(theme, pp)
        else:
            constraints = constraints_for(theme, {}) if theme else None
        return Context(cfg=self.cfg, store=self.store, llm=self.llm, sync=self.sync, memory=self.memory,
                       rules=self.rules, scope=scope, theme=theme, constraints=constraints,
                       catalog=self._catalogs[key], options=self.store.kv_get("settings_options") or {}, route=route)

    def regular_scope(self, region: str | None = None, universe: str | None = None, delay: int | None = None) -> dict:
        """The scope regular alphas are built in: `regular.universe` (auto = the universe an observed multiplier
        theme of this region and delay names, e.g. a TOP1000 theme; else the target universe)."""
        from ..brain.settings import allowed_values
        from .routes import theme_universe
        scope = self.scope(region, universe, delay)
        want = universe or self.cfg.get("regular.universe", "target")
        if want and want not in ("auto", "target"):
            scope["universe"] = want
        if want != "auto":
            return scope
        opts = self.store.kv_get("settings_options") or {}
        allowed = allowed_values(opts, "universe", {**self.cfg.section("default_settings"), **scope}) if opts else None
        u, t = theme_universe(self.store, scope, allowed, float(self.cfg.get("regular.theme_max_age_days", 3)))
        if u:
            scope["universe"] = u
            console.print(f"  regular route: universe {u} ({t['name']}, multiplier x{t['multiplier']:g})")
        return scope

    @property
    def simulator(self) -> Simulator:
        if self._sim is None:
            if self.client is None:
                raise RuntimeError("offline mode: simulations need the BRAIN API")
            self.client.ensure_auth()
            self._sim = Simulator(self.client, self.cfg)
        return self._sim

    def needs_sync(self, scope: dict) -> bool:
        return not self.store.operators() or not self.store.datasets(scope)

    # -- catalog + knowledge -----------------------------------------------------------------------
    def sync_catalog(self, scope: dict, docs: bool = True) -> dict:
        self.client.ensure_auth()
        grouping = self.cfg.get("power_pool.grouping_fields", [])
        summary = self.sync.sync_all(scope, docs=docs, grouping_fields=grouping)
        self._catalogs.clear()
        return summary

    def ingest(self, sources: list[str], extract: bool = True) -> list[str]:
        ids = ingest_sources(sources, self.store)
        if extract:
            for pid in ids:
                try:
                    extract_hypotheses(self.store, self.llm, self.cfg, pid)
                except BudgetExhausted as e:
                    console.print(f"[yellow]{esc(str(e))}. Run `p2a hypotheses --extract {pid}` later.[/yellow]")
                    break
                except LLMError as e:
                    console.print(f"[red]hypothesis extraction failed for {pid}: {esc(str(e))}[/red]")
        return ids

    # -- generation ------------------------------------------------------------------------------
    def generate(self, scope: dict, theme: ThemeSpec | None, hypothesis_ids: list[int] | None = None,
                 n_hypotheses: int = 2, per_call: int | None = None, route: str = "power_pool") -> list[int]:
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        hyps = self.memory.pick_hypotheses(n_hypotheses, ids=hypothesis_ids)
        if not hyps:
            console.print("[yellow]No hypotheses yet: `p2a ingest <paper>` first.[/yellow]")
            return []
        new_ids = []
        for h in hyps:
            console.rule(esc(f"hypothesis #{h['id']}: {h['title'][:80]}"))
            try:
                cands = gen.generate(h, per_call)
            except BudgetExhausted as e:
                console.print(f"[yellow]{esc(str(e))}[/yellow]")
                break
            except LLMError as e:
                console.print(f"[red]  generation failed: {esc(str(e))}[/red]")
                continue
            res = gen.save(cands, h["id"])
            new_ids += res["ids"]
            self.store.bump_hypothesis(h["id"])
            console.print(f"  saved {res['valid']} valid, {res['invalid']} invalid, {res['duplicate']} duplicate, "
                          f"{res['skipped']} skipped (same fields)")
            for c in cands:
                mark = ("[yellow]SKP[/yellow]" if c.skip else "[green]OK [/green]") if c.ok else "[red]BAD[/red]"
                console.print(f"   {mark} ({c.analysis.pp_op_count()} ops) {esc(c.analysis.canonical or c.expression)}")
                if not c.ok:
                    for iss in c.analysis.errors[:3]:
                        console.print(f"        [dim]{esc(iss.render())}[/dim]")
        return new_ids

    def explore(self, scope: dict, theme: ThemeSpec | None, n: int | None = None, category: str | None = None,
                route: str = "power_pool") -> list[int]:
        """Queue one probe per untried field of the most valuable, least crowded datasets (the theme's datasets on
        the Power Pool route, every category on the regular route)."""
        from .explorer import Explorer
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        try:
            cands = Explorer(ctx, gen, simulator=self.simulator if self.client else None).run(n, category)
        except BudgetExhausted as e:
            console.print(f"[yellow]{esc(str(e))}[/yellow]")
            return []
        ids = []
        for c in cands:
            res = gen.save([c], None)
            ids += res["ids"]
            mark = "[green]OK [/green]" if c.ok else "[red]BAD[/red]"
            console.print(f"   {mark} {esc(c.analysis.canonical or c.expression)}")
        console.print(f"  {len(ids)} probe(s) queued")
        return ids

    def shape_step(self, scope: dict, theme: ThemeSpec | None, n: int | None = None, route: str = "power_pool") -> list[int]:
        """Queue the next research shapes for fields that have shown signal."""
        from .shaper import ShapeExplorer
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        cands = ShapeExplorer(ctx, gen, simulator=self.simulator if self.client else None).run(n)
        ids = []
        for c in cands:
            res = gen.save([c], c.raw.get("hypothesis_id"))
            ids += res["ids"]
            mark = ("[yellow]SKP[/yellow]" if c.skip else "[green]OK [/green]") if c.ok else "[red]BAD[/red]"
            console.print(f"   {mark} {c.raw.get('shape'):18} {esc(c.analysis.canonical or c.expression)}")
            if not c.ok:
                for iss in c.analysis.errors[:2]:
                    console.print(f"        [dim]{esc(iss.render())}[/dim]")
        console.print(f"  {len(ids)} shape candidate(s) queued")
        return ids

    def combine(self, scope: dict, theme: ThemeSpec | None, n: int | None = None, route: str = "regular",
                origin: str | None = None) -> list[int]:
        """Queue combinations of weakly correlated, economically linked signals whose daily-PnL estimate clears the
        route's Sharpe bar (see combiner.py)."""
        from .combiner import Combiner
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        cands = Combiner(ctx, gen, simulator=self.simulator if self.client else None).run(n, origin)
        ids = []
        for c in cands:
            res = gen.save([c], None)
            ids += res["ids"]
            mark = ("[yellow]SKP[/yellow]" if c.skip else "[green]OK [/green]") if c.ok else "[red]BAD[/red]"
            console.print(f"   {mark} ({c.analysis.pp_op_count()} ops) {esc(c.analysis.canonical or c.expression)}")
            for iss in (c.analysis.errors if not c.ok else [])[:2]:
                console.print(f"        [dim]{esc(iss.render())}[/dim]")
            if c.skip:
                console.print(f"        [dim]{esc(c.skip)}[/dim]")
        console.print(f"  {len(ids)} combination(s) queued")
        return ids

    def _queue(self, gen, cands, label: str) -> list[int]:
        ids = []
        for c in cands:
            res = gen.save([c], c.raw.get("hypothesis_id"))
            ids += res["ids"]
            mark = ("[yellow]SKP[/yellow]" if c.skip else "[green]OK [/green]") if c.ok else "[red]BAD[/red]"
            console.print(f"   {mark} {str(c.raw.get('shape') or ''):24} {esc(c.analysis.canonical or c.expression)}")
            for iss in (c.analysis.errors if not c.ok else [])[:2]:
                console.print(f"        [dim]{esc(iss.render())}[/dim]")
            if c.skip:
                console.print(f"        [dim]{esc(c.skip)}[/dim]")
        console.print(f"  {len(ids)} {label} queued")
        return ids

    def mechanisms(self, scope: dict, theme: ThemeSpec | None, n: int | None = None, route: str = "regular",
                   only: list[str] | None = None) -> list[int]:
        """Queue research mechanisms (residual reversal, news-conditioned reversal, overnight tone, connected-firm
        momentum, ...) filled from the live catalog (mechanisms.py, research/mechanisms.yaml)."""
        from .mechanisms import MechanismBuilder
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        cands = MechanismBuilder(ctx, gen, simulator=self.simulator if self.client else None).run(n, only)
        return self._queue(gen, cands, "mechanism candidate(s)")

    def enhance(self, scope: dict, theme: ThemeSpec | None, ids: list[int] | None = None, n: int | None = None,
                route: str = "regular", only: list[str] | None = None) -> list[int]:
        """Apply research enhancers (volatility scaling, double neutralization, turnover targeting) to alphas that
        already work: the given ids, or the strongest unsubmitted alphas of this route."""
        from .lifecycle import Lifecycle, row_family
        from .mechanisms import MechanismBuilder
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        if ids:
            rows = [r for r in (self.store.alpha(i) for i in ids) if r and r.get("canonical")]
        else:
            min_s = float(self.cfg.get("mechanisms.enhance_min_sharpe", 1.4))
            fams = Lifecycle(ctx, simulator=self.simulator if self.client else None).families()
            rows = []
            for r in self.store.q("SELECT * FROM alphas WHERE status='simulated' AND brain_id IS NOT NULL "
                                  "AND (origin IS NULL OR origin NOT LIKE 'enhance:%') ORDER BY score DESC"):
                if ((r.get("stats") or {}).get("sharpe") or 0) < min_s or r.get("pp_status") == "suspect":
                    continue
                f = fams.get(row_family(ctx, r))
                if f is not None and f.state == "used":
                    continue
                rows.append(r)
                if len(rows) >= int(n or self.cfg.get("mechanisms.enhance_per_step", 4)):
                    break
        cands = MechanismBuilder(ctx, gen, simulator=self.simulator if self.client else None).enhance(rows, only)
        return self._queue(gen, cands, "enhanced variant(s)")

    def try_candidates(self, scope: dict, theme: ThemeSpec | None, raws: list[dict], route: str = "power_pool") -> list[int]:
        """Hand-written candidates go through the same validation, settings policy and description checks as
        LLM output (raw keys: expression, neutralization, decay, truncation, idea, rationale_data,
        rationale_operators, hypothesis_id)."""
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        ids = []
        for raw in raws:
            c = gen.check(raw, origin="manual")
            hyp = raw.get("hypothesis_id")
            res = gen.save([c], int(hyp) if hyp else None)
            mark = ("[yellow]SKP[/yellow]" if c.skip else "[green]OK [/green]") if c.ok else "[red]BAD[/red]"
            console.print(f"   {mark} ({c.analysis.pp_op_count()} ops) {esc(c.analysis.canonical or c.expression)}")
            for iss in (c.analysis.errors if not c.ok else [])[:3]:
                console.print(f"        [dim]{esc(iss.render())}[/dim]")
            if c.skip:
                console.print(f"        [dim]{esc(c.skip)}[/dim]")
            if res["duplicate"]:
                console.print("        [dim]already in the database with these settings[/dim]")
            ids += res["ids"]
        return ids

    def refine(self, scope: dict, theme: ThemeSpec | None, limit: int | None = None, use_llm: bool = True,
               ids: list[int] | None = None, route: str = "power_pool") -> list[int]:
        ctx = self.context(scope, theme, route)
        gen = Generator(ctx)
        try:
            cands = Refiner(ctx, gen, simulator=self.simulator if self.client else None).run(limit, use_llm=use_llm, ids=ids)
        except BudgetExhausted as e:
            console.print(f"[yellow]{esc(str(e))}[/yellow]")
            return []
        ids = []
        for c in cands:
            if not c.ok:
                continue
            parent = self.store.alpha(c.parent_id) if c.parent_id else None
            res = gen.save([c], parent.get("hypothesis_id") if parent else None)
            ids += res["ids"]
        console.print(f"  {len(ids)} new variant(s) queued for simulation")
        return ids

    # -- simulation ------------------------------------------------------------------------------
    def _evaluate_row(self, row: dict, alpha: dict, record_themes: bool = True) -> dict:
        from .routes import record_themes as remember_themes
        ev = evaluate(alpha, self.cfg.section("power_pool"), self.cfg.section("scoring"), self.cfg.section("refine"),
                      structural={"pp_op_count": row.get("pp_op_count") or 0, "n_fields": len(row.get("fields") or [])},
                      quality=self.cfg.section("quality"), regular=self.cfg.section("regular"),
                      datasets=row.get("datasets"), measured=row.get("stats") or {})
        s = row.get("settings") or {}
        if record_themes:  # themes in an old result are not themes BRAIN shows today
            remember_themes(self.store, ev.checks, {"region": s.get("region") or row.get("region"),
                                                    "delay": s.get("delay", row.get("delay"))})
        return {"stats": ev.stats, "checks": ev.checks, "classifications": alpha.get("classifications") or [],
                "pp_status": ev.status, "pp_reasons": ev.reasons, "score": ev.score,
                "reg_status": ev.reg_status, "reg_reasons": ev.reg_reasons}

    def reconcile(self, lookback: int = 300) -> dict:
        """Attach results to alphas left in 'simulating' (e.g. the run was interrupted) by finding them in the
        account's recent alphas (same code and settings); anything not found goes back to the queue."""
        # rows another engine process is still simulating are left alone: only those started longer ago than the
        # simulation timeout count as interrupted
        stale = time.time() - float(self.cfg.get("brain.simulation.max_wait_s", 2400))
        rows = [r for r in self.store.alphas(status="simulating") if (r.get("simulated_at") or 0) < stale]
        if not rows:
            return {"recovered": 0, "requeued": 0}
        self.client.ensure_auth()

        def key(code, s):
            return (" ".join((code or "").split()), s.get("region"), s.get("universe"), int(s.get("delay") or 0),
                    str(s.get("neutralization")), int(s.get("decay") or 0), round(float(s.get("truncation") or 0), 6))

        index = {}
        for a in self.client.paginate("/users/self/alphas", {"order": "-dateCreated"}, page_size=100, max_items=lookback):
            index.setdefault(key((a.get("regular") or {}).get("code"), a.get("settings") or {}), a)
        out = {"recovered": 0, "requeued": 0}
        for r in rows:
            a = index.get(key(r["canonical"], r["settings"] or {}))
            if a is None:
                self.store.update_alpha(r["id"], status="valid")
                out["requeued"] += 1
                continue
            upd = self._evaluate_row(r, a)
            self.store.update_alpha(r["id"], status="simulated", brain_id=a["id"], simulated_at=time.time(), **upd)
            out["recovered"] += 1
            st = upd["stats"]
            console.print(f"  recovered #{r['id']} -> {a['id']}: {upd['pp_status']} Sharpe {st.get('sharpe')} "
                          f"TO {st.get('turnover')} | {esc(r['canonical'][:70])}")
        return out

    def restore(self, limit: int | None = None) -> dict:
        """Rebuild the local memory from the account's own alphas on BRAIN. The store (.p2a/) never leaves the machine
        it was made on, so a fresh checkout or a new cloud session starts without the ideas already tried: the
        lifecycle would simulate them again, and the combiner and the inventory would have no parts. Every REGULAR
        alpha the store does not hold yet becomes a simulated row. Its code is analysed against the live catalog of
        its own region, universe and delay (fields, datasets, operator counts, families); BRAIN's settings, results
        and checks are kept as BRAIN reported them. Idempotent. Daily PnL is fetched later, when a step needs it."""
        from ..fastexpr import analyze
        from ..util import stable_hash
        from . import references
        from .generator import Candidate, equivalent_source
        self.client.ensure_auth()
        if not self.store.operators():  # the analysis needs the operator catalog, not a full sync
            self.sync.sync_operators(with_docs=False)
        if not self.store.kv_get("settings_options"):
            self.sync.sync_settings()
        known = {r["brain_id"] for r in self.store.q("SELECT brain_id FROM alphas WHERE brain_id IS NOT NULL")}
        mono = self.cfg.get("fastexpr.monotonic_in_rank") or []
        out = {"restored": 0, "attached": 0, "known": 0, "skipped": 0, "references": 0, "scopes": {}}
        gens: dict = {}
        ever = set(self.store.kv_get("submitted_ever") or [])  # submitted at some point, ACTIVE or decommissioned since
        for a in self.client.paginate("/users/self/alphas", {"order": "-dateCreated"}, page_size=100,
                                      max_items=int(limit or self.cfg.get("restore.max_alphas", 5000))):
            if a.get("dateSubmitted") and a.get("id"):
                ever.add(a["id"])
            code = ((a.get("regular") or {}).get("code") or "").strip()
            s = a.get("settings") or {}
            if (a.get("type") or "REGULAR") != "REGULAR" or not code or not s.get("universe") \
                    or s.get("region") in (None, "", "ALL"):
                out["skipped"] += 1  # SuperAlphas and Region Agnostic alphas are not single-scope expressions
                continue
            if a.get("id") in known:
                out["known"] += 1
                continue
            scope = self.scope(s["region"], s["universe"], int(s.get("delay", 1)))
            ref = references.match(self.cfg, code, s)
            if ref is not None:  # a crowded reference factor: kept where references.py reads it, never as an alpha row
                rkey = references.scope_key(scope, ref["id"])
                if not (self.store.kv_get(rkey) or {}).get("brain_id"):
                    is_ = a.get("is") or {}
                    self.store.kv_set(rkey, {"brain_id": a["id"], "expression": ref["expression"],
                                             "sharpe": is_.get("sharpe"), "turnover": is_.get("turnover")})
                out["references"] += 1
                continue
            key = f"{scope['region']}/{scope['universe']}/D{scope['delay']}"
            if key not in gens:
                gens[key] = Generator(self.context(scope, None, "regular"))
            gen = gens[key]
            an = analyze(code, gen.ctx.catalog, gen.ctx.constraints)
            # the engine's own settings keys (its payloads and duplicate detection use them), with BRAIN's values
            settings = {k: s.get(k, v) for k, v in {**gen.ctx.defaults, **scope}.items()}
            c = Candidate(raw={"expression": code}, expression=code, analysis=an, settings=settings,
                          description=(a.get("regular") or {}).get("description") or "", origin="restore",
                          equivalent=equivalent_source(an, mono))
            row = gen.row(c, None)
            canonical = an.canonical or code
            row.update(payload_hash=stable_hash({"regular": c.equivalent or canonical, "settings": settings}),
                       canonical=canonical, status="simulated", brain_id=a["id"],
                       shape_class=gen.shape_class(c) if an.program is not None else None,
                       simulated_at=_epoch(a.get("dateCreated")) or time.time())
            aid = self.store.add_alpha(row)
            if aid is None:  # the same code and settings are stored already: give that row this result if it has none
                twin = self.store.alpha_by_hash(row["payload_hash"])
                if twin is None or twin.get("brain_id"):
                    out["known"] += 1
                    continue
                aid, row = twin["id"], twin
                self.store.update_alpha(aid, status="simulated", brain_id=a["id"],
                                        simulated_at=_epoch(a.get("dateCreated")) or time.time())
                out["attached"] += 1
            else:
                out["restored"] += 1
            known.add(a["id"])
            upd = self._evaluate_row(row, a, record_themes=False)
            self.store.update_alpha(aid, **upd)
            tally = out["scopes"].setdefault(key, {})
            label = upd.get("reg_status") if upd.get("reg_status") in ("eligible", "pending") else upd["pp_status"]
            tally[label] = tally.get(label, 0) + 1
            if (out["restored"] + out["attached"]) % 50 == 0:
                console.print(f"  restored {out['restored'] + out['attached']} alpha(s)...")
        self.store.kv_set("submitted_ever", sorted(ever))
        return out

    def simulate(self, limit: int | None = None, ids: list[int] | None = None) -> dict:
        if self.client is not None and self.store.alphas(status="simulating", limit=1):
            res = self.reconcile()
            if any(res.values()):
                console.print(f"  reconciling interrupted simulations: {res}")
        rows = [self.store.alpha(i) for i in ids] if ids else self.store.alphas(status="valid", limit=limit)
        rows = [r for r in rows if r and r["status"] == "valid"]
        if not rows:
            console.print("  nothing queued for simulation")
            return {"done": 0, "error": 0}
        console.print(f"  simulating {len(rows)} alpha(s)")
        jobs = []
        for r in rows:
            self.store.update_alpha(r["id"], status="simulating", simulated_at=time.time())  # start time until done
            jobs.append(SimJob(key=r["id"], payload={"type": "REGULAR", "settings": r["settings"], "regular": r["canonical"]}))
        by_id = {r["id"]: r for r in rows}
        tally = {"done": 0, "error": 0}

        def on_done(job: SimJob):
            row = by_id[job.key]
            if job.status == "done":
                upd = self._evaluate_row(row, job.alpha)
                self.store.update_alpha(job.key, status="simulated", brain_id=job.alpha_id, sim_message=job.message,
                                        simulated_at=time.time(), **upd)
                if row.get("hypothesis_id"):
                    win = {"eligible": 1.0, "pending": 1.0, "near_miss": 0.3, "suspect": 0.1}.get(upd["pp_status"], 0.0)
                    self.store.bump_hypothesis(row["hypothesis_id"], tries=1, wins=win)
                st = upd["stats"]
                tally["done"] += 1
                console.print(f"  #{job.key} {upd['pp_status']:<9} Sharpe {st.get('sharpe')} TO {st.get('turnover')} "
                              f"fit {st.get('fitness')} | {esc(row['canonical'][:70])}")
            else:
                self.store.update_alpha(job.key, status="sim_error", sim_message=job.message, simulated_at=time.time())
                self.store.record_issue("SIM_ERROR", (job.message or "")[:140])
                tally["error"] += 1
                console.print(f"  #{job.key} [red]error[/red]: {esc((job.message or '')[:160])}")

        try:
            self.simulator.run(jobs, on_done=on_done)
        finally:
            for j in jobs:  # anything interrupted goes back to the queue
                if j.status == "pending":
                    self.store.update_alpha(j.key, status="valid")
        return tally

    @staticmethod
    def _stored_alpha(row: dict, stats: dict | None = None) -> dict:
        """A BRAIN-shaped alpha rebuilt from a stored row, for re-judging it without a new simulation."""
        st = stats if stats is not None else (row.get("stats") or {})
        derived = {"ic_sharpe", "rn_sharpe", "rn_returns", "rn_fitness", "prod_corr", "prod_crowd", "self_corr",
                   "self_with", "self_with_sharpe", "mult", "ref_corr", "ref_factor", "ref_exposures"}
        is_ = {**{k: v for k, v in st.items() if k not in derived}, "checks": row.get("checks") or [],
               "investabilityConstrained": {"sharpe": st.get("ic_sharpe")}}
        if st.get("rn_sharpe") is not None:
            is_["riskNeutralized"] = {"sharpe": st.get("rn_sharpe"), "returns": st.get("rn_returns"),
                                      "fitness": st.get("rn_fitness")}
        return {"settings": row.get("settings") or {}, "classifications": row.get("classifications") or [], "is": is_}

    def reevaluate(self) -> dict:
        """Re-score stored simulation results with the current rules (no new simulations)."""
        counts: dict = {}
        for r in self.store.alphas(status="simulated"):
            upd = self._evaluate_row(r, self._stored_alpha(r))
            self.store.update_alpha(r["id"], **upd)
            for key in (f"pp:{upd['pp_status']}", f"regular:{upd.get('reg_status')}"):
                counts[key] = counts.get(key, 0) + 1
        return counts

    def families(self, scope: dict, theme: ThemeSpec | None, route: str = "power_pool") -> dict:
        from .lifecycle import Lifecycle
        return Lifecycle(self.context(scope, theme, route), simulator=self.simulator if self.client else None).families()

    def uniqueness(self, top: int | None = None, ids: list[int] | None = None) -> list[dict]:
        """Measure production and self-correlation with BRAIN's correlation endpoints (seconds per alpha) for the
        strongest candidates that have no measurement yet, and re-judge them. This is the cheap uniqueness screen
        before the full submission check."""
        from .routes import correlation_stats
        rc = self.cfg.section("regular")
        top = int(top or rc.get("uniqueness_per_run", 12))
        if ids:
            rows = [r for r in (self.store.alpha(i) for i in ids) if r and r.get("brain_id")]
        else:
            min_s = float(rc.get("uniqueness_min_sharpe", 1.0))
            rows = [r for r in self.store.q(
                "SELECT * FROM alphas WHERE status='simulated' AND brain_id IS NOT NULL AND "
                "(pp_status IN ('pending','eligible','near_miss') OR reg_status IN ('pending','near_miss','eligible'))")
                if ((r.get("stats") or {}).get("sharpe") or 0) >= min_s and (r.get("stats") or {}).get("prod_corr") is None]
            # BRAIN limits correlation requests per hour: spend them where the answer decides a submission -
            # regular candidates that pass every other test, then Power Pool candidates, then the rest by Sharpe
            rank = {"pending": 0, "eligible": 0}
            rows.sort(key=lambda r: (rank.get(r.get("reg_status"), 2) if r.get("reg_status") in rank else
                                     (1 if r.get("pp_status") in ("pending", "eligible") else 2),
                                     -((r.get("stats") or {}).get("sharpe") or 0)))
            rows = rows[:top]
        from . import references as refs
        ref_cache: dict = {}  # the reference factors of each alpha's own region, universe and delay

        def region_refs(row):
            s = self.row_scope(row)
            key = (s["region"], s["universe"], s["delay"])
            if key not in ref_cache:
                c = self.context(s, None, "regular")
                ref_cache[key] = (c, refs.pnls(c, self.simulator))
            return ref_cache[key]

        out = []
        for r in rows:
            ctx, ref_pnls = region_refs(r) if not ids else (None, None)
            if ref_pnls:  # an alpha that is a crowded factor in disguise is not worth an hourly request
                v, name = refs.row_exposure(ctx, self.simulator, r, ref_pnls)
                if v is not None:
                    st = r.get("stats") or {}
                    self.store.update_alpha(r["id"], stats={**st, "ref_corr": v, "ref_factor": name})
                    if abs(v) >= refs.limit(self.cfg):
                        console.print(f"  #{r['id']}: trades like the {name} factor ({v}); crowded, no correlation "
                                      "request spent")
                        continue
            m = correlation_stats(self.simulator.correlations(r["brain_id"], "prod"),
                                  self.simulator.correlations(r["brain_id"], "self"))
            if not m:
                console.print(f"  #{r['id']}: BRAIN has not computed its correlations yet (busy or hourly request "
                              "limit); the next run asks again")
                continue
            stats = {**(r.get("stats") or {}), **m}
            upd = self._evaluate_row({**r, "stats": stats}, self._stored_alpha(r, stats))
            self.store.update_alpha(r["id"], **upd)
            if upd.get("reg_status") in ("eligible", "pending") and self.cfg.get("regular.decrowd", True):
                self.decrowd(rows=[{**r, **upd}])  # unique enough to submit, but could be more unique
            console.print(f"  #{r['id']} prod corr {m.get('prod_corr')} ({m.get('prod_crowd', 0)} production alphas >= 0.5), "
                          f"self corr {m.get('self_corr')} -> regular: {upd.get('reg_status')}, Power Pool: {upd['pp_status']}")
            out.append({**r, **upd})
        return out

    def decrowd(self, ids: list[int] | None = None, rows: list[dict] | None = None) -> list[int]:
        """One variant per alpha whose measured production correlation is above regular.prod_corr_target: its tilts
        toward crowded reference factors (|PnL correlation| >= uniqueness.tilt_min) are regressed out with
        regression_proj. Measured 18 Oct: the value tilt (0.31) removed from a composite cut its production
        correlation from 0.694 to below 0.6 for 0.1 Sharpe; CROWDING neutralization cost 0.85 Sharpe and
        STATISTICAL broke the sub-universe test."""
        from . import references as refs
        from .refiner import residual_code
        target = float(self.cfg.get("regular.prod_corr_target", 0.65))
        exprs = {r["id"]: r["expression"] for r in refs.specs(self.cfg)}
        rows = rows if rows is not None else [r for r in (self.store.alpha(i) for i in ids or []) if r]
        done = {r["parent_id"] for r in self.store.q("SELECT parent_id FROM alphas WHERE origin='refine:residualize'")}
        queued = []
        for r in rows:
            st = r.get("stats") or {}
            pv = st.get("prod_corr")
            if r["id"] in done or pv is None or pv < target:
                continue
            # the variant is built, checked and simulated in the parent's own region, universe and delay
            ctx = self.context(self.row_scope(r), None, "regular")
            gen = Generator(ctx)
            if not st.get("ref_exposures"):
                ex = refs.row_exposures(ctx, self.simulator if self.client else None, r)
                st = {**st, "ref_exposures": ex}
                self.store.update_alpha(r["id"], stats=st)
            factors = [f for f in refs.tilts(st, self.cfg) if f in exprs]
            if not factors:
                console.print(f"  #{r['id']}: production correlation {pv} but no factor tilt to remove")
                continue
            code = r["canonical"]
            for f in factors:
                code = residual_code(code, exprs[f])
            sv = r.get("settings") or {}
            why = ", ".join(f"{f} ({st['ref_exposures'][f]:+.2f})" for f in factors)
            raw = {"expression": code, "neutralization": sv.get("neutralization"), "decay": sv.get("decay"),
                   "truncation": sv.get("truncation"),
                   "idea": f"{(r.get('description') or '').split(chr(10))[0][:600]} Variant: the parts of the signal "
                           f"explained by crowded factors it leaned on ({why}) are regressed out to lower its correlation "
                           "with production alphas.",
                   "rationale_data": "the parent's fields; the factor fields only to build the factors removed",
                   "rationale_operators": "regression_proj(): fits the cross-sectional regression on each crowded "
                                          "factor (with intercept); the residual keeps the information beyond it"}
            c = gen.check(raw, origin="refine:residualize", parent_id=r["id"])
            res = gen.save([c], None)
            queued += res["ids"]
            console.print(f"  #{r['id']} prod corr {pv}: residual on {why} -> {'queued' if res['ids'] else 'not valid'}")
        return queued

    def exposures(self, scope: dict | None = None) -> int:
        """Reference-factor exposure for simulated alphas that have none yet and carry some signal (one PnL download
        each): the lifecycle sends those that trade like a crowded factor to a residual test (refine:orthogonalize).
        Only alphas of `scope` (the run's region, universe and delay) are measured, so a run never simulates the
        references of regions it is not working on."""
        min_s = float(self.cfg.get("uniqueness.exposure_min_sharpe", 0.6))
        ids = [r["id"] for r in self.store.q("SELECT * FROM alphas WHERE status='simulated' AND brain_id IS NOT NULL")
               if (r.get("stats") or {}).get("ref_corr") is None and abs((r.get("stats") or {}).get("sharpe") or 0) >= min_s
               and (scope is None or _same_scope(self.row_scope(r), scope))]
        if not ids:
            return 0
        rows = self.references(ids=ids)
        flagged = [r for r in rows if abs(r["ref_corr"]) >= float(self.cfg.get("uniqueness.reference_limit", 0.6))]
        console.print(f"  reference factors: {len(rows)} alpha(s) measured, {len(flagged)} trade like a crowded factor")
        return len(rows)

    def row_scope(self, row: dict) -> dict:
        """The region / universe / delay an alpha was simulated in."""
        s = row.get("settings") or {}
        return self.scope(s.get("region") or row.get("region"), s.get("universe") or row.get("universe"),
                          s.get("delay", row.get("delay")))

    def references(self, ids: list[int] | None = None, top: int = 40, scope: dict | None = None) -> list[dict]:
        """Simulate the crowded reference factors once (references.py) and report how much each alpha trades like
        them, next to BRAIN's measured production correlation where there is one (to calibrate the screen).

        Every alpha is compared with the references of its own region, universe and delay: production in each
        region is crowded by the same kinds of factor, but a factor's daily PnL exists only where it trades. Without
        ids, the alphas of `scope` (default: the configured target) are measured."""
        from . import references as refs
        if ids:
            rows = [r for r in (self.store.alpha(i) for i in ids) if r and r.get("brain_id")]
        else:  # the measured alphas first (calibration), then the strongest unmeasured ones
            scope = scope or self.scope()
            rows = [r for r in self.store.q("SELECT * FROM alphas WHERE status='simulated' AND brain_id IS NOT NULL")
                    if _same_scope(self.row_scope(r), scope)]
            rows.sort(key=lambda r: ((r.get("stats") or {}).get("prod_corr") is None,
                                     -abs((r.get("stats") or {}).get("sharpe") or 0)))
            rows = rows[:top]
        groups: dict[tuple, tuple[dict, list]] = {}
        for r in rows:
            s = self.row_scope(r)
            groups.setdefault((s["region"], s["universe"], s["delay"]), (s, []))[1].append(r)
        out = []
        for s, grp in groups.values():
            ctx = self.context(s, None, "regular")
            if self.client is not None:
                refs.ensure(ctx, self.simulator, Generator(ctx).build_settings)
            ref_pnls = refs.pnls(ctx, self.simulator if self.client else None)
            if not ref_pnls:
                console.print(f"  no reference factor simulated yet for {s['region']} {s['universe']} D{s['delay']}")
                continue
            for r in grp:
                ex = refs.row_exposures(ctx, self.simulator if self.client else None, r, ref_pnls)
                if not ex:
                    continue
                name = max(ex, key=lambda k: abs(ex[k]))
                v = ex[name]
                st = r.get("stats") or {}
                self.store.update_alpha(r["id"], stats={**st, "ref_corr": v, "ref_factor": name, "ref_exposures": ex})
                out.append({"id": r["id"], "sharpe": st.get("sharpe"), "prod_corr": st.get("prod_corr"), "ref_corr": v,
                            "ref_factor": name, "code": r["canonical"]})
        return out

    def check(self, top: int = 5, ids: list[int] | None = None) -> list[dict]:
        """Run the platform's submission check (read-only) on the best pending candidates of both routes: Power Pool
        candidates waiting for their theme / correlation checks, and regular candidates whose every computed test
        passes and only the correlation tests (self, production) are still pending."""
        if ids:
            rows = [r for r in (self.store.alpha(i) for i in ids) if r and r.get("brain_id")]
        else:
            # BRAIN's check is slow: spend it only on families the lifecycle has not already ruled out
            from .lifecycle import row_family
            rows, seen = [], set()
            scope = self.scope()
            theme = self.resolve_theme(scope)
            frac = float(self.cfg.get("regular.check_min_fraction", 0.95))
            bar = float(self.cfg.get("regular.min_sharpe", 1.58))
            queries = [("power_pool", "SELECT * FROM alphas WHERE status='simulated' AND pp_status IN ('pending','eligible') "
                                      "AND brain_id IS NOT NULL ORDER BY pp_status='eligible', score DESC"),
                       ("regular", "SELECT * FROM alphas WHERE status='simulated' AND reg_status='pending' "
                                   "AND brain_id IS NOT NULL ORDER BY score DESC")]
            per_route = max(1, top)
            for route, sql in queries:
                ctx = self.context(scope, theme, route)
                fams = self.families(scope, theme, route)
                n = 0
                for r in self.store.q(sql):
                    if r["id"] in seen:
                        continue
                    if route == "regular" and ((r.get("stats") or {}).get("sharpe") or 0) < frac * bar:
                        continue
                    f = fams.get(row_family(ctx, r))
                    if f is not None and f.state in ("used", "dropped"):
                        continue
                    rows.append(r)
                    seen.add(r["id"])
                    n += 1
                    if n >= per_route:
                        break
        out = []
        describe = self.cfg.get("power_pool.describe_before_check", True)
        for r in rows:
            console.print(f"  checking #{r['id']} ({r['brain_id']})...")
            if describe and r.get("description"):  # Power Pool theme matching requires the description
                self.simulator.set_properties(r["brain_id"], description=r["description"])
            for kind in ("prod", "self"):  # the check only reports correlations once these have computed them
                self.simulator.correlations(r["brain_id"], kind)
            data = self.simulator.check(r["brain_id"])
            alpha = self.simulator.refresh_alpha(r["brain_id"])
            if not alpha:
                continue
            if data and (data.get("is") or {}).get("checks"):
                alpha.setdefault("is", {})["checks"] = data["is"]["checks"]
            upd = self._evaluate_row(r, alpha)
            self.store.update_alpha(r["id"], **upd)
            st = upd["stats"]
            extra = f" | prod corr {st.get('prod_corr')}" if st.get("prod_corr") is not None else ""
            console.print(f"    -> Power Pool: {upd['pp_status']}, regular: {upd.get('reg_status')}{extra}")
            for line in (upd["pp_reasons"] or [])[:4]:
                console.print(f"       [dim]PP: {esc(line)}[/dim]")
            for line in (upd.get("reg_reasons") or [])[:4]:
                console.print(f"       [dim]regular: {esc(line)}[/dim]")
            out.append({**r, **upd})
        return out

    # -- full loop ---------------------------------------------------------------------------------
    def run(self, scope: dict, theme: ThemeSpec | None, cycles: int = 1, n_hypotheses: int = 2,
            simulate: bool = True, refine_rounds: int | None = None, check_top: int = 5,
            route: str = "power_pool") -> None:
        """One research cycle for a route: LLM generation from the papers, exploration of uncrowded data, research
        shapes, combinations of weakly correlated signals, simulation, lifecycle-driven refinement, BRAIN's check."""
        refine_rounds = int(self.cfg.get("refine.max_rounds", 2)) if refine_rounds is None else refine_rounds
        for cycle in range(1, cycles + 1):
            console.rule(f"cycle {cycle}/{cycles} ({route})  |  LLM budget left today: {self.llm.budget_left()}")
            new = self.generate(scope, theme, n_hypotheses=n_hypotheses, route=route)
            if self.cfg.get("explore.enabled", True):
                new += self.explore(scope, theme, route=route)
            if self.cfg.get("shapes.enabled", True):
                new += self.shape_step(scope, theme, route=route)
            if self.cfg.get("mechanisms.enabled", True) and route == "regular":
                new += self.mechanisms(scope, theme, route=route)
            if not simulate:
                continue
            if new or self.store.alphas(status="valid", limit=1):
                self.simulate()
            if route == "regular" and self.client is not None:
                self.exposures(scope)  # which new alphas are a crowded factor in disguise (references.py)
            if self.cfg.get("combine.enabled", True):  # after simulation: new parts may now combine
                ids = self.combine(scope, theme, route=route)
                if ids:
                    self.simulate(ids=ids)
            if self.cfg.get("refine.enabled", True):
                for rnd in range(refine_rounds):
                    use_llm = self.llm.budget_left() > 0
                    ids = self.refine(scope, theme, use_llm=use_llm, route=route)
                    if not ids:
                        break
                    self.simulate(ids=ids)
                    if route == "regular" and self.client is not None:
                        self.exposures(scope)
            if check_top:
                self.uniqueness()
                self.check(check_top)
            if self.llm.budget_left() <= 0:
                console.print("[yellow]LLM budget for today is used up; stopping after this cycle.[/yellow]")
                break
        path = self.report()
        console.print(f"[bold]Report:[/bold] {path}")

    # -- reporting ----------------------------------------------------------------------------------
    def queue(self, scope: dict | None = None, theme: ThemeSpec | None = None, route: str = "power_pool") -> list[dict]:
        """Submittable alphas of one route in the order to submit them (see lifecycle.submission_queue)."""
        from .lifecycle import Lifecycle, submission_queue
        scope = scope or self.scope()
        theme = theme if theme is not None else self.resolve_theme(scope)
        ctx = self.context(scope, theme, route)
        sim = self.simulator if self.client else None
        return submission_queue(ctx, sim, Lifecycle(ctx, simulator=sim), route=route)

    def _queue_lines(self) -> list[str]:
        lines = []
        titles = {"regular": ("## Production (regular) alphas, in submission order",
                              "Every BRAIN consultant test passed, production correlation included (4 a day). Value = "
                              "Sharpe x BRAIN's multipliers x (1 - production correlation), an ordering heuristic."),
                  "power_pool": ("## Power Pool alphas, in submission order",
                                 "BRAIN's Power Pool check passed. 'Power Pool + Regular' rows also pass every regular "
                                 "test and do not use the pure Power Pool quota.")}
        for route in ("regular", "power_pool"):
            title, note = titles[route]
            try:
                q = self.queue(route=route)
            except Exception as e:  # the report must not fail because BRAIN is unreachable
                lines += [title, "", f"(queue unavailable: {e})", ""]
                continue
            lines += [title, "", note, "",
                      "| order | # | BRAIN | Sharpe | fitness | turnover | prod corr | multiplier | expression | warnings |",
                      "|---|---|---|---|---|---|---|---|---|---|"]
            k = 0
            for r in q:
                st = r.get("stats") or {}
                k += 1 if r["queued"] else 0
                order = str(k) if r["queued"] else "skip"
                flags = "; ".join(r.get("flags") or []) or "-"
                if not r["queued"]:
                    flags = f"{r.get('why_not')}; {flags}"
                lines.append(f"| {order} | {r['id']} | [{r['brain_id']}]({PLATFORM_ALPHA_URL.format(r['brain_id'])}) | "
                             f"{st.get('sharpe')} | {st.get('fitness')} | {st.get('turnover')} | {st.get('prod_corr', '-')} | "
                             f"{st.get('mult', '-')} | `{r['canonical']}` | {flags} |")
            if not q:
                lines.append("| - | - | - | - | - | - | - | - | nothing submittable yet | - |")
            lines.append("")
        return lines

    def _family_lines(self) -> list[str]:
        from .lifecycle import family_table
        try:
            fams = self.families(self.scope(), self.resolve_theme(self.scope()))
        except Exception as e:
            return [f"(families unavailable: {e})", ""]
        lines = ["## Idea families", "", "One simulation budget per set of data fields; settings variants share it.", "",
                 "| fields | state | sims | best Sharpe | why |", "|---|---|---|---|---|"]
        for key, state, sims, _queued, best, why in family_table(fams):
            lines.append(f"| {key} | {state} | {sims} | {best} | {why} |")
        return lines + [""]

    def report(self, top: int = 25, path: Path | None = None) -> Path:
        rows = self.store.q("SELECT * FROM alphas WHERE status='simulated' ORDER BY "
                            "CASE WHEN reg_status='eligible' THEN 0 WHEN pp_status='eligible' THEN 1 WHEN reg_status='pending' "
                            "THEN 2 WHEN pp_status='pending' THEN 3 WHEN reg_status='near_miss' THEN 4 WHEN pp_status='near_miss' "
                            "THEN 5 ELSE 6 END, score DESC LIMIT ?", (top,))
        counts = {r["status"]: r["n"] for r in self.store.q("SELECT status, COUNT(*) AS n FROM alphas GROUP BY status")}
        lines = [f"# paper2alpha report - {datetime.now():%Y-%m-%d %H:%M}", "",
                 f"Alphas by status: {counts}", ""]
        lines += self._queue_lines() + self._family_lines()
        lines += ["## All results", "",
                 "| # | Power Pool | regular | Sharpe | fitness | turnover | prod corr | margin (bps) | ops | fields | BRAIN id |",
                 "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            st = r.get("stats") or {}
            m = st.get("margin")
            lines.append(f"| {r['id']} | {r['pp_status']} | {r.get('reg_status') or '-'} | {st.get('sharpe')} | "
                         f"{st.get('fitness')} | {st.get('turnover')} | {st.get('prod_corr', '-')} | "
                         f"{round(m * 1e4, 2) if isinstance(m, (int, float)) else ''} | {r['pp_op_count']} | "
                         f"{len(r.get('fields') or [])} | {r.get('brain_id') or ''} |")
        lines.append("")
        for r in rows:
            s = r.get("settings") or {}
            hyp = self.store.hypothesis(r["hypothesis_id"]) if r.get("hypothesis_id") else None
            lines += [f"## #{r['id']} - {r['pp_status']} (score {r['score']})", "",
                      f"- Hypothesis: {hyp['title'] if hyp else '-'}",
                      f"- Settings: {s.get('region')}/{s.get('universe')}/D{s.get('delay')}, neutralization {s.get('neutralization')}, "
                      f"decay {s.get('decay')}, truncation {s.get('truncation')}",
                      f"- Theme: {r.get('theme') or '-'} | categories: {', '.join(r.get('categories') or [])} | "
                      f"datasets: {', '.join(r.get('datasets') or [])}"]
            if r.get("brain_id"):
                lines.append(f"- BRAIN: {PLATFORM_ALPHA_URL.format(r['brain_id'])}")
            if r.get("pp_reasons"):
                lines.append(f"- Open issues (Power Pool): {'; '.join(r['pp_reasons'])}")
            if r.get("reg_reasons"):
                lines.append(f"- Open issues (regular): {'; '.join(r['reg_reasons'])}")
            lines += ["", "```", r["canonical"], "```", "", "Power Pool description:", "", "```",
                      r.get("description") or "", "```", ""]
        out = path or (self.cfg.data_dir / "reports" / f"report-{date.today().isoformat()}-{datetime.now():%H%M}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines))
        return out

"""Command line interface: `python -m p2a <command>` (or `p2a` if installed)."""
from __future__ import annotations

import argparse
import json
import sys

from .config import Config, brain_credentials, openrouter_key
from .util import console, esc


def _scope_args(p):
    p.add_argument("--region")
    p.add_argument("--universe")
    p.add_argument("--delay", type=int)


def _route_args(p, default="power_pool"):
    p.add_argument("--route", choices=["power_pool", "regular"], default=default,
                   help="power_pool: theme-matched Power Pool alphas; regular: production alphas that must pass every "
                        "consultant test, production correlation included (default %(default)s)")


def _theme_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--theme", help="Power Pool theme name (default: the active one matching the scope)")
    g.add_argument("--no-theme", action="store_true", help="ignore themes (structural Power Pool limits still apply)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="p2a", description="paper2alpha: research papers -> WorldQuant BRAIN Power Pool alphas")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--offline", action="store_true", help="do not call the BRAIN API (use the local catalog cache)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check keys, login, catalog and themes")
    sub.add_parser("login", help="log in to BRAIN (handles biometric sign-in)")
    p = sub.add_parser("sync", help="sync operators, settings, categories, datasets and docs from BRAIN")
    _scope_args(p)
    p.add_argument("--no-docs", action="store_true", help="skip operator docs and Learn pages")
    p = sub.add_parser("themes", help="show Power Pool themes and how they were interpreted")
    _scope_args(p)
    p = sub.add_parser("models", help="list free OpenRouter models and what the engine learned about them")
    p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("ingest", help="add research papers (PDF, txt/md, folder, URL, arXiv id)")
    p.add_argument("sources", nargs="+")
    p.add_argument("--no-extract", action="store_true", help="store the paper without extracting hypotheses")
    p = sub.add_parser("hypotheses", help="list hypotheses, or extract them for a stored paper")
    p.add_argument("--paper")
    p.add_argument("--extract", metavar="PAPER_ID")
    p = sub.add_parser("validate", help="statically validate a Fast Expression against the live catalog")
    p.add_argument("expression")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("generate", help="generate + validate + repair alphas for hypotheses")
    p.add_argument("--hypothesis", type=int, action="append", help="hypothesis id (repeatable)")
    p.add_argument("--n-hyp", type=int, default=2, help="hypotheses to use when none is given")
    p.add_argument("--per-call", type=int, help="candidates requested per LLM call")
    p.add_argument("--simulate", action="store_true", help="simulate the valid candidates right away")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("try", help="validate (and simulate) hand-written expressions through the same checks as LLM output")
    p.add_argument("expression", nargs="?")
    p.add_argument("--file", help="JSON list of {expression, neutralization, decay, truncation, idea, rationale_data, "
                                  "rationale_operators, hypothesis_id}")
    p.add_argument("--neutralization")
    p.add_argument("--decay", type=int)
    p.add_argument("--truncation", type=float)
    p.add_argument("--idea", default="")
    p.add_argument("--hypothesis", type=int)
    p.add_argument("--no-sim", action="store_true")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("explore", help="one probe per untried field of the theme's most valuable, least crowded datasets")
    p.add_argument("--n", type=int, help="number of probes (default explore.probes)")
    p.add_argument("--category", help="only datasets of this data category (e.g. analyst)")
    p.add_argument("--simulate", action="store_true")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("shapes", help="next research shapes (change, event, spread, orthogonal, ...) for fields with signal")
    p.add_argument("--n", type=int, help="number of shape candidates (default shapes.per_step)")
    p.add_argument("--simulate", action="store_true")
    p.add_argument("--stats", action="store_true", help="what each shape class has produced on each kind of data")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("simulate", help="simulate queued (validated) alphas on BRAIN")
    p.add_argument("--limit", type=int)
    sub.add_parser("reconcile", help="recover results of simulations that finished while the engine was stopped")
    sub.add_parser("reevaluate", help="re-score stored simulation results with the current rules")
    p = sub.add_parser("refine", help="create variants of near-miss alphas")
    p.add_argument("--limit", type=int)
    p.add_argument("--no-llm", action="store_true", help="only deterministic variants (no LLM request)")
    p.add_argument("--ids", type=int, action="append", help="refine these local alpha ids (any status)")
    p.add_argument("--simulate", action="store_true")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("check", help="run BRAIN's submission check (read-only) on the best candidates")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--ids", type=int, action="append", help="check these local alpha ids (repeatable)")
    p = sub.add_parser("combine", help="combinations of weakly correlated, economically linked signals estimated from "
                                       "their daily PnL to clear the route's Sharpe bar")
    p.add_argument("--n", type=int, help="number of combinations (default combine.per_step)")
    p.add_argument("--origin", help="only parts whose origin starts with this (e.g. 'mechanism:' for research mechanisms)")
    p.add_argument("--simulate", action="store_true")
    _scope_args(p)
    _theme_args(p)
    _route_args(p, "regular")
    p = sub.add_parser("mechanisms", help="research mechanisms (residual reversal, news-conditioned reversal, overnight tone, "
                                          "connected-firm momentum, ...) filled from the live catalog")
    p.add_argument("--n", type=int)
    p.add_argument("--only", action="append", help="mechanism id (repeatable)")
    p.add_argument("--list", action="store_true", help="show each mechanism and the live fields its roles resolve to")
    p.add_argument("--simulate", action="store_true")
    _scope_args(p)
    _theme_args(p)
    _route_args(p, "regular")
    p = sub.add_parser("enhance", help="volatility scaling, double neutralization and turnover targeting for alphas that work")
    p.add_argument("--ids", type=int, action="append")
    p.add_argument("--n", type=int)
    p.add_argument("--only", action="append", help="enhancer id (repeatable)")
    p.add_argument("--simulate", action="store_true")
    _scope_args(p)
    _theme_args(p)
    _route_args(p, "regular")
    p = sub.add_parser("uniqueness", help="measure production / self correlation of the strongest unmeasured candidates "
                                          "with BRAIN's fast correlation endpoints")
    p.add_argument("--top", type=int)
    p.add_argument("--ids", type=int, action="append")
    p = sub.add_parser("decrowd", help="regress out the crowded-factor tilts of alphas whose production correlation is "
                                       "above regular.prod_corr_target (queues one variant each)")
    p.add_argument("--ids", type=int, action="append", required=True)
    p.add_argument("--simulate", action="store_true")
    p = sub.add_parser("references", help="simulate the crowded reference factors once and show how much alphas trade "
                                          "like them (a local production-correlation screen)")
    p.add_argument("--ids", type=int, action="append")
    p.add_argument("--top", type=int, default=40)
    _scope_args(p)
    p = sub.add_parser("inventory", help="every simulated part of a scope and whether it can still feed a production alpha "
                                         "(available / used / crowded / illiquid / weak)")
    p.add_argument("--refresh", action="store_true", help="re-measure cached parts")
    p.add_argument("--all", action="store_true", help="list every verdict, not only available and weak parts")
    _scope_args(p)
    p = sub.add_parser("osmosis", help="Osmosis points plan per scope (region x delay): what is missing for a valid "
                                       "allocation and a points split that maximizes each scope's combo Sharpe (read-only)")
    p.add_argument("--refresh", action="store_true", help="re-read the submitted alphas from BRAIN")
    p.add_argument("--csv", help="also write alpha,scope,points to this CSV file")
    p = sub.add_parser("pyramids",help="BRAIN's pyramid multipliers (region x delay x category) and the themes seen in checks")
    _scope_args(p)
    p = sub.add_parser("queue", help="submittable alphas in the order to submit them (one per idea family, low correlation)")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("families", help="the idea lifecycle: which signal families are winners, promising, used or dropped")
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("run", help="full loop: generate -> simulate -> refine -> check -> report")
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--n-hyp", type=int, default=2)
    p.add_argument("--no-sim", action="store_true")
    p.add_argument("--check-top", type=int, default=5)
    _scope_args(p)
    _theme_args(p)
    _route_args(p)
    p = sub.add_parser("report", help="write a markdown report of the best alphas")
    p.add_argument("--top", type=int, default=25)
    p = sub.add_parser("describe", help="print an alpha's Power Pool description (optionally set it on BRAIN)")
    p.add_argument("alpha_id", type=int, help="local alpha id (see report)")
    p.add_argument("--apply", action="store_true", help="PATCH the description onto the BRAIN alpha")
    sub.add_parser("stats", help="what the engine has learned so far")
    p = sub.add_parser("load-catalog", help="load a catalog snapshot in BRAIN API shape (offline demos/tests)")
    p.add_argument("path")
    p.add_argument("--operators", help="operators JSON (list from GET /operators)")
    return ap


def _table(title, columns, rows):
    try:
        from rich.table import Table
    except ImportError:
        console.print(title)
        for r in rows:
            console.print("  " + " | ".join(str(x) for x in r))
        return
    t = Table(title=title, show_lines=False)
    for c in columns:
        t.add_column(c, overflow="fold")
    for r in rows:
        t.add_row(*[str(x) for x in r])
    console.print(t)


def main(argv=None) -> int:
    from .brain import AuthRequired, BrainError
    from .llm import LLMError
    try:
        return _main(argv)
    except AuthRequired as e:
        console.print(f"[yellow]{esc(str(e))}[/yellow]")
        return 2
    except (BrainError, LLMError) as e:
        console.print(f"[red]{esc(str(e))}[/red]")
        return 1
    except KeyboardInterrupt:
        console.print("[yellow]interrupted[/yellow]")
        return 130


def _main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.load(args.config)
    from .engine import Engine

    session_exists = (cfg.data_dir / cfg.get("brain.session_file", "session.json")).exists()
    offline = args.offline or (brain_credentials() is None and not session_exists and args.cmd not in ("login",))
    eng = Engine(cfg, offline=offline)
    route = getattr(args, "route", None) or "power_pool"
    if route == "regular":  # production alphas: their own universe choice (regular.universe), no theme
        scope = eng.regular_scope(getattr(args, "region", None), getattr(args, "universe", None), getattr(args, "delay", None))
    else:
        scope = eng.scope(getattr(args, "region", None), getattr(args, "universe", None), getattr(args, "delay", None))

    def theme():
        if route == "regular":
            return None
        return eng.resolve_theme(scope, getattr(args, "theme", None), not getattr(args, "no_theme", False))

    cmd = args.cmd
    if cmd == "doctor":
        console.print(f"config: {cfg.root / 'config.yaml'}")
        console.print(f"OpenRouter key: {'set' if openrouter_key() else '[red]missing[/red]'}")
        try:
            ms = eng.llm.models()
            console.print(f"free models usable: {len(ms)} ({', '.join(m.id for m in ms[:6])}{'...' if len(ms) > 6 else ''})")
        except Exception as e:
            console.print(f"[red]OpenRouter model list failed: {e}[/red]")
        console.print(f"LLM budget left today: {eng.llm.budget_left()} / {eng.llm.daily_budget}")
        console.print(f"BRAIN credentials: {'set' if brain_credentials() else '[yellow]missing (offline mode)[/yellow]'}")
        if eng.client:
            try:
                eng.client.ensure_auth()
                console.print(f"BRAIN login: ok (multi-simulation: {eng.client.can_multi_simulate})")
            except Exception as e:
                console.print(f"[red]BRAIN login failed: {e}[/red]")
        console.print(f"catalog: {len(eng.store.operators())} operators, {len(eng.store.datasets(scope))} datasets, "
                      f"{len(eng.store.fields(scope))} cached fields for {scope['region']}/{scope['universe']}/D{scope['delay']}")
        console.print(f"papers: {len(eng.store.documents('paper'))}, hypotheses: {len(eng.store.hypotheses())}")
        th = eng.resolve_theme(scope)
        console.print(f"theme for this scope: {th.name if th else 'none'}")
        return 0
    if cmd == "login":
        eng.client.login()
        console.print(f"logged in; permissions: {', '.join(eng.client.permissions) or 'n/a'}")
        return 0
    if cmd == "sync":
        summary = eng.sync_catalog(scope, docs=not args.no_docs)
        console.print(f"synced: {summary}")
        return 0
    if cmd == "themes":
        specs = eng.themes(scope)
        rows = []
        for s in specs:
            rows.append([s.name, s.source, f"{s.start or ''}..{s.end or ''}", s.delay, sorted(s.categories or []) or "-",
                         "category" if s.single_category else ("dataset" if s.single_dataset else "-"),
                         len(s.api_datasets), "; ".join(s.warnings + s.extra + s.scope_problems(scope)) or "-"])
        _table(f"Power Pool themes ({scope['region']}/{scope['universe']}/D{scope['delay']})",
               ["name", "source", "window", "delay", "categories", "single", "API-tagged datasets", "notes"], rows)
        th = eng.resolve_theme(scope)
        console.print(f"active for this scope: [bold]{th.name if th else 'none'}[/bold]")
        return 0
    if cmd == "models":
        if args.refresh:
            eng.llm.models(refresh=True)
        _table("free OpenRouter models (learned usefulness)", ["model", "context", "score", "calls", "fails", "last error"],
               [[r["model"], r["context"], f"{r['mean']:.2f}", r["calls"], r["failures"], (r["last_error"] or "")[:60]]
                for r in eng.llm.scoreboard()])
        console.print(f"LLM budget left today: {eng.llm.budget_left()}")
        return 0
    if cmd == "ingest":
        eng.ingest(args.sources, extract=not args.no_extract)
        return 0
    if cmd == "hypotheses":
        if args.extract:
            from .engine.hypotheses import extract_hypotheses
            extract_hypotheses(eng.store, eng.llm, cfg, args.extract)
        rows = eng.store.hypotheses(args.paper)
        _table("hypotheses", ["id", "paper", "title", "categories", "tries", "wins"],
               [[h["id"], h["paper_id"], h["title"][:70], ",".join(h.get("categories") or []), h["tries"], h["wins"]]
                for h in rows])
        return 0
    if cmd == "validate":
        from .fastexpr import analyze
        ctx = eng.context(scope, theme(), route)
        an = analyze(args.expression, ctx.catalog, ctx.constraints)
        console.print(f"canonical : {esc(an.canonical)}")
        console.print(f"operators : {an.op_count} (Power Pool count {an.pp_op_count()}): {', '.join(an.operators)}")
        console.print(f"fields    : {', '.join(an.counted_fields()) or '-'} | categories {an.categories()} | datasets {an.datasets()}")
        console.print(f"theme     : {ctx.theme.name if ctx.theme else 'none'}")
        for i in an.issues:
            color = "red" if i.severity == "error" else "yellow"
            console.print(f"[{color}]{esc(i.render())}[/{color}]")
        console.print("[green]VALID[/green]" if an.ok else "[red]INVALID[/red]")
        return 0 if an.ok else 1
    if cmd == "generate":
        ids = eng.generate(scope, theme(), args.hypothesis, args.n_hyp, args.per_call, route=route)
        if args.simulate and ids:
            eng.simulate(ids=ids)
        return 0
    if cmd == "explore":
        ids = eng.explore(scope, theme(), args.n, getattr(args, "category", None), route=route)
        if ids and args.simulate:
            eng.simulate(ids=ids)
        return 0
    if cmd == "shapes":
        if args.stats:
            from .engine.shapes import ShapeLibrary, shape_stats
            ctx = eng.context(scope, theme())
            lib = ShapeLibrary.load(cfg, ctx.catalog)
            st = shape_stats(eng.store, lib, float(cfg.get("power_pool.min_sharpe", 1.0)), scope)
            _table("shape classes by kind of data", ["shape class", "data kind", "tried", "mean Sharpe", "best", "cleared"],
                   [[c, k or "-", v["n"], f"{v['sum'] / v['n']:.2f}", f"{v['best']:.2f}", v["wins"]]
                    for (c, k), v in sorted(st.items(), key=lambda kv: (-kv[1]["wins"], -kv[1]["n"]))])
            return 0
        ids = eng.shape_step(scope, theme(), args.n, route=route)
        if ids and args.simulate:
            eng.simulate(ids=ids)
        return 0
    if cmd == "try":
        if args.file:
            raws = json.loads(open(args.file).read())
        elif args.expression:
            raws = [{"expression": args.expression, "neutralization": args.neutralization, "decay": args.decay,
                     "truncation": args.truncation, "idea": args.idea, "hypothesis_id": args.hypothesis}]
        else:
            console.print("[red]give an expression or --file[/red]")
            return 1
        ids = eng.try_candidates(scope, theme(), raws, route=route)
        if ids and not args.no_sim:
            eng.simulate(ids=ids)
        return 0
    if cmd == "simulate":
        eng.simulate(limit=args.limit)
        return 0
    if cmd == "reevaluate":
        console.print(f"{eng.reevaluate()}")
        return 0
    if cmd == "reconcile":
        console.print(f"{eng.reconcile()}")
        return 0
    if cmd == "refine":
        ids = eng.refine(scope, theme(), args.limit, use_llm=not args.no_llm, ids=args.ids, route=route)
        if args.simulate and ids:
            eng.simulate(ids=ids)
        return 0
    if cmd == "check":
        eng.check(args.top, ids=args.ids)
        return 0
    if cmd == "combine":
        ids = eng.combine(scope, theme(), args.n, route=route, origin=args.origin)
        if ids and args.simulate:
            eng.simulate(ids=ids)
        return 0
    if cmd == "mechanisms":
        if args.list:
            from .engine.mechanisms import MechanismBuilder
            ctx = eng.context(scope, theme(), route)
            mb = MechanismBuilder(ctx, None)
            rows = []
            for m in mb.lib.mechanisms + mb.lib.enhancers:
                filled = []
                for role in m.roles:
                    c = mb.resolver.candidates(role)
                    filled.append(f"{role}: {c[0]['id'] if c else '-'} (+{max(0, len(c) - 1)})")
                rows.append([m.id, "enhancer" if m.enhancer else m.group, "ok" if m.available else
                             f"missing {', '.join(sorted(m.missing_ops))}", "; ".join(filled) or "-"])
            _table("research mechanisms", ["mechanism", "group", "operators", "roles -> live fields"], rows)
            return 0
        ids = eng.mechanisms(scope, theme(), args.n, route=route, only=args.only)
        if ids and args.simulate:
            eng.simulate(ids=ids)
        return 0
    if cmd == "enhance":
        ids = eng.enhance(scope, theme(), ids=args.ids, n=args.n, route=route, only=args.only)
        if ids and args.simulate:
            eng.simulate(ids=ids)
        return 0
    if cmd == "decrowd":
        ids = eng.decrowd(args.ids)
        if ids and args.simulate:
            eng.simulate(ids=ids)
        return 0
    if cmd == "references":
        rows = eng.references(args.ids, args.top, scope=scope)
        _table("crowded reference factors", ["#", "Sharpe", "prod corr (BRAIN)", "max |ref corr|", "factor", "expression"],
               [[r["id"], r["sharpe"], r["prod_corr"] if r["prod_corr"] is not None else "-", r["ref_corr"],
                 r["ref_factor"], r["code"][:70]] for r in rows])
        return 0
    if cmd == "inventory":
        from .engine.inventory import build
        rows = build(eng, scope, refresh=args.refresh)
        shown = rows if args.all else [r for r in rows if r["verdict"] in ("available", "weak")]
        _table(f"signal inventory {scope['region']} {scope['universe']} D{scope['delay']}: "
               f"{sum(1 for r in rows if r['verdict'] == 'available')} available of {len(rows)} parts",
               ["#", "verdict", "Sharpe", "last 2y", "sub ratio", "max |ref| (factor)", "max corr submitted", "fields",
                "expression"],
               [[r["id"], r["verdict"], r["sharpe"], r["last2y"], r["sub_ratio"],
                 f"{r['ref_corr']} ({r['ref_factor']})" if r["ref_corr"] is not None else "-",
                 f"{r['max_sub_corr']} ({r['sub_with']})" if r["max_sub_corr"] is not None else "-",
                 ", ".join(r["fields"])[:40], (r["code"] or "")[:60]] for r in shown])
        return 0
    if cmd == "uniqueness":
        eng.uniqueness(args.top, ids=args.ids)
        return 0
    if cmd == "osmosis":
        from .engine.osmosis import plan
        res = plan(eng, refresh=args.refresh)
        n, total = res["min_alphas"], res["points_per_scope"]
        _table(f"Osmosis scopes: {res['valid_now']} valid now, {res['plannable']} plannable, "
               f"{res['min_scopes']} needed ({n}+ alphas x {total:,} points each)",
               ["scope", "submitted", "missing for minimum", "alphas with points", "points now", "plan Sharpe",
                "equal-weight Sharpe", "current Sharpe"],
               [[s["scope"], s["submitted"], s["needed"] or "-", s["alphas_now"], f"{s['allocated_now']:,}",
                 (s["combo"] or {}).get("proposed", "-"), (s["combo"] or {}).get("equal", "-"),
                 (s["combo"] or {}).get("current") or "-"] for s in res["scopes"]])
        rows_csv = []
        for s in res["scopes"]:
            rows = sorted(s["rows"], key=lambda r: (-(r.get("points") or 0), -(r["net_sharpe"] or -9)))
            if not s["combo"]:
                continue
            _table(f"{s['scope']}: proposed points (in-sample PnL, after an assumed {res['cost_bps']} bps cost per "
                   f"dollar traded; {s['combo']['days']} days)",
                   ["alpha", "#", "Sharpe", "after-cost", "turnover", "investability keeps", "datasets", "max corr",
                    "points", "note"],
                   [[r["id"], r["local"] or "-", r["sharpe"], r["net_sharpe"], f"{r['turnover']:.0%}",
                     f"{r['ic_keep']:.0%}" if r["ic_keep"] is not None else "n/a", ", ".join(r["datasets"])[:34],
                     r["max_corr"] if r["max_corr"] is not None else "-", f"{r['points']:,}" if r.get("points") else "-",
                     r["excluded"] or r["note"]] for r in rows])
            rows_csv += [(r["id"], s["scope"], r["points"]) for r in rows if r.get("points")]
        if args.csv and rows_csv:
            with open(args.csv, "w") as fh:
                fh.write("alpha,scope,points\n" + "".join(f"{a},{sc},{p}\n" for a, sc, p in rows_csv))
            console.print(f"  wrote {len(rows_csv)} allocations to {esc(args.csv)}")
        short = [f"{s['scope']} needs {s['needed']} more" for s in res["scopes"] if s["needed"]]
        if res["plannable"] < res["min_scopes"]:
            console.print(f"  [yellow]no valid allocation possible yet: {res['plannable']} of {res['min_scopes']} scopes "
                          f"have {n}+ alphas; {', '.join(short) or 'submit alphas in more scopes'}[/yellow]")
        return 0
    if cmd == "pyramids":
        from .engine.routes import pyramid_multipliers
        ctx = eng.context(scope, None)
        pm = pyramid_multipliers(ctx, max_age_s=0 if eng.client else None)
        here = sorted(((k.split("/")[2], v) for k, v in pm.items()
                       if k.startswith(f"{scope['region']}/{scope['delay']}/")), key=lambda t: -t[1])
        _table(f"pyramid multipliers {scope['region']} D{scope['delay']} (higher = less used by BRAIN alphas)",
               ["category", "multiplier"], [[c, m] for c, m in here])
        best = sorted(pm.items(), key=lambda kv: -kv[1])[:12]
        _table("highest multipliers anywhere", ["pyramid", "multiplier"], [[k, v] for k, v in best])
        seen = eng.store.kv_get("observed_themes") or {}
        _table("themes seen in BRAIN checks", ["theme", "multiplier", "region", "delay"],
               [[t.get("name"), t.get("multiplier"), t.get("region"), t.get("delay")] for t in seen.values()])
        return 0
    if cmd == "queue":
        routes = [route] if "--route" in (argv or sys.argv) else ["regular", "power_pool"]
        for rt in routes:
            sc = eng.regular_scope(getattr(args, "region", None), getattr(args, "universe", None), getattr(args, "delay", None)) \
                if rt == "regular" else scope
            th = None if rt == "regular" else theme()
            q = eng.queue(sc, th, route=rt)
            rows, k = [], 0
            for r in q:
                k += 1 if r["queued"] else 0
                st = r.get("stats") or {}
                rows.append([str(k) if r["queued"] else "skip", r["id"], r["brain_id"], st.get("sharpe"), st.get("fitness"),
                             st.get("turnover"), st.get("prod_corr", "-"), st.get("mult", "-"), r["canonical"][:56],
                             "; ".join(([r["why_not"]] if not r["queued"] else []) + (r.get("flags") or []))[:90]])
            title = "production (regular) alphas ready to submit" if rt == "regular" else "Power Pool alphas ready to submit"
            _table(title, ["order", "#", "BRAIN", "Sharpe", "fit", "TO", "prod corr", "mult", "expression", "warnings"], rows)
        return 0
    if cmd == "families":
        from .engine.lifecycle import family_table
        fams = eng.families(scope, theme(), route=route)
        _table(f"idea families, {route} route (one budget per set of data fields)", ["fields", "state", "sims", "queued", "best Sharpe", "why"],
               family_table(fams))
        return 0
    if cmd == "run":
        eng.run(scope, theme(), cycles=args.cycles, n_hypotheses=args.n_hyp, simulate=not args.no_sim,
                check_top=args.check_top, route=route)
        return 0
    if cmd == "report":
        console.print(f"report written to {eng.report(args.top)}")
        return 0
    if cmd == "describe":
        row = eng.store.alpha(args.alpha_id)
        if not row:
            console.print("[red]unknown alpha id[/red]")
            return 1
        console.print(esc(row["canonical"]))
        console.print(esc(row.get("description") or ""))
        if args.apply:
            if not row.get("brain_id"):
                console.print("[red]this alpha has not been simulated on BRAIN yet[/red]")
                return 1
            ok = eng.simulator.set_properties(row["brain_id"], description=row["description"])
            console.print("[green]description set on BRAIN[/green]" if ok else "[red]PATCH failed[/red]")
        return 0
    if cmd == "stats":
        counts = eng.store.q("SELECT status, pp_status, reg_status, COUNT(*) AS n FROM alphas GROUP BY status, pp_status, reg_status")
        _table("alphas", ["status", "power pool", "regular", "count"],
               [[c["status"], c["pp_status"] or "-", c["reg_status"] or "-", c["n"]] for c in counts])
        _table("validator catches (the engine's hallucination memory)", ["code", "subject", "count"],
               [[r["code"], r["subject"][:70], r["count"]] for r in eng.store.top_issues(20)])
        _table("models", ["model", "score", "calls", "fails"],
               [[r["model"], f"{r['mean']:.2f}", r["calls"], r["failures"]] for r in eng.llm.scoreboard()[:10]])
        console.print(f"LLM requests since the 00:00 UTC reset: {eng.llm.budget_used()} (budget {eng.llm.daily_budget})")
        return 0
    if cmd == "load-catalog":
        data = json.loads(open(args.path).read())
        sc = {**scope, **{k: data.get("scope", {}).get(k, scope[k]) for k in ("region", "delay", "universe")}}
        if args.operators:
            eng.store.upsert_operators(json.loads(open(args.operators).read()))
        if data.get("categories"):
            eng.store.kv_set("data_categories", data["categories"])
        if data.get("settings_options"):
            eng.store.kv_set("settings_options", data["settings_options"])
        eng.store.upsert_datasets(data.get("datasets", []), sc)
        eng.store.upsert_fields(data.get("fields", []), sc)
        for ds in {(f.get("dataset") or {}).get("id") for f in data.get("fields", [])}:
            if ds:
                eng.store.mark_dataset_synced(ds, sc, sum(1 for f in data["fields"] if (f.get("dataset") or {}).get("id") == ds))
        console.print(f"loaded {len(data.get('datasets', []))} datasets, {len(data.get('fields', []))} fields for {sc}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

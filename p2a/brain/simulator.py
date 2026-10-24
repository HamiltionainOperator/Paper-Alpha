"""Run simulations on BRAIN: batching, concurrency, polling, results, submission checks."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from ..util import console
from .client import BrainClient, BrainError

SERVER_ERRORS = (500, 502, 503, 504)


@dataclass
class SimJob:
    key: int
    payload: dict
    status: str = "pending"          # pending | done | error
    alpha_id: str | None = None
    message: str | None = None
    error_location: dict | None = None
    alpha: dict | None = None
    extra: dict = field(default_factory=dict)


class QuotaExhausted(Exception):
    pass


class Simulator:
    def __init__(self, client: BrainClient, cfg, log=console.print):
        self.client = client
        self.log = log
        sim = cfg.get("brain.simulation", {}) or {}
        self.max_concurrent = int(sim.get("max_concurrent", 3))
        self.batch_size = max(2, min(10, int(sim.get("multi_batch_size", 10))))
        self.max_wait = float(sim.get("max_wait_s", 2400))
        self.stop_below = int(sim.get("stop_when_remaining_below", 25))
        mode = sim.get("multi_simulation", "auto")
        self.multi = mode is True or (str(mode).lower() == "auto" and client.can_multi_simulate)
        self.check_timeout = float(cfg.get("brain.check_timeout_s", 240))
        self.remaining: int | None = None

    # -- helpers -----------------------------------------------------------------
    def _track_quota(self, r) -> None:
        rem = r.headers.get("X-Ratelimit-Remaining") or r.headers.get("x-ratelimit-remaining")
        if rem is not None:
            try:
                self.remaining = int(float(rem))
            except ValueError:
                pass

    def _units(self, jobs: list[SimJob]) -> deque:
        if not self.multi:
            return deque([[j] for j in jobs])
        groups: dict[tuple, list[SimJob]] = {}
        for j in jobs:
            s = j.payload["settings"]
            groups.setdefault((s.get("instrumentType"), s.get("region"), s.get("delay"), s.get("language")), []).append(j)
        units = deque()
        for g in groups.values():
            for i in range(0, len(g), self.batch_size):
                units.append(g[i:i + self.batch_size])
        return units

    def _fail(self, jobs, message, on_done, location=None):
        for j in jobs:
            j.status, j.message, j.error_location = "error", message, location
            if on_done:
                on_done(j)

    # -- main loop ---------------------------------------------------------------
    def run(self, jobs: list[SimJob], on_done=None) -> list[SimJob]:
        units = self._units(jobs)
        inflight: list[dict] = []
        backoff_until = 0.0
        while units or inflight:
            now = time.time()
            while units and len(inflight) < self.max_concurrent and now >= backoff_until:
                if self.remaining is not None and self.remaining < self.stop_below:
                    self.log(f"[yellow]Simulation quota nearly used ({self.remaining} left) - stopping submissions.[/yellow]")
                    for u in units:
                        self._fail(u, "skipped: daily simulation quota guard", on_done)
                    units.clear()
                    break
                unit = units[0]
                body = unit[0].payload if len(unit) == 1 else [j.payload for j in unit]
                r = self.client.request("POST", "/simulations", json=body, retry_statuses=SERVER_ERRORS)
                self._track_quota(r)
                if r.status_code == 201 and r.headers.get("Location"):
                    units.popleft()
                    inflight.append({"jobs": unit, "location": r.headers["Location"], "next": time.time() + 3,
                                     "started": time.time()})
                    self.log(f"  submitted {len(unit)} simulation(s); in flight: {len(inflight)}")
                elif r.status_code == 429:
                    wait = float(r.headers.get("Retry-After") or 15)
                    backoff_until = time.time() + wait
                    break
                elif r.status_code == 400:
                    units.popleft()
                    detail = r.text[:600]
                    if len(unit) > 1:  # isolate the offending payload
                        for j in reversed(unit):
                            units.appendleft([j])
                    else:
                        self._fail(unit, f"rejected by API: {detail}", on_done)
                else:
                    units.popleft()
                    self._fail(unit, f"HTTP {r.status_code}: {r.text[:300]}", on_done)
            now = time.time()
            for f in list(inflight):
                if f["next"] > now:
                    continue
                try:
                    r = self.client.request("GET", f["location"])
                except Exception as e:  # network trouble: retry later
                    f["next"] = now + 15
                    self.log(f"  [yellow]poll error {e}; retrying[/yellow]")
                    continue
                retry = r.headers.get("Retry-After")
                if r.status_code >= 400:
                    inflight.remove(f)
                    self._fail(f["jobs"], f"poll HTTP {r.status_code}: {r.text[:300]}", on_done)
                elif retry and float(retry) > 0:
                    f["next"] = now + max(float(retry), 2.0)
                    if now - f["started"] > self.max_wait:
                        inflight.remove(f)
                        self._fail(f["jobs"], "timed out waiting for simulation", on_done)
                else:
                    inflight.remove(f)
                    for j in reversed(self._finish(f["jobs"], r.json(), on_done)):
                        units.appendleft([j])  # a failed multi-simulation: run its members one by one
            if inflight:
                nxt = min(f["next"] for f in inflight)
                time.sleep(min(max(nxt - time.time(), 0.5), 10))
            elif units and time.time() < backoff_until:
                time.sleep(min(backoff_until - time.time(), 15))
        return jobs

    def _wait_child(self, child_id: str) -> dict:
        start = time.time()
        while True:
            r = self.client.request("GET", f"/simulations/{child_id}")
            retry = r.headers.get("Retry-After")
            if r.status_code < 400 and not (retry and float(retry) > 0):
                return r.json()
            if time.time() - start > self.max_wait or r.status_code >= 400:
                return {"status": "ERROR", "message": f"child poll failed (HTTP {r.status_code})"}
            time.sleep(max(float(retry or 5), 2.0))

    def _finish(self, jobs: list[SimJob], data: dict, on_done) -> list[SimJob]:
        """Record results; returns the jobs to simulate again on their own (one bad member can fail a whole
        multi-simulation, which says nothing about the others)."""
        children = data.get("children") or []
        if len(jobs) > 1:
            if not children:
                self.log(f"  [yellow]multi-simulation {data.get('status')}: {(data.get('message') or '')[:120]}; "
                         f"retrying its {len(jobs)} members one by one[/yellow]")
                for j in jobs:
                    j.extra["solo"] = True
                return list(jobs)
            child_data = [self._wait_child(c) for c in children]

            def key(code, settings):  # same code may be submitted with different settings in one batch
                s = settings or {}
                return ((code or "").strip(), str(s.get("neutralization")), s.get("decay"), s.get("truncation"),
                        s.get("universe"))

            by_key: dict = {}
            for cd in child_data:
                by_key.setdefault(key(cd.get("regular"), cd.get("settings")), []).append(cd)
            retry = []
            for idx, job in enumerate(jobs):
                bucket = by_key.get(key(job.payload.get("regular"), job.payload.get("settings")))
                cd = bucket.pop(0) if bucket else None
                if cd is None and idx < len(child_data):
                    cd = child_data[idx]  # children come back in submission order
                cd = cd or {"status": "ERROR", "message": "missing child simulation"}
                failed = (cd.get("status") or "").upper() not in ("COMPLETE", "WARNING")
                if failed and not cd.get("message") and not job.extra.get("solo"):
                    # a bare FAIL inside a batch can be collateral damage from another member: try it alone once
                    job.extra["solo"] = True
                    retry.append(job)
                    continue
                self._finish_single(job, cd)
                if on_done:
                    on_done(job)
            if retry:
                self.log(f"  [yellow]{len(retry)} member(s) of a multi-simulation failed without a message; "
                         "retrying them one by one[/yellow]")
            return retry
        self._finish_single(jobs[0], data)
        if on_done:
            on_done(jobs[0])
        return []

    def _finish_single(self, job: SimJob, data: dict) -> None:
        status = (data.get("status") or "").upper()
        job.alpha_id = data.get("alpha")
        if status in ("COMPLETE", "WARNING") and job.alpha_id:
            try:
                job.alpha = self.client.get_json(f"/alphas/{job.alpha_id}")
                job.status = "done"
                job.message = data.get("message")
            except BrainError as e:
                job.status, job.message = "error", f"could not fetch alpha: {e}"
        else:
            job.status = "error"
            job.message = data.get("message") or status or "unknown simulation failure"
            job.error_location = data.get("location")

    # -- after simulation ---------------------------------------------------------
    def check(self, alpha_id: str) -> dict | None:
        """GET /alphas/{id}/check: correlation + theme checks used before submission (read-only)."""
        deadline = time.time() + self.check_timeout
        data = None
        while time.time() < deadline:
            r = self.client.request("GET", f"/alphas/{alpha_id}/check")
            retry = r.headers.get("Retry-After")
            if retry and float(retry) > 0:
                time.sleep(float(retry))
                continue
            if r.status_code >= 400:
                return None
            data = r.json()
            checks = (data.get("is") or {}).get("checks") or []
            if not any(c.get("result") == "PENDING" for c in checks):
                break
            time.sleep(10)
        return data

    def correlations(self, alpha_id: str, kind: str = "prod", attempts: int = 12) -> dict | None:
        """GET /alphas/{id}/correlations/{prod|self}: BRAIN computes these on request, in seconds (the submission
        check only reports them once they exist). prod -> {max, min, records: [[lo, hi, n production alphas]]};
        self -> {max, min, records: [[id, name, ..., correlation, sharpe, ...]]}."""
        for _ in range(attempts):
            r = self.client.request("GET", f"/alphas/{alpha_id}/correlations/{kind}")
            retry = r.headers.get("Retry-After")
            if r.status_code == 200 and r.text.strip() and not (retry and float(retry) > 0):
                try:
                    return r.json()
                except ValueError:
                    return None
            if r.status_code >= 400 and r.status_code != 429:
                return None
            time.sleep(float(retry or 2))
        return None

    def recordset(self, alpha_id: str, name: str, attempts: int = 15) -> dict | None:
        """GET /alphas/{id}/recordsets/{name} (pnl, daily-pnl, yearly-stats, ...); waits while BRAIN computes it."""
        for _ in range(attempts):
            r = self.client.request("GET", f"/alphas/{alpha_id}/recordsets/{name}")
            retry = r.headers.get("Retry-After")
            if r.status_code == 200 and r.text.strip() and not (retry and float(retry) > 0):
                return r.json()
            if r.status_code >= 400 and r.status_code != 429:
                return None
            time.sleep(float(retry or 2))
        return None

    def refresh_alpha(self, alpha_id: str) -> dict | None:
        try:
            return self.client.get_json(f"/alphas/{alpha_id}")
        except BrainError:
            return None

    def set_properties(self, alpha_id: str, name: str | None = None, description: str | None = None,
                       tags: list[str] | None = None) -> bool:
        body: dict = {}
        if name:
            body["name"] = name
        if tags is not None:
            body["tags"] = tags
        if description:
            body["regular"] = {"description": description}
        r = self.client.request("PATCH", f"/alphas/{alpha_id}", json=body)
        return r.status_code < 400

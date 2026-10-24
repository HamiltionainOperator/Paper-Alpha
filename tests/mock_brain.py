"""A mock of the BRAIN API reproducing the response shapes observed on the live platform."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tests.helpers import load_catalog_fixture, load_operators, FIXTURES

TOKEN = "mock-jwt-token"
PP_THEME = {"id": "ZDXgJ5B", "name": "D1 Power Pool Oct`26 2", "multiplier": 1.0}


class State:
    def __init__(self):
        fx = load_catalog_fixture()
        self.categories = fx["categories"]
        self.datasets = fx["datasets"]
        self.fields = fx["fields"]
        self.operators = load_operators()
        self.options = json.loads((FIXTURES / "settings_options.json").read_text())
        self.persona_pending = True
        self.persona_needed_polls = 1
        self.persona_posts = 0
        self.sims: dict[str, dict] = {}
        self.alphas: dict[str, dict] = {}
        self.checks: dict[str, int] = {}
        self.n = 0
        self.post_count = 0
        self.lock = threading.Lock()
        self.requests: list[str] = []


def _stats_for(code: str, settings: dict) -> dict:
    h = int(hashlib.md5((code + json.dumps(settings, sort_keys=True)).encode()).hexdigest(), 16)
    if "ts_mean" in code:
        bucket = 0          # meets the Power Pool numbers
    elif "ts_rank" in code:
        bucket = 1          # decent Sharpe but turnover too high
    elif "ts_zscore" in code:
        bucket = 2          # strongly negative Sharpe -> sign-flip candidate
    else:
        bucket = h % 4
    sharpe = {0: 1.45, 1: 0.85, 2: -1.3, 3: 0.2}[bucket]
    turnover = 0.12 if bucket != 1 else 0.82
    return {"sharpe": sharpe, "fitness": round(sharpe * 0.7, 2), "turnover": turnover, "returns": 0.05,
            "drawdown": 0.03, "margin": 0.0006, "longCount": 1400, "shortCount": 1450}


def make_alpha(alpha_id: str, code: str, settings: dict) -> dict:
    st = _stats_for(code, settings)
    # like BRAIN: for an alpha that qualifies for the Power Pool, the checks it is exempt from show WARNING, not FAIL
    exempt_fail = "WARNING" if st["sharpe"] >= 1.0 and st["turnover"] <= 0.7 else "FAIL"
    checks = [
        {"name": "LOW_SHARPE", "result": "PASS" if st["sharpe"] >= 1.58 else exempt_fail, "limit": 1.58, "value": st["sharpe"]},
        {"name": "LOW_FITNESS", "result": exempt_fail, "limit": 1, "value": st["fitness"]},
        {"name": "LOW_TURNOVER", "result": "PASS", "limit": 0.01, "value": st["turnover"]},
        {"name": "HIGH_TURNOVER", "result": "PASS" if st["turnover"] <= 0.7 else "FAIL", "limit": 0.7, "value": st["turnover"]},
        {"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS", "limit": 0.5, "value": 0.9},
        {"name": "POWER_POOL_CORRELATION", "result": "PENDING"},
        {"result": "PENDING", "name": "MATCHES_THEMES", "themes": [PP_THEME]},
    ]
    classifications = [{"id": "POWER_POOL:POWER_POOL_ELIGIBLE", "name": "Power Pool Alpha"}] if st["sharpe"] >= 1.0 else []
    return {"id": alpha_id, "type": "REGULAR", "settings": settings, "regular": {"code": code, "operatorCount": 3},
            "status": "UNSUBMITTED", "classifications": classifications, "is": {**st, "checks": checks}}


class Handler(BaseHTTPRequestHandler):
    state: State = None

    def log_message(self, *a):
        pass

    def _send(self, status=200, body=None, headers=None):
        payload = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authed(self) -> bool:
        return f"t={TOKEN}" in (self.headers.get("Cookie") or "")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"null") if n else None

    def _page(self, items, qs):
        limit = int(qs.get("limit", ["50"])[0])
        offset = int(qs.get("offset", ["0"])[0])
        if limit > 50:
            return self._send(400, {"limit": ["Ensure this value is less than or equal to 50."]})
        self._send(200, {"count": len(items), "results": items[offset:offset + limit]})

    # -- verbs ---------------------------------------------------------------------
    def do_OPTIONS(self):
        if urlparse(self.path).path == "/simulations":
            return self._send(200, {"actions": {"POST": {"settings": {"children": self.state.options}}}})
        self._send(404, {"detail": "Not found."})

    def do_GET(self):
        st = self.state
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = u.path
        st.requests.append(f"GET {path}")
        if path == "/authentication":
            return self._send(200, {"user": {"id": "U1"}, "permissions": ["MULTI_SIMULATION"]}) if self._authed() else self._send(204)
        if not self._authed():
            return self._send(401, {"detail": "Incorrect authentication credentials."})
        if path == "/operators":
            return self._send(200, st.operators)
        if path.startswith("/operators/"):
            name = path.rsplit("/", 1)[1]
            return self._send(200, {"id": name, "content": [
                {"type": "TEXT", "value": f"<p><b>{name}</b> documentation.</p>"},
                {"type": "SIMULATION_EXAMPLE", "value": {"settings": {"region": "USA"}, "regular": "rank(-ts_delta(close, 5))"}}]})
        if path == "/data-categories":
            return self._send(200, st.categories)
        if path == "/data-sets":
            return self._page(st.datasets, qs)
        if path == "/data-fields":
            items = st.fields
            if "dataset.id" in qs:
                items = [f for f in items if f["dataset"]["id"] == qs["dataset.id"][0]]
            if "search" in qs:
                items = [f for f in items if qs["search"][0].lower() in (f["id"] + f["description"]).lower()]
            return self._page(items, qs)
        if path.startswith("/data-fields/"):
            fid = path.rsplit("/", 1)[1]
            f = next((x for x in st.fields if x["id"] == fid), None)
            if not f:
                return self._send(404, {"detail": "Not found."})
            return self._send(200, {**f, "data": [{"region": "USA", "delay": 1, "universe": "TOP3000", "coverage": f["coverage"]}]})
        if path == "/tutorials":
            return self._send(200, {"count": 1, "next": None, "results": [
                {"id": "t1", "title": "Data", "category": "Data", "pages": [{"id": "vector-datafields", "title": "Vector Data Fields"}]}]})
        if path.startswith("/tutorial-pages/"):
            return self._send(200, {"id": "vector-datafields", "title": "Vector Data Fields", "content": [
                {"type": "TEXT", "value": "<p>Vector fields must be aggregated with vec_avg or vec_sum before use.</p>"},
                {"type": "SIMULATION_EXAMPLE", "value": {"regular": "rank(vec_avg(nws18_ssc))"}}]})
        if path.startswith("/simulations/"):
            sid = path.rsplit("/", 1)[1]
            with st.lock:
                sim = st.sims.get(sid)
                if sim is None:
                    return self._send(404, {"detail": "Not found."})
                sim["polls"] += 1
                if sim["polls"] < 2:
                    return self._send(200, {"progress": 0.5}, {"Retry-After": "0.2"})
                return self._send(200, sim["result"])
        if path.startswith("/alphas/") and path.endswith("/check"):
            aid = path.split("/")[2]
            with st.lock:
                st.checks[aid] = st.checks.get(aid, 0) + 1
                if st.checks[aid] == 1:
                    return self._send(200, {}, {"Retry-After": "0.2"})
                alpha = st.alphas[aid]
                checks = [c for c in alpha["is"]["checks"] if c["name"] not in ("POWER_POOL_CORRELATION", "MATCHES_THEMES")]
                checks += [{"name": "POWER_POOL_CORRELATION", "result": "PASS", "limit": 0.5, "value": 0.21},
                           {"result": "PASS", "name": "MATCHES_THEMES", "themes": [PP_THEME]}]
                alpha["is"]["checks"] = checks
                return self._send(200, {"is": {"checks": checks}})
        if path.startswith("/alphas/"):
            aid = path.split("/")[2]
            return self._send(200, st.alphas[aid]) if aid in st.alphas else self._send(404, {"detail": "Not found."})
        self._send(404, {"detail": "Not found."})

    def do_POST(self):
        st = self.state
        u = urlparse(self.path)
        st.requests.append(f"POST {u.path}")
        if u.path == "/authentication":
            auth = self.headers.get("Authorization", "")
            email = base64.b64decode(auth.split(" ", 1)[1]).decode().split(":")[0] if auth.startswith("Basic ") else ""
            if email.startswith("persona") and st.persona_pending:
                st.persona_pending = False
                return self._send(401, {"detail": "persona"}, {"WWW-Authenticate": "persona",
                                                               "Location": "/authentication/persona?inquiry=inq_1"})
            if not email:
                return self._send(401, {"detail": "INVALID_CREDENTIALS"})
            return self._send(201, {"user": {"id": "U1"}, "permissions": ["MULTI_SIMULATION", "CONSULTANT"]},
                              {"Set-Cookie": f"t={TOKEN}; Path=/"})
        if u.path.startswith("/authentication/persona"):
            st.persona_posts += 1
            if st.persona_posts < st.persona_needed_polls:
                return self._send(401, {"detail": "INQUIRY_NOT_COMPLETED"})
            return self._send(201, {"user": {"id": "U1"}, "permissions": ["MULTI_SIMULATION"]}, {"Set-Cookie": f"t={TOKEN}; Path=/"})
        if not self._authed():
            return self._send(401, {"detail": "Incorrect authentication credentials."})
        if u.path == "/simulations":
            body = self._body()
            with st.lock:
                st.post_count += 1
                if st.post_count == 1:  # first submission hits the concurrency limit
                    return self._send(429, {"detail": "CONCURRENT_SIMULATION_LIMIT_EXCEEDED"}, {"Retry-After": "0.3"})
                items = body if isinstance(body, list) else [body]
                for it in items:
                    if "regular" not in it or "settings" not in it:
                        return self._send(400, {"regular": ["This field is required."]})
                children = []
                for it in items:
                    st.n += 1
                    sid, aid = f"S{st.n}", f"A{st.n}"
                    if "hump(" in it["regular"]:  # pretend the simulator rejects this one
                        res = {"id": sid, "status": "ERROR", "message": "Incompatible unit for input of \"hump\"",
                               "location": {"line": 1, "start": 0, "end": 6}, "regular": it["regular"]}
                    else:
                        st.alphas[aid] = make_alpha(aid, it["regular"], it["settings"])
                        res = {"id": sid, "status": "COMPLETE", "alpha": aid, "regular": it["regular"],
                               "settings": it["settings"]}
                    st.sims[sid] = {"polls": 1, "result": res}
                    children.append(sid)
                if isinstance(body, list):
                    st.n += 1
                    pid = f"P{st.n}"
                    st.sims[pid] = {"polls": 0, "result": {"id": pid, "status": "COMPLETE", "children": children}}
                    loc = f"/simulations/{pid}"
                else:
                    loc = f"/simulations/{children[0]}"
                    st.sims[children[0]]["polls"] = 0
            return self._send(201, None, {"Location": loc, "X-Ratelimit-Remaining": "4999"})
        self._send(404, {"detail": "Not found."})

    def do_PATCH(self):
        u = urlparse(self.path)
        if not self._authed():
            return self._send(401, {})
        aid = u.path.split("/")[2]
        body = self._body() or {}
        if aid in self.state.alphas and "regular" in body:
            self.state.alphas[aid]["regular"]["description"] = body["regular"].get("description")
            return self._send(200, self.state.alphas[aid])
        self._send(404, {})


def start() -> tuple[ThreadingHTTPServer, State, str]:
    state = State()
    handler = type("BoundHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state, f"http://127.0.0.1:{server.server_address[1]}"

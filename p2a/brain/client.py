"""HTTP client for the WorldQuant BRAIN API (https://api.worldquantbrain.com)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from urllib.parse import urljoin

import requests

from ..config import Config

RETRY_STATUSES = (429, 500, 502, 503, 504)


class BrainError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response


class AuthRequired(BrainError):
    pass


class BrainClient:
    def __init__(self, cfg: Config, credentials: tuple[str, str] | None = None, interactive: bool = True):
        self.base = cfg.get("brain.api_base", "https://api.worldquantbrain.com").rstrip("/")
        self.min_interval = float(cfg.get("brain.min_request_interval_s", 1.0))
        self.max_retries = int(cfg.get("brain.max_retries", 6))
        self.session_path = cfg.data_dir / cfg.get("brain.session_file", "session.json")
        self.credentials = credentials
        self.interactive = interactive
        auth = cfg.get("brain.auth", {}) or {}
        self.auto_open = bool(auth.get("auto_open_browser", True))
        self.browser_app = auth.get("browser_app", "Google Chrome") or ""
        self.persona_interval = float(auth.get("persona_poll_interval_s", 15))
        self.persona_timeout = float(auth.get("persona_timeout_s", 600))
        self.permissions: list[str] = []
        self.pending_persona: str | None = None
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "paper2alpha/0.1", "Accept": "application/json"})
        self._last = 0.0
        self._load_session()

    # -- session persistence -------------------------------------------------
    def _load_session(self) -> None:
        try:
            data = json.loads(self.session_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for c in data.get("cookies", []):
            self.s.cookies.set(c["name"], c["value"], domain=c.get("domain") or "", path=c.get("path") or "/")
        self.permissions = data.get("permissions", [])
        self.pending_persona = data.get("pending_persona")

    def _save_session(self) -> None:
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.s.cookies]
        self.session_path.write_text(json.dumps({"cookies": cookies, "permissions": self.permissions,
                                                 "pending_persona": self.pending_persona, "saved_at": time.time()}))
        os.chmod(self.session_path, 0o600)

    def url(self, path: str) -> str:
        return path if path.startswith("http") else self.base + path

    # -- authentication --------------------------------------------------------
    def authenticated(self) -> bool:
        try:
            r = self.s.get(self.url("/authentication"), timeout=30)
        except requests.RequestException:
            return False
        if r.status_code == 200:
            try:
                self.permissions = r.json().get("permissions", self.permissions)
            except ValueError:
                pass
            return True
        return False

    def login(self) -> None:
        if not self.credentials:
            raise AuthRequired("BRAIN credentials missing: set BRAIN_EMAIL and BRAIN_PASSWORD in .env "
                               "(or create ~/.brain_credentials as [\"email\", \"password\"]).")
        if self.pending_persona:  # biometric sign-in started earlier: finish it if the user completed it
            link, self.pending_persona = self.pending_persona, None
            r = self.s.post(link, auth=self.credentials, timeout=60)
            if r.status_code in (200, 201):
                self._finish_login(r)
                return
        r = self.s.post(self.url("/authentication"), auth=self.credentials, timeout=60)
        if self._is_persona(r):
            link = urljoin(r.url, r.headers.get("Location", ""))
            if self.auto_open:
                r = self._persona_flow(link)
            elif self.interactive and sys.stdin.isatty():
                print(f"\nBRAIN asks for biometric sign-in. Open this link in your browser and complete it:\n  {link}\n")
                input("Press Enter once you have completed it... ")
                r = self.s.post(link, auth=self.credentials, timeout=60)
            else:
                self.pending_persona = link
                self._save_session()
                raise AuthRequired("Biometric sign-in required. Open this link in your browser and complete it, "
                                   f"then run `python3 -m p2a login`:\n  {link}")
        if r.status_code not in (200, 201):
            detail = r.text[:300]
            raise AuthRequired(f"BRAIN login failed (HTTP {r.status_code}): {detail}", r)
        self._finish_login(r)

    @staticmethod
    def _is_persona(r: requests.Response) -> bool:
        return r.status_code == 401 and r.headers.get("WWW-Authenticate", "").lower() == "persona"

    def open_in_browser(self, url: str) -> bool:
        """Open a URL in the configured browser (Chrome by default); returns True if it was launched."""
        if self.browser_app and sys.platform == "darwin":
            try:
                if subprocess.run(["open", "-a", self.browser_app, url], capture_output=True, timeout=30).returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            return webbrowser.open(url)
        except webbrowser.Error:
            return False

    def _persona_flow(self, link: str) -> requests.Response:
        """Biometric sign-in: open the link in the browser, then re-post it every few seconds (the
        completion call from the BRAIN API docs) until BRAIN confirms the verification."""
        opened = self.open_in_browser(link)
        where = self.browser_app or "your browser"
        print(f"\nBRAIN requires biometric sign-in. {'Opened' if opened else 'Please open'} this link in {where} "
              f"and complete it:\n  {link}\nChecking every {self.persona_interval:g}s "
              f"(gives up after {self.persona_timeout / 60:g} min)...", flush=True)
        start, checks = time.time(), 0
        while time.time() - start < self.persona_timeout:
            time.sleep(self.persona_interval)
            checks += 1
            try:
                r = self.s.post(link, auth=self.credentials, timeout=60)
            except requests.RequestException as e:
                print(f"  check {checks}: network error ({type(e).__name__}), retrying", flush=True)
                continue
            if r.status_code in (200, 201):
                print(f"  biometric verification confirmed after {int(time.time() - start)}s", flush=True)
                return r
            print(f"  not verified yet (check {checks}, {int(time.time() - start)}s, HTTP {r.status_code})", flush=True)
        self.pending_persona = link
        self._save_session()
        raise AuthRequired(f"Biometric sign-in was not completed within {self.persona_timeout / 60:g} min. "
                           f"Finish it at {link} and run `python3 -m p2a login`.")

    def _finish_login(self, r: requests.Response) -> None:
        try:
            self.permissions = (r.json() or {}).get("permissions", [])
        except ValueError:
            self.permissions = []
        self._save_session()

    def ensure_auth(self) -> None:
        if not self.authenticated():
            self.login()

    @property
    def can_multi_simulate(self) -> bool:
        return "MULTI_SIMULATION" in self.permissions

    # -- requests --------------------------------------------------------------
    def request(self, method: str, path: str, *, retry_statuses=RETRY_STATUSES, timeout: float = 90,
                throttle: bool = True, **kw) -> requests.Response:
        reauthed = False
        for attempt in range(self.max_retries + 1):
            if throttle:
                gap = self.min_interval - (time.time() - self._last)
                if gap > 0:
                    time.sleep(gap)
            try:
                r = self.s.request(method, self.url(path), timeout=timeout, **kw)
            except requests.RequestException:
                if attempt == self.max_retries:
                    raise
                time.sleep(min(60, 2 ** attempt))
                continue
            finally:
                self._last = time.time()
            if r.status_code == 401 and not reauthed and self.credentials:
                reauthed = True
                self.login()
                continue
            if r.status_code in retry_statuses and attempt < self.max_retries:
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else min(90, 3 * 2 ** attempt)
                time.sleep(max(wait, 1.0))
                continue
            return r
        return r

    def get_json(self, path: str, params: dict | None = None):
        r = self.request("GET", path, params=params)
        if r.status_code >= 400:
            raise BrainError(f"GET {path} -> HTTP {r.status_code}: {r.text[:300]}", r)
        return r.json()

    def paginate(self, path: str, params: dict, page_size: int = 50, max_items: int | None = None):
        offset = 0
        while True:
            data = self.get_json(path, {**params, "limit": page_size, "offset": offset})
            results = data.get("results", []) if isinstance(data, dict) else data
            yield from results
            offset += len(results)
            total = data.get("count", 0) if isinstance(data, dict) else 0
            if not results or offset >= total or (max_items and offset >= max_items):
                break

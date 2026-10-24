"""OpenRouter client behaviour against a mock server with misbehaving free models."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from p2a.config import Config
from p2a.llm import BudgetExhausted, OpenRouter
from p2a.store import Store

FREE = {"prompt": "0", "completion": "0"}
TEXT = {"input_modalities": ["text"], "output_modalities": ["text"]}
MODELS = [
    {"id": "a/ratelimited:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072, "supported_parameters": ["response_format"]},
    {"id": "b/badparam:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072, "supported_parameters": ["response_format", "reasoning"]},
    {"id": "c/truncated:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072, "supported_parameters": []},
    {"id": "d/garbage:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072, "supported_parameters": []},
    {"id": "e/daily:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072, "supported_parameters": []},
    {"id": "f/paid", "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "architecture": TEXT, "context_length": 131072},
    {"id": "g/music:free", "pricing": FREE, "architecture": {"input_modalities": ["text"], "output_modalities": ["text", "audio"]}, "context_length": 131072},
    {"id": "h/content-safety:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072},
    {"id": "i/tiny-ctx:free", "pricing": FREE, "architecture": TEXT, "context_length": 4096},
    {"id": "j/agentic:free", "pricing": FREE, "architecture": TEXT, "context_length": 131072, "supported_parameters": []},
]
GOOD = {"candidates": [{"expression": "rank(x)"}]}


class Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"data": MODELS})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        Handler.seen.append((model, "response_format" in body, "reasoning" in body))
        chat = lambda content: self._send(200, {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10}})
        if model.startswith("a/"):
            return self._send(429, {"error": {"code": 429, "message": "Provider returned error",
                                              "metadata": {"raw": "temporarily rate-limited upstream"}}})
        if model.startswith("b/"):
            if "response_format" in body:
                return self._send(400, {"error": {"code": 400, "message": "response_format not supported"}})
            return chat(json.dumps(GOOD))
        if model.startswith("c/"):
            return chat('{"candidates": [{"expression": "rank(a)"}, {"expression": "rank(b)"}, {"expres')
        if model.startswith("d/"):
            return chat("I am sorry, I cannot help with that.")
        if model.startswith("j/"):
            return self._send(403, {"error": {"code": 403, "message": "j/agentic:free is only available on agentic harnesses."}})
        if model.startswith("e/"):
            return self._send(429, {"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}})
        self._send(500, {"error": {"code": 500, "message": "unexpected"}})


def has_candidates(obj):
    return None if isinstance(obj, dict) and obj.get("candidates") else "no candidates"


class OpenRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def client(self, prefer, budget=20):
        tmp = Path(tempfile.mkdtemp())
        cfg = Config({"llm": {"base_url": self.url, "prefer_patterns": prefer, "daily_request_budget": budget,
                              "per_minute_limit": 100, "exclude_patterns": ["safety"], "min_context": 32000,
                              "reasoning_effort": "low"}}, tmp)
        return OpenRouter(cfg, Store(tmp / "db.sqlite"), "test-key", log=lambda *a, **k: None)

    def test_model_filtering(self):
        ids = {m.id for m in self.client([]).models()}
        self.assertEqual(ids, {"a/ratelimited:free", "b/badparam:free", "c/truncated:free", "d/garbage:free", "e/daily:free",
                               "j/agentic:free"})

    def test_permanently_unavailable_model_is_blocked(self):
        llm = self.client(["agentic", "ratelimited", "badparam"])
        res = llm.chat_json([{"role": "user", "content": "x"}], "generate", check=has_candidates, max_attempts=1)
        self.assertEqual(res.model, "b/badparam:free")  # 403 and 429 did not use up the single attempt
        self.assertNotIn("j/agentic:free", {m.id for m in llm.models()})

    def test_rate_limit_then_param_fallback(self):
        Handler.seen.clear()
        llm = self.client(["ratelimited", "badparam"])
        res = llm.chat_json([{"role": "user", "content": "x"}], "generate", check=has_candidates, max_attempts=4)
        self.assertEqual(res.model, "b/badparam:free")
        self.assertEqual(res.obj, GOOD)
        self.assertIn(("b/badparam:free", True, True), Handler.seen)    # first try with optional params
        self.assertIn(("b/badparam:free", False, False), Handler.seen)  # retried without them
        self.assertIn("a/ratelimited:free", llm.cooldown)

    def test_garbage_then_truncated_salvage(self):
        llm = self.client(["garbage", "truncated"])
        res = llm.chat_json([{"role": "user", "content": "x"}], "generate", check=has_candidates)
        self.assertEqual(res.model, "c/truncated:free")
        self.assertEqual([c["expression"] for c in res.obj["candidates"]], ["rank(a)", "rank(b)"])
        board = {r["model"]: r for r in llm.scoreboard()}
        self.assertLess(board["d/garbage:free"]["mean"], board["c/truncated:free"]["mean"])

    def test_daily_limit_and_budget(self):
        with self.assertRaises(BudgetExhausted):
            self.client(["daily"]).chat_json([{"role": "user", "content": "x"}], "generate")
        llm = self.client(["badparam"], budget=2)
        llm.chat_json([{"role": "user", "content": "x"}], "generate", check=has_candidates)  # uses 2 requests
        with self.assertRaises(BudgetExhausted):
            llm.chat_json([{"role": "user", "content": "x"}], "generate")


if __name__ == "__main__":
    unittest.main()

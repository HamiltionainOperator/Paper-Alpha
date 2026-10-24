import tempfile
import unittest
from pathlib import Path

from p2a.config import Config
from p2a.engine.playbook import field_tags, playbook_text, rules_for

PLAYBOOK = """
rules:
  - {id: reduce_vectors, tags: [vector], rule: "reduce a vector field before ranking", template: "rank(vec_avg({x}))"}
  - {id: sparse_form, tags: [sparse], rule: "carry a sparse field forward or trade it as an event", template: "rank(ts_backfill({x}, 252))"}
  - {id: smooth_news, tags: [news, event], rule: "smooth noisy daily news", template: "rank(ts_mean({x}, 5))"}
  - {id: normalise, tags: [any], rule: "normalise cross-sectionally"}
uniqueness:
  - {technique: risk-set neutralization, how: "use CROWDING or SLOW", template: ""}
fitness:
  - {technique: decay, how: "raise decay for fast signals", template: ""}
"""


class PlaybookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "pb.yaml"
        path.write_text(PLAYBOOK)
        self.cfg = Config({"playbook": {"path": str(path), "rules_in_prompt": 3}}, Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_field_tags_mark_vectors_sparse_and_news(self):
        self.assertIn("vector", field_tags({"id": "x", "type": "VECTOR"}))
        self.assertIn("sparse", field_tags({"id": "board_centrality", "description": "director network centrality"}))
        self.assertIn("sparse", field_tags({"id": "x", "description": "", "date_coverage": 0.3}))
        self.assertIn("event", field_tags({"id": "x", "category": "news"}))
        self.assertNotIn("sparse", field_tags({"id": "close", "description": "daily close price", "date_coverage": 1.0}))

    def test_rules_that_fit_the_fields_come_first(self):
        vec = {"id": "tone", "type": "VECTOR", "category": "news", "description": "news tone"}
        ids = [r["id"] for r in rules_for(self.cfg, [vec])]
        self.assertEqual(ids[0], "smooth_news")                    # two matching tags
        self.assertIn("reduce_vectors", ids)
        self.assertNotIn("sparse_form", ids)                       # only rules for these fields, plus general ones
        text = playbook_text(self.cfg, [vec])
        self.assertIn("rank(vec_avg({x}))", text)
        self.assertIn("Lower production correlation", text)
        self.assertIn("Raise fitness", text)


if __name__ == "__main__":
    unittest.main()

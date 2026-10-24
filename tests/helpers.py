import json
from pathlib import Path

from p2a.fastexpr import Catalog, FieldInfo, Rules

FIXTURES = Path(__file__).parent / "fixtures"

TYPE_OVERRIDES = {
    "densify": {"params": {"x": "GROUP"}, "returns": "GROUP"},
    "bucket": {"returns": "GROUP"},
    "group_cartesian_product": {"returns": "GROUP"},
}


def load_operators():
    return json.loads((FIXTURES / "operators.json").read_text())


def load_catalog_fixture():
    return json.loads((FIXTURES / "catalog_usa_d1_top3000.json").read_text())


def field_from_api(f: dict) -> FieldInfo:
    return FieldInfo(id=f["id"], type=f.get("type", "MATRIX"), dataset=(f.get("dataset") or {}).get("id"),
                     category=(f.get("category") or {}).get("id"), coverage=f.get("coverage"),
                     description=f.get("description", ""))


def make_catalog(lenient: bool = False) -> Catalog:
    rules = Rules(type_overrides=TYPE_OVERRIDES)
    fx = load_catalog_fixture()
    lookup = (lambda name: FieldInfo(id=name)) if lenient else None
    return Catalog(load_operators(), rules, [field_from_api(f) for f in fx["fields"]], field_lookup=lookup)

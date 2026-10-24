"""Everything a generation/refinement step needs for one simulation scope."""
from __future__ import annotations

from dataclasses import dataclass

from ..brain.catalog import CatalogSync
from ..config import Config
from ..fastexpr import Catalog, Constraints, Rules
from ..llm import OpenRouter
from ..store import Store
from .memory import Memory
from .themes import ThemeSpec


@dataclass
class Context:
    cfg: Config
    store: Store
    llm: OpenRouter
    sync: CatalogSync
    memory: Memory
    rules: Rules
    scope: dict
    theme: ThemeSpec | None
    constraints: Constraints | None
    catalog: Catalog
    options: dict
    route: str = "power_pool"        # power_pool | regular (see routes.py)

    @property
    def defaults(self) -> dict:
        return self.cfg.section("default_settings")

    @property
    def pp(self) -> dict:
        return self.cfg.section("power_pool")

    @property
    def regular(self) -> dict:
        return self.cfg.section("regular")

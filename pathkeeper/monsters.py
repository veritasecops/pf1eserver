"""The bundled Archives of Nethys Pathfinder First Edition monster catalog."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def monsters():
    return json.loads((Path(__file__).parent / "data" / "monsters.json").read_text(encoding="utf-8"))

"""Administration index for AoN's nonmagical equipment branches."""
from functools import lru_cache
from decimal import Decimal
from fractions import Fraction
import re
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .armor import table_armor
from .weapons import table_weapons

GROUPS = ("Weapons", "Armor", "Special Materials", "Miscellaneous")


@lru_cache
def published_equipment():
    return json.loads((Path(__file__).parent / "data" / "equipment_index.json").read_text())


def identity(url):
    parts = urlsplit(url)
    names = parse_qs(parts.query).get("ItemName", ())
    if parts.hostname == "www.aonprd.com" and names:
        return parts.path.casefold(), names[0].casefold()
    return None


@lru_cache
def equipment_bindings():
    return {reference: (kind, key) for kind, entries in (("weapons", table_weapons()), ("armor", table_armor()))
            for key, item in entries.items() if (reference := identity(item.get("url", "")))}


def equipment_entries(catalog):
    result = {**published_equipment(), **catalog.get("equipment_index", {})}
    bindings = equipment_bindings()
    for key, entry in result.items():
        binding = bindings.get(identity(entry["url"]))
        if not binding:
            continue
        kind, item_key = binding
        live = catalog[kind].get(item_key)
        if not live:
            continue
        cost = live.get("cost")
        weight = live.get("weight")
        result[key] = {
            **entry, "name": live["name"], "url": live.get("url", ""), "enabled": live.get("enabled", True),
            "cost_text": f"{cost / 100:g} gp" if cost is not None else live.get("cost_text") or entry["cost_text"],
            "weight_text": f"{weight:g} lb." if weight is not None else live.get("weight_text") or entry["weight_text"],
            "editor_kind": kind, "editor_key": item_key,
        }
    return result


COIN_VALUES = {"cp": 1, "sp": 10, "gp": 100, "pp": 1000}
COIN_PRICE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(cp|sp|gp|pp)(?:\s+\d+)?", re.I)
POUNDS = re.compile(
    r"(?:(\d[\d,]*)[- ])?(?:(\d+)/([1-9]\d*)|(\d[\d,]*(?:\.\d+)?))\s*lbs?\.?(?:\s+\d+)?", re.I
)


def sheet_gear(catalog):
    """Adapt the two AoN inventory catalogs to the sheet's purchase format."""
    result = {}
    for key, entry in equipment_entries(catalog).items():
        if entry["group"] not in {"Special Materials", "Miscellaneous"}:
            continue
        material = entry["group"] == "Special Materials"
        cost_text, weight_text = entry["cost_text"], entry["weight_text"]
        price = COIN_PRICE.fullmatch(cost_text.strip())
        cost = Decimal(price[1].replace(",", "")) * COIN_VALUES[price[2].lower()] if price and not material else None
        weight = POUNDS.fullmatch(weight_text.strip())
        pounds = None
        if weight:
            whole, numerator, denominator, decimal = weight.groups()
            pounds = (float(decimal.replace(",", "")) if decimal else
                      int((whole or "0").replace(",", "")) + float(Fraction(int(numerator), int(denominator))))
        result[key] = {
            **entry, "kind": "material" if material else "misc",
            "cost": int(cost) if cost is not None and cost == cost.to_integral_value() else None,
            "weight": pounds,
        }
    return result

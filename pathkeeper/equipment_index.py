"""Administration index for AoN's nonmagical equipment branches."""
from functools import lru_cache
from decimal import Decimal
from fractions import Fraction
import re
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .armor import ARMOR_CATEGORIES, table_armor
from .weapons import WEAPON_CATEGORIES, table_weapons

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


def live_equipment(entry, kind, key, item):
    cost, weight = item.get("cost"), item.get("weight")
    if kind == "weapons":
        category = WEAPON_CATEGORIES.get(item.get("category"))
        entry = {**entry, "categories": [category] if category else [],
                 "proficiencies": item.get("proficiencies", [item.get("group")])}
    return {
        **entry, "name": item["name"], "url": item.get("url", ""), "source": item.get("source", ""), "enabled": item.get("enabled", True),
        "cost_text": f"{cost / 100:g} gp" if cost is not None else item.get("cost_text") or entry["cost_text"],
        "weight_text": f"{weight:g} lb." if weight is not None else item.get("weight_text") or entry["weight_text"],
        "editor_kind": kind, "editor_key": key,
    }


def equipment_entries(catalog):
    overrides = {key: item for key, item in catalog.get("equipment_index", {}).items()
                 if not key.startswith("miscellaneous-pathfinder-chronicles-")
                 and not any(label.casefold() == "pathfinder chronicles" for label in item["categories"])}
    result = {**published_equipment(), **overrides}
    bindings = equipment_bindings()
    live_catalogs = {kind: catalog.get(kind, {}) for kind in ("weapons", "armor")}
    current_bindings = {reference: (kind, key) for kind, items in live_catalogs.items()
                        for key, item in items.items() if (reference := identity(item.get("url", "")))}
    represented = set()
    for key, entry in result.items():
        if entry["group"] not in {"Weapons", "Armor"}:
            continue
        reference = identity(entry["url"])
        binding = bindings.get(reference) or current_bindings.get(reference)
        if not binding:
            continue
        kind, item_key = binding
        if item := live_catalogs[kind].get(item_key):
            represented.add(binding)
            result[key] = live_equipment(entry, kind, item_key, item)
    for kind, items in live_catalogs.items():
        for key, item in items.items():
            if (kind, key) in represented:
                continue
            labels = WEAPON_CATEGORIES if kind == "weapons" else ARMOR_CATEGORIES
            category = labels.get(item.get("category"))
            entry = {"group": "Weapons" if kind == "weapons" else "Armor",
                     "categories": [category] if category else [], "cost_text": "",
                     "weight_text": "", "details": ""}
            entry_key = f"live-{kind}-{key}"
            while entry_key in result:
                entry_key = "live-" + entry_key
            result[entry_key] = live_equipment(entry, kind, key, item)
    return result


COIN_VALUES = {"cp": 1, "sp": 10, "gp": 100, "pp": 1000}
COIN_PRICE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(cp|sp|gp|pp)(?:\s+\d+)?", re.I)
POUNDS = re.compile(
    r"(?:(\d[\d,]*)[- ])?(?:(\d+)/([1-9]\d*)|(\d[\d,]*(?:\.\d+)?))\s*lbs?\.?(?:\s+\d+)?", re.I
)


def equipment_categories(entries, group):
    return sorted({label for item in entries.values() if item["group"] == group for label in item["categories"]})


def sheet_equipment(catalog):
    entries = equipment_entries(catalog)
    items = {**catalog["weapons"], **catalog.get("armor", {}), **sheet_gear(catalog, entries)}
    categories = {}
    for entry in entries.values():
        if key := entry.get("editor_key"):
            categories.setdefault(key, set()).update(entry["categories"])
    for key, labels in categories.items():
        items[key] = {**items[key], "categories": sorted(labels)}
    return items, {group: equipment_categories(entries, group) for group in GROUPS}


def sheet_gear(catalog, entries=None):
    """Adapt the two AoN inventory catalogs to the sheet's purchase format."""
    result = {}
    for key, entry in (equipment_entries(catalog) if entries is None else entries).items():
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

"""Project backpack entries onto stable sheet gear slots."""
from decimal import Decimal
import re
import secrets

from fastapi import HTTPException

GEAR_SLOTS = 256
LEGACY_GEAR_SLOTS = 56


def available_slot(items, values):
    used = {item.get("gear_row") for item in items}
    slot = next((row for row in range(GEAR_SLOTS) if row not in used and not values.get(f"gear.{row}.name")), None)
    if slot is None:
        raise HTTPException(422, "The gear table is full. Remove an item from the backpack first.")
    return slot


def gear_label(item):
    return item.get("gear_label") or f"{item['name']} × {item['quantity']}"


def gear_weight(item, size):
    if "gear_weight" in item:
        return item["gear_weight"]
    catalog = item.get("catalog", {})
    if catalog.get("weight") is None:
        return catalog.get("weight_text") or ""
    scale = Decimal("0.5") if item.get("combat") and size.casefold() == "small" else Decimal(1)
    return format(Decimal(str(catalog["weight"])) * item["quantity"] * scale, "f")


def project_backpack(character, values):
    for item in (character.play_data or {}).get("backpack", []):
        if (row := item.get("gear_row")) is None:
            continue
        values[f"gear.{row}.name"] = gear_label(item)
        values[f"gear.{row}.weight"] = gear_weight(item, values.get("size", ""))


def seed_backpack(character, values, catalog):
    """Retain legacy Gear rows and link recognized weapon and armor stacks."""
    from .character_weapons import inventory

    data = character.play_data or {}
    items = [dict(item) for item in data.get("backpack", [])]
    managed = inventory(character, values, catalog)
    starting = {f"{item['name']} × {item['quantity']}": item
                for item in (character.sheet_data or {}).get("computed", {}).get("equipment", [])}
    for row in range(LEGACY_GEAR_SLOTS):
        label = values.get(f"gear.{row}.name", "").strip()
        if not label or any(item.get("gear_row") == row for item in items):
            continue
        match = re.fullmatch(r"(.+) × ([1-9][0-9]{0,6})", label)
        name, quantity = (match[1], int(match[2])) if match else (label, 1)
        entry = next((entry for entry in managed if entry.get("gear_row") == row), None)
        catalog_item = (entry or {}).get("item") or starting.get(label, {})
        link = None
        if entry and entry.get("row") is not None:
            link = {"kind": "weapon", "row": entry["row"]}
        elif entry and entry.get("armor_row") is not None:
            link = {"kind": "armor", "row": entry["armor_row"]}
        item = next((item for item in items if item.get("gear_row") is None
                     and item["name"].casefold() == name.casefold() and item["quantity"] == quantity), None)
        if item is None:
            item = {"id": secrets.token_hex(16), "name": name, "quantity": quantity,
                    "unit_cp": catalog_item.get("cost") or 0}
            items.append(item)
        if entry and entry.get("id") and "catalog_id" not in item:
            item["catalog_id"] = entry["id"]
            item["agreed_unit_price"] = entry.get("agreed_unit_price")
        if catalog_item and "catalog" not in item:
            item["catalog"] = catalog_item
        if link:
            item["combat"] = link
        item.update(gear_row=row, gear_label=label, gear_weight=values.get(f"gear.{row}.weight", ""),
                    notes=item.get("notes") or values.get(f"gear.{row}.notes", ""))
    for item in items:
        if item.get("gear_row") is None:
            item["gear_row"] = available_slot(items, values)
            if "catalog" not in item:
                item["gear_weight"] = "0"
    character.play_data = {**data, "backpack": items, "backpack_gear_version": 1,
                           "weapon_inventory": [entry for entry in managed
                                                if entry.get("row") is not None or entry.get("armor_row") is not None]}

"""Published NPC templates and their projection into editable campaign sheets."""
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import re
from types import SimpleNamespace

from .class_catalog import casting_class_keys, class_key_for_name
from .deluxe_sheet import sheet_values
from .equipment_effects import persist_effects
from .gear_backpack import LEGACY_GEAR_SLOTS, seed_backpack
from .models import Character
from .rule_catalog import character_catalog

CATEGORIES = ("Core class", "Prestige class", "NPC class", "Iconic", "Animal companion")
WIZARD_SCHOOLS = {
    "abjurer", "conjurer", "diviner", "enchanter", "evoker", "illusionist",
    "necromancer", "transmuter", "universalist",
}
PAGE_SIZE = 30
COMMA = re.compile(r",\s*(?![^()]*\))")
SIGN = r"[+–−-]?\s*\d+"
SPELL_LEVEL = re.compile(r"\b([0-9])(?:st|nd|rd|th)?\s*(?:\(([^()]*)\))?\s*[—–-]\s*")
ARMOR_NAME = re.compile(
    r"\b(?:armor|full plate|breastplate|chain shirt|chainmail|scale mail|splint mail|banded mail|half-plate|hide|leather|padded)\b",
    re.I,
)
SHIELD_NAME = re.compile(r"\b(?:shield|buckler)\b", re.I)


@lru_cache(maxsize=1)
def entries():
    path = Path(__file__).with_name("data") / "npc_codex.json"
    return json.loads(path.read_text(encoding="utf-8"))


def browse(params):
    category = params.get("category", "")
    if category not in CATEGORIES:
        category = ""
    search = params.get("q", "").strip()[:100]
    try:
        page = int(params.get("page", "1"))
    except ValueError:
        page = 1
    matches = [(key, item) for key, item in entries().items()
               if (not category or item["category"] == category)
               and search.casefold() in " ".join([item["name"], item["ancestry"], class_label(item)]).casefold()]
    matches.sort(key=lambda pair: (pair[1]["name"].casefold(), pair[1]["level"]))
    pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    return dict(items=matches[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], categories=CATEGORIES,
                category=category, search=search, page=page, pages=pages, total=len(matches))


def class_label(item):
    return " / ".join(f"{name.replace(' Of ', ' of ')} {level}" for name, level in item["classes"]) or "Animal companion"


def class_id(name, catalog):
    base = re.split(r" of ", name, maxsplit=1, flags=re.I)[0]
    return "wizard" if base.casefold() in WIZARD_SCHOOLS else class_key_for_name(base, catalog)


def read_number(text, label=""):
    match = re.search(rf"{label}\s*({SIGN})", text) if label else re.match(rf"\s*({SIGN})", text)
    if match:
        return int(match[1].replace("–", "-").replace("−", "-").replace(" ", ""))
    return None


def equipment_rows(values, offense, statistics):
    for row, match in enumerate(re.finditer(
        r"(?:^|\s+or\s+|,\s+)([^(),]+?)\s+([+−–-]\d+(?:/[+−–-]\d+)*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
        " or ".join(offense.get(label, "") for label in ("Melee", "Ranged")), re.I
    )):
        if row == 6:
            break
        name, attack, damage = match.groups()
        name = re.sub(r"^(?:[A-Z] ){1,4}(?=[a-z])", "", name.strip())
        critical = re.search(r"/\s*((?:\d+[–-]\d+)?(?:/?×\d+)?)(?=\s|$)", damage)
        fields = {"name": name, "attack": attack, "damage": damage}
        if critical and critical[1]:
            fields["critical"] = critical[1]
            fields["damage"] = damage[:critical.start()] + damage[critical.end():]
        for key, value in fields.items():
            values[f"weapon.{row}.{key}"] = value
    gear = ", ".join(statistics.get(label, "") for label in ("Combat Gear", "Other Gear"))
    coins = {coin: [] for coin in ("pp", "gp", "sp", "cp")}
    inventory = []
    for name in COMMA.split(gear):
        name = name.strip(" .,;")
        if not name:
            continue
        if match := re.fullmatch(r"([\d,]+) (pp|gp|sp|cp)", name):
            coins[match[2]].append(int(match[1].replace(",", "")))
        else:
            inventory.append(name)
    for coin, amounts in coins.items():
        if amounts:
            values[f"money.{coin}"] = str(sum(amounts))
    for row, label in enumerate(inventory[:LEGACY_GEAR_SLOTS]):
        qty = re.fullmatch(r"(.+?) \(([1-9]\d*)\)", label)
        values[f"gear.{row}.name"] = (f"{qty[1]} × {qty[2]}" if qty else label)[:200]
    return inventory


def spells(item, values, casters, catalog):
    spell_notes = []
    for label, text in item["sections"].get("Offense", []):
        if "Spell" not in label:
            continue
        spell_notes.append(f"{label} {text}")
        if not label.endswith(("Spells Prepared", "Spells Known")):
            continue
        base = label.split(" Spells ", 1)[0]
        key = class_id(base, catalog)
        prefix = "spell"
        if key in casters[1:]:
            prefix = f"spellbook.{key}"
        for label, field in (("CL", "caster_level"), ("concentration", "concentration")):
            if (number := read_number(text, label)) is not None:
                if prefix == "spell":
                    values[field] = str(number)
                else:
                    values.setdefault("published_caster_levels", {}).setdefault(key, {})[field] = number
        splits = list(SPELL_LEVEL.finditer(text))
        for index, match in enumerate(splits):
            end = splits[index + 1].start() if index + 1 < len(splits) else len(text)
            names = re.sub(r"(?<=[a-z])D\b", "", text[match.end():end]).strip(" ,;")
            values[f"{prefix}.{match[1]}.list"] = "\n".join(COMMA.split(names))
            if prefix == "spell":
                if daily := re.search(r"(\d+)\s*/\s*day", match[2] or ""):
                    values[f"spell.{match[1]}.daily"] = daily[1]
                dc_values = set(re.findall(r"\bDC\s*(\d+)", names))
                if len(dc_values) == 1:
                    values[f"spell.{match[1]}.dc"] = dc_values.pop()
    if spell_notes:
        values["spell_notes"] = "\n".join(spell_notes)[:5000]


def published_skills(text, values, targets, catalog):
    names = {entry["name"].casefold(): key for key, entry in catalog["skills"].items()}
    used_specialties = set()
    for piece in COMMA.split(text):
        match = re.match(rf"([A-Za-z ]+?)\s*(?:\(([^()]*)\))?\s+({SIGN})\b", piece.strip())
        if not match:
            continue
        name, detail, bonus = match.groups()
        if name.casefold() == "knowledge" and detail:
            keys = [names.get(f"knowledge ({topic.strip().casefold()})") for topic in detail.split(",")]
        else:
            key = names.get(name.casefold())
            if key in {"craft", "perform", "profession"} and detail:
                if key in used_specialties:
                    key += "-2"
                used_specialties.add(key)
                values[f"skill.{key}.specialty"] = detail[:200]
            keys = [key]
        for key in filter(None, keys):
            targets[f"skill.{key}.total"] = read_number(bonus)


def make_character(item, campaign, catalog):
    classes = [(class_id(name, catalog), level) for name, level in item["classes"]]
    known = bool(classes) and all(key for key, _ in classes)
    section_text = [section + "\n" + "\n".join(f"{label} {text}" for label, text in fields)
                    for section, fields in item["sections"].items()]
    source = f"Pathfinder RPG NPC Codex, p. {item['page']}"
    identity = f"CR {item['cr']} · XP award {item['xp_award']:,}" if item["cr"] else f"Effective druid level {item['companion_level']}"
    if item.get("druid_only"):
        identity += " (druid only)"
    notes = "\n\n".join([f"{source}\n{identity}\n{class_label(item)}", *section_text])
    character = Character(name=item["name"], ancestry=item["ancestry"], class_name=class_label(item),
                          level=item["level"], campaign_id=campaign.id, owner_id=campaign.owner_id,
                          is_npc=True, notes=notes[:10000])
    data = {"calculation_version": 1, "alignment": item["alignment"], "size": item["size"],
            "hp.total": str(item["hp"]), "hp.current": str(item["hp"])}
    if any(key for key, _ in classes):
        data["class_levels"] = [[key, level] for key, level in classes if key]
    if not known:
        data["manual_class_progression"] = True

    for ability, score in item["scores"].items():
        data[f"ability.{ability}.score"] = str(score)
    defense = dict(item["sections"]["Defense"])
    offense = dict(item["sections"]["Offense"])
    statistics = dict(item["sections"]["Statistics"])
    header = dict(item["sections"].get("Identity", []))
    if deity := next((name.split(" Of ", 1)[1] for name, _ in item["classes"]
                      if name.startswith(("Cleric Of ", "Paladin Of "))), ""):
        from .deities import deity_key
        data["deity"] = deity_key(deity, catalog.get("deities", {})) or deity
    if languages := statistics.get("Languages"):
        data["languages"] = languages[:5000]
    speed = read_number(offense.get("Speed", ""))
    if speed is not None:
        data["speed.armor"] = str(speed)
        data["speed.base"] = str(speed)
    for movement in ("fly", "burrow", "climb", "swim"):
        if (movement_speed := read_number(offense.get("Speed", ""), rf"\b{movement}")) is not None:
            data[f"speed.{movement}"] = str(movement_speed)
    if (sr := read_number(" ".join(defense.values()), r"\bSR")) is not None:
        data["resistance.spell"] = str(sr)
    if damage_reduction := re.search(r"\bDR\s+(\d+)\s*/\s*([^;,]+)", " ".join(defense.values())):
        data["resistance.0.damage"], data["resistance.0.bypass"] = damage_reduction.groups()

    attacks = statistics["Base Atk"]
    data["bab"] = str(read_number(attacks))
    saves = defense["Fort"]
    targets = {
        "initiative.total": read_number(header.get("Init", "")),
        "save.fortitude.total": read_number(saves),
        "save.reflex.total": read_number(saves, r"\bRef"),
        "save.will.total": read_number(saves, r"\bWill"),
        "cmb.total": read_number(attacks, r"\bCMB"),
        "cmd.total": read_number(attacks, r"\bCMD"),
    }
    if not known:
        for name, ability in (("fortitude", "con"), ("reflex", "dex"), ("will", "wis")):
            score = item["scores"][ability]
            data[f"save.{name}.base"] = str((targets[f"save.{name}.total"] or 0) - (score - 10) // 2)
    armor = re.search(r"\s*\((.*)\)", defense["AC"])
    components = {name.casefold(): read_number(amount) for amount, name in
                  re.findall(r"([+–−-]\s*\d+)\s+(armor|shield|natural|deflection|dodge)\b", armor[1] if armor else "", re.I)}
    for label in ("natural", "deflection", "dodge"):
        if label in components:
            data[f"ac.{label}"] = str(components[label])
    inventory = equipment_rows(data, offense, statistics)
    for row, label in enumerate(("armor", "shield")):
        if not components.get(label):
            continue
        pattern = ARMOR_NAME if label == "armor" else SHIELD_NAME
        name = next((name for name in inventory if pattern.search(name)
                     and not re.match(r"(?i)(?:wands?|scrolls?|potions?|oils?) of\b", name)), "")
        if not name:
            continue
        data[f"armor.{row}.name"] = name[:200]
        data[f"armor.{row}.type"] = label
        data[f"armor.{row}.bonus"] = str(components[label])
        data[f"armor.{row}.equipped"] = "1"
    targets["ac.total"] = read_number(defense["AC"])
    casters = casting_class_keys(catalog, {key: level for key, level in classes if key})
    spells(item, data, casters, catalog)
    feats = COMMA.split(statistics.get("Feats", ""))
    for row, feat in enumerate(filter(None, feats[:56])):
        data[f"feature.{row}"] = feat.strip()[:500]
    published_skills(statistics.get("Skills", ""), data, targets, catalog)

    character.play_data = data
    owner = SimpleNamespace(name="")
    initial = sheet_values(character, owner, progression_catalog=catalog)
    seed_backpack(character, initial, character_catalog(character))
    initial = sheet_values(character, owner, progression_catalog=catalog)
    if speed is not None:
        initial["speed.armor"] = str(speed)
    ac_delta = targets["ac.total"] - int(initial["ac.total"])
    for key, target in targets.items():
        if target is None:
            continue
        base = Decimal(initial[key] or "0")
        misc = key.removesuffix(".total") + ".misc"
        initial[misc] = str(Decimal(initial[misc] or "0") + target - base)
        character.play_data[misc] = initial[misc]
    character.play_data.update(persist_effects(character, initial))
    for field, label in (("ac.touch", "touch"), ("ac.flat", "flat-footed")):
        target = read_number(defense["AC"], label)
        if target is not None:
            offset = target - int(initial[field]) - ac_delta
            if offset:
                character.play_data.setdefault("published_ac_adjustments", {})[field] = offset
    return character

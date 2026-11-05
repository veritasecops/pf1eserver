"""Validation and presentation for the administration class editor."""
import re

from fastapi import HTTPException

from .class_catalog import BONUS_FEATS, GROUPS, class_profile
from .level_up import feature_choices
from .pf1_data import ABILITIES, CLASSES
from .rule_catalog import class_skills
from .security import field, integer
from .ui import render
from .weapons import safe_weapon_url

SAVES = ("fortitude", "reflex", "will")
SPELL_FIELDS = {"slots": "Daily slots", "known": "Spells known", "prepared": "Spells prepared"}


def editor(ctx, record, key, form=None, errors=()):
    catalog = record.data
    profile = class_profile(catalog, key)
    first_swap, frequency, lower = profile["spell_swap"] or (0, 0, False)
    values = {
        **profile,
        "swap_first": first_swap, "swap_frequency": frequency, "swap_lower": lower,
        "automatic_feats": "\n".join(profile["automatic_feats"]),
        **{save: value for save, value in zip(SAVES, profile["saves"])},
    }
    for index, row in enumerate(profile["levels"], 1):
        prefix = f"level.{index}."
        values.update({prefix + name: value for name, value in zip(SAVES, row["saves"])})
        values[prefix + "bab"] = row["bab"]
        values[prefix + "features"] = row["features"]
        values[prefix + "choices"] = "\n".join(feature_choices(row)) if index > 1 else ""
        values[prefix + "statistics"] = "\n".join(f"{label}={value}" for label, value in row.get("statistics", {}).items())
        for column in SPELL_FIELDS:
            values[prefix + column] = ", ".join(f"{level}={count}" for level, count in row.get(column, {}).items())
    if form is not None:
        values.update(form)
        values["swap_lower"] = form.get("swap_lower") == "on"
    response = render(ctx, "class_edit.html", title="Edit " + profile["name"], key=key, values=values,
                      version=record.version, abilities=ABILITIES, groups=GROUPS, bonus_feats=BONUS_FEATS,
                      skills=sorted(catalog["skills"].items(), key=lambda entry: entry[1]["name"]),
                      selected_skills=form.getlist("class_skills") if form is not None else class_skills(catalog, key),
                      saves=SAVES, spell_fields=SPELL_FIELDS, errors=errors)
    if errors:
        response.status_code = 422
    return response


def lines(form, key, limit, length=150):
    entries = [line.strip() for line in field(form, key, 5000, required=False).splitlines() if line.strip()]
    if len(entries) > limit or any(len(line) > length for line in entries) or len(set(entries)) != len(entries):
        raise HTTPException(422, f"Enter up to {limit} different lines in {key}, with up to {length} characters per line.")
    return entries


def spell_counts(form, key):
    values = {}
    raw = field(form, key, 150, required=False)
    if raw:
        for token in raw.split(","):
            match = re.fullmatch(r"([0-9])\s*=\s*([0-9]{1,2})", token.strip())
            if not match or match[1] in values:
                raise HTTPException(422, f"Use distinct spell levels and counts in {key}, such as 0=4, 1=2.")
            values[match[1]] = int(match[2])
    return values


def parse_class(form, key, catalog):
    old = class_profile(catalog, key)
    item = {
        "name": field(form, "name", 100),
        "url": field(form, "url", 1000, required=False),
        "choices": field(form, "choices", 1000, required=False),
        "group": field(form, "group", 20),
        "hd": integer(form, "hd", 1, 20),
        "ranks": integer(form, "ranks", 1, 20),
        "bab": integer(form, "bab", 0, 20),
        "saves": [integer(form, name, 0, 20) for name in SAVES],
        "wealth_dice": integer(form, "wealth_dice", 0, 20),
        "casting_ability": field(form, "casting_ability", 3, required=False),
        "caster_delay": integer(form, "caster_delay", 0, 19),
        "book": integer(form, "book", 0, 20),
        "starting_book": integer(form, "starting_book", 0, 20),
        "bonus_feat": field(form, "bonus_feat", 20, required=False),
        "automatic_feats": lines(form, "automatic_feats", 15, 100),
    }
    if item["url"] and not safe_weapon_url(item["url"]):
        raise HTTPException(422, "Use a safe HTTP or HTTPS reference link.")
    if item["group"] not in GROUPS or item["bonus_feat"] not in BONUS_FEATS or item["casting_ability"] not in {"", *ABILITIES}:
        raise HTTPException(422, "Choose a valid class group, bonus feat type, and spellcasting ability.")
    if item["hd"] not in {4, 6, 8, 10, 12, 20}:
        raise HTTPException(422, "Choose a standard Hit Die.")
    first_swap = integer(form, "swap_first", 0, 20)
    frequency = integer(form, "swap_frequency", 0, 20)
    if bool(first_swap) != bool(frequency) or first_swap == 1 or (first_swap and not item["casting_ability"]):
        raise HTTPException(422, "Set spell replacement to zero for both fields, or choose a first level of 2 or higher and a frequency for a spellcaster.")
    item["spell_swap"] = [first_swap, frequency, form.get("swap_lower") == "on"] if first_swap else None
    aliases = list(dict.fromkeys([*old.get("aliases", []), old["name"]])) if old["name"] != item["name"] else old.get("aliases", [])
    item["aliases"] = aliases
    for other in CLASSES.keys() - {key}:
        profile = class_profile(catalog, other)
        if item["name"].casefold() in {name.casefold() for name in (CLASSES[other]["name"], profile["name"], *profile.get("aliases", []))}:
            raise HTTPException(422, "Another class already uses that name.")
    item["levels"] = []
    for level in range(1, 21):
        prefix = f"level.{level}."
        row = {
            "bab": integer(form, prefix + "bab", 0, 40),
            "saves": [integer(form, prefix + save, 0, 40) for save in SAVES],
            "features": field(form, prefix + "features", 1000, required=False),
            **{column: spell_counts(form, prefix + column) for column in SPELL_FIELDS},
        }
        statistics = {}
        for line in lines(form, prefix + "statistics", 20):
            label, sep, value = line.partition("=")
            if not sep or not label.strip() or not value.strip() or label.strip() in statistics:
                raise HTTPException(422, f"Level {level} statistics need distinct labels, one label=value pair per line.")
            statistics[label.strip()] = value.strip()
        row["statistics"] = statistics
        if level > 1:
            row["choices"] = lines(form, prefix + "choices", 15)
        if (row["slots"] or row["known"] or row["prepared"]) and not item["casting_ability"]:
            raise HTTPException(422, "Choose a spellcasting ability for a class with spell progression.")
        if item["levels"]:
            previous = item["levels"][-1]
            for column, label in SPELL_FIELDS.items():
                if any(row[column].get(spell_level, -1) < count for spell_level, count in previous[column].items()):
                    raise HTTPException(422, f"{label} cannot decrease or disappear at level {level}.")
        item["levels"].append(row)
    first = item["levels"][0]
    if item["book"] and any(row["known"] for row in item["levels"]):
        raise HTTPException(422, "Use either spellbook additions or a spells-known table for advancement.")
    if first_swap and not any(row["known"] for row in item["levels"]):
        raise HTTPException(422, "Spell replacement requires a spells-known table.")
    if item["starting_book"] and not first["slots"]:
        raise HTTPException(422, "Starting spellbook entries require first-level spell slots.")
    if item["book"] and not any(row["slots"] for row in item["levels"]):
        raise HTTPException(422, "Spellbook progression requires spell slots.")
    item["caster"] = item["casting_ability"] if first["slots"] or first["known"] else ""
    skills = set(form.getlist("class_skills"))
    if skills - catalog["skills"].keys():
        raise HTTPException(422, "Choose skills from the catalog.")
    return item, skills

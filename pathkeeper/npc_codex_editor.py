"""Validate edits to NPC Codex templates before they reach campaign sheets."""
from collections import Counter
import re

from fastapi import HTTPException

from .npc_codex import CATEGORIES, class_id, read_number
from .pf1_data import ABILITIES, ALIGNMENTS
from .security import field, integer
from .sheet_calculations import SIZE_MODIFIERS

REQUIRED_FIELDS = {"Defense": ("AC", "Fort"), "Offense": ("Speed",), "Statistics": ("Base Atk",)}
SECTIONS = ("Identity", "Defense", "Offense", "Statistics", "Alternate statistics", "Special Abilities")
STRUCTURED_FIELDS = {("Defense", "hp"), ("Statistics", "Str")}
EDITED_BY_INPUT = {(section, label.casefold()) for section, label in STRUCTURED_FIELDS}
CHALLENGE_RATING = re.compile(r"0|1/[2-8]|[1-9][0-9]?")
CLASS_LINE = re.compile(r"(.+?)\s+([1-9][0-9]?)")


def editor_values(item):
    values = {key: item[key] for key in ("name", "ancestry", "category", "level", "alignment", "size", "hp", "cr")}
    values.update(companion_level=item.get("companion_level", ""), xp_award=item.get("xp_award", ""),
                  classes="\n".join(f"{name} {level}" for name, level in item["classes"]))
    values.update(item["scores"])
    for section in SECTIONS:
        values[section] = "\n".join(f"{label}: {text}" for label, text in item["sections"].get(section, [])
                                    if (section, label) not in STRUCTURED_FIELDS)
    return values


def parse_section(form, section, original_rows):
    rows = []
    originals = Counter(label.casefold() for label, _ in original_rows)
    seen = Counter()
    for line in field(form, section, 7000, required=False).splitlines():
        if not line.strip():
            continue
        label, separator, value = (part.strip() for part in line.partition(":"))
        if not separator or not label or not value or len(label) > 80 or len(value) > 5000:
            raise HTTPException(422, f"Enter one Label: value per line in {section}.")
        key = label.casefold()
        seen[key] += 1
        if seen[key] > max(1, originals[key]) or (section, key) in EDITED_BY_INPUT:
            raise HTTPException(422, f"{label} is already recorded in {section}.")
        rows.append([label, value])
    fields = dict(rows)
    for label in REQUIRED_FIELDS.get(section, ()):
        if not fields.get(label):
            raise HTTPException(422, f"Keep the {label} line in {section}.")
    return rows


def parse_entry(form, original, catalog):
    companion = "companion_level" in original
    name = field(form, "name", 150)
    ancestry = field(form, "ancestry", 100)
    alignment = field(form, "alignment", 2)
    size = field(form, "size", 12)
    if alignment not in ALIGNMENTS or size.casefold() not in SIZE_MODIFIERS:
        raise HTTPException(422, "Choose a valid alignment and size.")
    level = integer(form, "level", 1, 20)
    hp = integer(form, "hp", 1, 10000)
    scores = {key: integer(form, key, 1, 100) for key in ABILITIES}
    item = {**original, "name": name, "ancestry": ancestry, "level": level, "alignment": alignment,
            "size": size.capitalize(), "hp": hp, "scores": scores}
    if companion:
        effective = field(form, "companion_level", 8).replace("-", "–")
        if not re.fullmatch(r"[1-9][0-9]?(?:–[1-9][0-9]?)?", effective):
            raise HTTPException(422, "Enter an effective druid level or range from 1 to 20.")
        limits = list(map(int, effective.split("–")))
        if not 1 <= limits[0] <= limits[-1] <= 20:
            raise HTTPException(422, "Enter an effective druid level or range from 1 to 20.")
        item["companion_level"] = effective
    else:
        cr = field(form, "cr", 5)
        category = field(form, "category", 30)
        if not CHALLENGE_RATING.fullmatch(cr) or category not in CATEGORIES[:-1]:
            raise HTTPException(422, "Enter a valid CR and character category.")
        classes, seen = [], set()
        for line in field(form, "classes", 300).splitlines():
            match = CLASS_LINE.fullmatch(line.strip())
            if not match or len(match[1]) > 80:
                raise HTTPException(422, "Enter a class name followed by its level on each line.")
            class_name = " ".join(match[1].split())
            key = class_id(class_name, catalog) or class_name.casefold()
            if key in seen:
                raise HTTPException(422, "Enter each class once.")
            seen.add(key)
            classes.append([class_name, int(match[2])])
        if sum(count for _, count in classes) != level or len(" / ".join(f"{key} {count}" for key, count in classes)) > 100:
            raise HTTPException(422, "Class levels must add up to the NPC’s level. Use up to 100 characters for the class summary.")
        item.update(category=category, cr=cr, xp_award=integer(form, "xp_award", 0, 1000000000), classes=classes)

    current = editor_values(original)
    sections = {
        section: list(original["sections"].get(section, []))
        if form.get(section, "").replace("\r\n", "\n").strip() == current[section].strip()
        else parse_section(form, section, original["sections"].get(section, []))
        for section in SECTIONS
    }
    defense = dict(sections["Defense"])
    statistics = dict(sections["Statistics"])
    speed = dict(sections["Offense"])["Speed"]
    for text, labels, message in (
        (defense["AC"], ("", "touch", "flat-footed"), "Enter AC, touch AC, and flat-footed AC on the AC line."),
        (defense["Fort"], ("", r"\bRef", r"\bWill"), "Enter Fortitude, Reflex, and Will totals on the Fort line."),
        (statistics["Base Atk"], ("", r"\bCMB", r"\bCMD"), "Enter base attack bonus, CMB, and CMD on the Base Atk line."),
        (speed, ("",), "Begin the Speed line with the land speed in feet."),
    ):
        if re.search(r"\d{7,}", text) or any(read_number(text, label) is None for label in labels):
            raise HTTPException(422, message)
    hp_text = dict(original["sections"]["Defense"])["hp"]
    sections["Defense"] = [row for row in sections["Defense"] if row[0] != "hp"]
    sections["Defense"].insert(1, ["hp", re.sub(r"^\s*\d+", str(hp), hp_text) if level == original["level"] else str(hp)])
    score_text = ", ".join(f"{key.title()} {value}" for key, value in scores.items())
    sections["Statistics"] = [row for row in sections["Statistics"] if row[0] != "Str"]
    sections["Statistics"].insert(0, ["Str", score_text.removeprefix("Str ")])
    item["sections"] = {section: rows for section, rows in sections.items() if rows}
    return item

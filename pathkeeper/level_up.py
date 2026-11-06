"""Plan and apply a single level in a character's existing class."""
import re
from decimal import Decimal

from .advancement import XP_TRACKS, eligible, track
from .deluxe_sheet import SAVES, sheet_values, skill_rows
from .equipment_effects import persist_effects
from .models import Campaign, User
from .class_catalog import class_key, class_profile
from .pf1_data import ABILITIES
from .rule_catalog import character_catalog, class_skills, equipment, load_catalog
from .weapons import safe_weapon_url
from .trait_rules import fighter_weapon_groups, trained_weapon_groups, weapon_group_name

CLASS_INDEX = "https://www.aonprd.com/Classes.aspx"
FEAT_INDEX = "https://www.aonprd.com/Feats.aspx"
CHOICES = re.compile(
    r"^(?:rage power|versatile performance|bonus (?:combat )?feat|bloodline feat|teamwork feat|"
    r"combat style feat|discovery|grand discovery|cruelty|mercy|fiendish boon|divine bond|hunter.s bond|"
    r"arcanist exploit|maneuver training|weapon training|weapon mastery|gun training|investigator talent|"
    r"utility wild talent|infusion\b(?! specialization)|expanded element|magus arcana|mesmerist trick|"
    r"bold stare|ki power|style strike|ninja trick|focus power|implements \d|revelation|phrenic amplification|"
    r"(?:\d(?:st|nd|rd|th) )?favored (?:enemy|terrain)|rogue talent|finesse training|rogue.s edge|"
    r"weapon expertise|hex\b|(?:second|third|fourth|final) aspect|slayer talent|vigilante talent|"
    r"social talent|summon familiar|precise companion|bonus trick|metakinetic master|"
    r"swashbuckler weapon mastery|final revelation|implement mastery)$"
)
# Features with scaling numbers or parentheticals still use the same prompts.
FEATURE_SUFFIX = re.compile(r"\s+(?:\([^)]*\)|[+]?\d.*)$")


def feature_choices(level):
    features = re.split(r",\s*(?![^()]*\))", level["features"]) if level["features"] else []
    return level.get("choices", [
        feature for feature in features
        if CHOICES.fullmatch(feature.lower()) or CHOICES.fullmatch(FEATURE_SUFFIX.sub("", feature.lower()))
    ])


def available(character, campaign, catalog):
    return eligible(character, campaign) and class_key(character, catalog) is not None


def plan(ctx, character):
    db = ctx.db
    campaign = db.get(Campaign, character.campaign_id) if character.campaign_id else None
    current_catalog = load_catalog(db)
    class_id = class_key(character, current_catalog)
    if not class_id or not eligible(character, campaign):
        return None
    owner = db.get(User, character.owner_id)
    gm = db.get(User, campaign.owner_id) if campaign else None
    values = sheet_values(character, owner, campaign, gm)
    profile = class_profile(current_catalog, class_id)
    target = character.level + 1
    previous, current = profile["levels"][target - 2:target]
    sheet_input = (character.sheet_data or {}).get("input", {})
    bab = current["bab"] - previous["bab"]
    if class_id == "vigilante" and sheet_input.get("vigilante_specialization") == "avenger":
        bab = 1
    features = re.split(r",\s*(?![^()]*\))", current["features"]) if current["features"] else []
    choices = ["General feat"] if target % 2 else []
    choices.extend(feature_choices(current))
    known = {key: count - previous.get("known", {}).get(key, 0) for key, count in current.get("known", {}).items()
             if count > previous.get("known", {}).get(key, 0)}
    catalog = character_catalog(character)
    trained = set(class_skills(catalog, class_id, sheet_input.get("expert_skills", ())))
    rows = [
        (key, item["name"] + (" (second specialty)" if key.endswith("-2") else ""),
         key.removesuffix("-2") in trained, int(Decimal(values[f"skill.{key}.ranks"] or 0)),
         safe_weapon_url(current_catalog["skills"].get(key.removesuffix("-2"), item).get("url", "")),
         item.get("enabled", True))
        for key, item in skill_rows(catalog)
    ]
    feats = current_catalog["feats"]
    owned = {
        (entry["name"], entry.get("choice", ""))
        for entry in (character.sheet_data or {}).get("computed", {}).get("feats", [])
    }
    owned.update((name, "") for name in (character.sheet_data or {}).get("computed", {}).get("automatic_feats", []))
    owned.update((entry["choice"], entry.get("target", ""))
                 for record in (character.play_data or {}).get("advancement_history", [])
                 for entry in record["choices"] if "feat" in entry["feature"].casefold())
    owned.update((name, "") for i in range(56) if (name := values[f"feature.{i}"]) in feats
                 and not any(existing == name for existing, _ in owned))
    targets = {
        "skill": {key: item["name"] for key, item in current_catalog["skills"].items() if item.get("enabled", True)},
        "weapon": {key: item["name"] for key, item in equipment(current_catalog).items()
                   if item.get("kind") == "weapon" and item.get("enabled", True)},
    }
    swaps = {}
    if profile["spell_swap"] and profile["casting_ability"]:
        first, frequency, lower = profile["spell_swap"]
        if target >= first and (target - first) % frequency == 0:
            casting_score = Decimal(values[f"ability.{profile['casting_ability']}.score"] or 0)
            known_levels = [int(key) for key in current.get("known", {})]
            highest = max(known_levels, default=0)
            for spell_level in sorted(known_levels):
                if spell_level <= highest - lower and spell_level + 10 <= casting_score:
                    spells = values[f"spell.{spell_level}.list"].splitlines()
                    swaps.update({f"{spell_level}.{index}": (spell_level, spell) for index, spell in enumerate(spells) if spell.strip()})
    return {
        "class_id": class_id, "swaps": swaps, "profile": profile, "target": target, "values": values, "features": features,
        "choices": choices, "rows": rows, "known": known, "bab": bab,
        "saves": [after - before for before, after in zip(previous["saves"], current["saves"])],
        "previous": previous, "current": current,
        "spell_levels": [int(key) for key in current.get("slots", {}) if int(key) > 0],
        "speed": track(campaign), "threshold": XP_TRACKS[track(campaign)][target - 1],
        "human": character.ancestry.casefold() == "human",
        "missing": [ABILITIES[key] for key in ("con", "int") if not values[f"ability.{key}.score"]]
                   + (["Maximum HP"] if not values["hp.total"] else []),
        "fighter_weapon_slots": {index for index, label in enumerate(choices)
                                 if class_id == "fighter" and label.casefold().startswith("weapon training")},
        "fighter_weapon_choices": sorted(fighter_weapon_groups().keys() - trained_weapon_groups(character).keys())
                                  if class_id == "fighter" else [],
        "feat_catalog": feats, "owned_feats": sorted(owned), "feat_targets": targets,
        "feat_bab": float(Decimal(values["bab"] or previous["bab"]) + bab),
        "feat_scores": {key: float(Decimal(values[f"ability.{key}.score"] or 0)) for key in ABILITIES},
        "feat_slots": {index: feat_slot(class_id, label) for index, label in enumerate(choices)
                       if "feat" in label.casefold()},

    }


def feat_slot(class_id, label):
    label = label.casefold()
    if "teamwork" in label:
        return "teamwork"
    if "combat" in label or (label == "bonus feat" and class_id in {"fighter", "gunslinger", "warpriest"}):
        return "combat"
    return ""


def feat_options(advancement):
    return {
        name: {
            "url": safe_weapon_url(item.get("url", "")),
            "combat": item.get("combat", False), "teamwork": "Teamwork" in item.get("categories", ()),
            "scores": {key: item[key] for key in ABILITIES if item.get(key)}, "bab": item.get("bab", 0),
            "requires": item.get("requires", ""), "repeatable": item.get("repeatable", False),
            "choice": item.get("choice", ""),
        }
        for name, item in sorted(advancement["feat_catalog"].items(), key=lambda entry: entry[0].casefold())
        if item.get("enabled", True)
    }


def validate_feats(advancement, selections, ability, errors):
    options = feat_options(advancement)
    owned = advancement["owned_feats"]
    slots = advancement["feat_slots"]
    selected = {entry["choice"] for index, entry in enumerate(selections) if index in slots}
    owned_names = {name for name, _ in owned}
    taken = list(owned)
    for index, slot in slots.items():
        entry = selections[index]
        name, target = entry["choice"], entry.get("target", "")
        feat = options.get(name)
        if not feat or slot and not feat[slot]:
            errors.append(f"Choose an available feat for {entry['feature']}.")
            continue
        if feat["bab"] > advancement["feat_bab"] or any(
            advancement["feat_scores"][key] + (key == ability) < score for key, score in feat["scores"].items()
        ):
            errors.append(f"{name} exceeds the character's ability score or base attack bonus.")
        prerequisite = feat["requires"]
        visited = {name}
        while prerequisite and prerequisite not in owned_names:
            if prerequisite not in selected or prerequisite in visited:
                errors.append(f"{name} requires {prerequisite}.")
                break
            visited.add(prerequisite)
            prerequisite = options.get(prerequisite, {}).get("requires", "")
        choice = feat["choice"]
        if choice and target not in advancement["feat_targets"].get(choice, {}):
            errors.append(f"Choose a valid {choice} for {name}.")
        if any(existing == name and (not feat["repeatable"] or previous == target) for existing, previous in taken):
            errors.append(f"{name} is already selected.")
        taken.append((name, target))


def submit(character, advancement, form):
    target, profile = advancement["target"], advancement["profile"]
    values = advancement["values"]
    errors, changes = [], {}

    def text(key, limit):
        value = str(form.get(key, "")).strip()
        if len(value) > limit:
            errors.append(f"Use up to {limit} characters for {key.replace('_', ' ')}.")
        return value

    def whole(key, minimum, maximum):
        raw = str(form.get(key, ""))
        if not re.fullmatch(r"[0-9]{1,3}", raw) or not minimum <= int(raw) <= maximum:
            errors.append(f"Enter {key.replace('_', ' ')} between {minimum} and {maximum}.")
            return minimum
        return int(raw)

    def number(key, default=0):
        return Decimal(values[key]) if values[key] else Decimal(default)

    def add(key, amount, default=0):
        changes[key] = str(Decimal(changes[key]) + amount if key in changes else number(key, default) + amount)

    roll = whole("hit_die", 1, profile["hd"])
    favored = form.get("favored", "")
    if favored not in {"hp", "skill", "none"}:
        errors.append("Choose a favored class reward.")
    ability = form.get("ability", "") if target % 4 == 0 else ""
    if target % 4 == 0:
        if ability not in ABILITIES or not values.get(f"ability.{ability}.score"):
            errors.append("Choose an ability with a permanent score to increase.")
        else:
            add(f"ability.{ability}.score", 1)
    if advancement["missing"]:
        errors.append("Save the missing character sheet values before advancing.")
    # Floor division on Decimal truncates toward zero. Convert scores before computing modifiers.
    old_con = (int(number("ability.con.score", 10)) - 10) // 2
    old_int = (int(number("ability.int.score", 10)) - 10) // 2
    con_increase = int(ability == "con" and int(number("ability.con.score", 10)) % 2 == 1)
    int_increase = int(ability == "int" and int(number("ability.int.score", 10)) % 2 == 1)
    hp = max(1, roll + old_con + con_increase) + int(favored == "hp") + con_increase * (target - 1)
    add("hp.total", hp)
    add("hp.current", hp, number("hp.total"))
    previous, current = advancement["previous"], advancement["current"]
    add("bab", advancement["bab"], previous["bab"])
    for index, (key, _, _) in enumerate(SAVES):
        add(f"save.{key}.base", advancement["saves"][index], previous["saves"][index])
    changes["skill_points.base"] = str(profile["ranks"])

    before = max(1, profile["ranks"] + old_int)
    after = max(1, profile["ranks"] + old_int + int_increase)
    budget = after + (after - before) * (target - 1) + advancement["human"] + (favored == "skill")
    allocated = 0
    for key, _, _, ranks, _, enabled in advancement["rows"]:
        if enabled and form.get(f"rank_{key}", ""):
            added = whole(f"rank_{key}", 0, max(0, target - ranks))
            allocated += added
            if added:
                changes[f"skill.{key}.ranks"] = str(ranks + added)
    if allocated != budget:
        errors.append(f"Assign exactly {budget} skill ranks. You assigned {allocated}.")

    selections = []
    for index, label in enumerate(advancement["choices"]):
        entry = text(f"choice_{index}", 150)
        if index in advancement["fighter_weapon_slots"]:
            entry = weapon_group_name(entry) or ""
            if entry not in advancement["fighter_weapon_choices"]:
                errors.append("Choose a Fighter weapon group that the character has not already trained.")
        elif not entry:
            errors.append(f"Record your choice for {label}.")
        selections.append({"feature": label, "choice": entry})
        if index in advancement["feat_slots"]:
            selections[-1]["target"] = text(f"target_{index}", 100)
    validate_feats(advancement, selections, ability, errors)

    existing_features = {values[f"feature.{i}"].casefold() for i in range(56)}
    free = iter(i for i in range(56) if not values[f"feature.{i}"])
    for entry in selections:
        label, choice = entry["feature"], entry["choice"]
        display = choice if "feat" in label.casefold() else f"{label}: {choice}"
        if target_key := entry.get("target"):
            kind = advancement["feat_catalog"].get(choice, {}).get("choice")
            display += f" ({advancement['feat_targets'].get(kind, {}).get(target_key, target_key)})"
        if display.casefold() not in existing_features and (slot := next(free, None)) is not None:
            changes[f"feature.{slot}"] = display
            existing_features.add(display.casefold())

    # Preserve sheet bonuses while applying the supported unconditional effects
    # of new catalog feats. Choices and situational effects remain in history.
    feats = {**advancement["feat_catalog"], **character_catalog(character)["feats"]}
    feat_names = {name.casefold(): name for name in feats}
    history = (character.play_data or {}).get("advancement_history", [])
    previous_feats = {str(item["choice"]).casefold() for record in history for item in record["choices"]
                      if "feat" in item["feature"].casefold()}
    previous_feats |= {values[f"feature.{i}"].casefold() for i in range(56)}
    if "toughness" in previous_feats and target > 3:
        add("hp.total", 1)
        add("hp.current", 1)
        hp += 1
    for entry in selections:
        name = entry["choice"].casefold()
        if "feat" not in entry["feature"].casefold() or name not in feat_names or name in previous_feats:
            continue
        previous_feats.add(name)
        feat = feats[feat_names[name]]
        for effect, amount in feat.get("effects", {}).items():
            if effect == "hp":
                amount = max(target, amount) if name == "toughness" else amount
                add("hp.total", amount)
                add("hp.current", amount)
                hp += amount
            elif effect in {"fortitude", "reflex", "will"}:
                add(f"save.{effect}.misc", amount)
            elif effect == "initiative":
                add("initiative.misc", amount)
            elif effect == "dodge":
                add("ac.dodge", amount)
            elif effect == "selected_skill" or effect.startswith("skill:"):
                skill = entry.get("target") if effect == "selected_skill" else effect.partition(":")[2]
                key = f"skill.{skill}.misc"
                if key in values:
                    add(key, amount)

    replacement = text("replacement_spell", 150)
    swap = form.get("swap_spell", "")
    if (swap or replacement) and (swap not in advancement["swaps"] or not replacement):
        errors.append("Choose one eligible known spell and enter its replacement.")
    swap_record = None
    spell_additions = {}
    writable_levels = set(advancement["known"])
    if profile["book"]:
        writable_levels.update(map(str, advancement["spell_levels"]))
    if swap in advancement["swaps"]:
        writable_levels.add(str(advancement["swaps"][swap][0]))
    for level in sorted(writable_levels):
        existing = values[f"spell.{level}.list"].splitlines()
        additions = [name.strip() for name in text(f"spells_{level}", 2000).splitlines() if name.strip()]
        count = advancement["known"].get(level, 0)
        if advancement["known"] and len(additions) != count:
            errors.append(f"Enter {count} new level {level} spells or talents.")
        if swap in advancement["swaps"] and swap.split(".")[0] == level and replacement:
            index = int(swap.split(".")[1])
            if replacement.casefold() == existing[index].casefold():
                errors.append("Choose a different replacement spell.")
            swap_record = {"level": level, "old": existing[index], "new": replacement}
            existing[index] = replacement
        combined = [name for name in existing + additions if name.strip()]
        if (additions or replacement) and len({name.strip().casefold() for name in combined}) < len(combined):
            errors.append(f"Choose distinct level {level} spells or talents.")
        if len("\n".join(combined)) > 10000:
            errors.append(f"The level {level} spell list is full.")
        if additions:
            spell_additions[level] = additions
        if additions or swap_record and swap_record["level"] == level:
            changes[f"spell.{level}.list"] = "\n".join(combined)
    if profile["book"] and sum(map(len, spell_additions.values())) != profile["book"]:
        errors.append(f"Record {profile['book']} new spellbook, familiar or formula-book entries.")
    for level, slots in current.get("slots", {}).items():
        old_slots = previous.get("slots", {}).get(level, 0)
        key = f"spell.{level}.daily"
        if slots != old_slots or not values[key]:
            add(key, slots - old_slots, old_slots)
    if current.get("slots") or current.get("known"):
        delay = profile["caster_delay"]
        caster_level = max(1, target - delay)
        old_caster_level = max(1, target - 1 - delay) if previous.get("slots") or previous.get("known") else 0
        add("caster_level", caster_level - old_caster_level, old_caster_level)
        caster = profile["casting_ability"]
        old_mod = (int(number(f"ability.{caster}.score", 10)) - 10) // 2
        new_mod = old_mod + int(ability == caster and int(number(f"ability.{caster}.score", 10)) % 2 == 1)
        concentration_gain = caster_level - old_caster_level + new_mod - old_mod
        add("concentration", concentration_gain, old_caster_level + old_mod)
        for level in {"0", *map(str, advancement["spell_levels"])}:
            add(f"spell.{level}.dc", new_mod - old_mod, 10 + int(level) + old_mod)
            if level != "0":
                old_bonus = max(0, (old_mod - int(level)) // 4 + 1)
                new_bonus = max(0, (new_mod - int(level)) // 4 + 1)
                domain = int(advancement["class_id"] == "cleric")
                if level in previous.get("slots", {}):
                    add(f"spell.{level}.bonus", new_bonus - old_bonus, old_bonus + domain)
                else:
                    add(f"spell.{level}.bonus", new_bonus + domain)

    entry = {
        "level": target, "class": character.class_name, "hit_die": roll, "hp": hp,
        "favored": favored, "ability": ability, "features": advancement["features"], "choices": selections,
        "spells": spell_additions, "spell_swap": swap_record,
    }
    if not errors:
        character.play_data = {
            **(character.play_data or {}), "calculation_version": 1,
            **persist_effects(character, values), **changes, "advancement_history": [*history, entry],
        }
        character.level = target
    return errors

"""Plan and apply one level in a selected class."""
import re
from decimal import Decimal
from fastapi import HTTPException

from .advancement import XP_TRACKS, eligible, level_for, saved_xp, track
from .deluxe_sheet import sheet_values, skill_rows
from .equipment_effects import persist_effects
from .feat_class_requirements import class_feat_gate
from .models import Campaign, User
from .class_catalog import (
    FIRST_LEVEL_CHOICES, casting_class_keys, character_classes, class_profile, class_progression_row, class_summary,
    combined_class_skills, favored_class_keys,
)
from .pf1_data import ABILITIES, CLASSES
from .rule_catalog import character_catalog, load_catalog
from .feature_links import feature_targets
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
    return eligible(character, campaign) and bool(character_classes(character, catalog))


EXCLUSIVE_CLASSES = ({"rogue", "rogue-unchained", "ninja"}, {"cavalier", "samurai"},
                     {"barbarian", "barbarian-unchained"}, {"monk", "monk-unchained"},
                     {"summoner", "summoner-unchained"})


def class_choices(catalog, classes, alignment):
    def allowed(key):
        if key not in classes and any(key in group and group & classes.keys() for group in EXCLUSIVE_CLASSES):
            return False
        if not alignment and key in classes:
            return True
        if key == "paladin":
            return alignment == "LG"
        if key in {"monk", "monk-unchained"}:
            return alignment.startswith("L")
        if key in {"barbarian", "barbarian-unchained", "bard"}:
            return not alignment.startswith("L") and bool(alignment or key in classes)
        if key in {"druid", "shifter"}:
            return "N" in alignment
        if key == "antipaladin":
            return alignment == "CE"
        return True

    options = [(key, class_profile(catalog, key)["name"], classes.get(key, 0)) for key in CLASSES
               if allowed(key) and classes.get(key, 0) < 20]
    return sorted(options, key=lambda item: (not item[2], item[1].casefold()))


def plan(ctx, character, selected_class=None, specialization=None):
    db = ctx.db
    campaign = db.get(Campaign, character.campaign_id) if character.campaign_id else None
    current_catalog = load_catalog(db)
    classes = character_classes(character, current_catalog)
    speed = track(campaign)
    eligible_level = level_for(saved_xp(character, speed), speed)
    if not classes or eligible_level <= character.level:
        return None
    owner = db.get(User, character.owner_id)
    gm = db.get(User, campaign.owner_id) if campaign else None
    values = sheet_values(character, owner, campaign, gm, progression_catalog=current_catalog)
    options = class_choices(current_catalog, classes, values["alignment"])
    if not options:
        return None
    if selected_class and selected_class not in {option[0] for option in options}:
        raise HTTPException(422, "Choose an eligible class for this level.")
    class_id = selected_class or next((key for key in classes if any(option[0] == key for option in options)), options[0][0])
    profile = class_profile(current_catalog, class_id)
    target = character.level + 1
    class_level = classes.get(class_id, 0) + 1
    if class_id == "vigilante" and class_level == 1:
        specialization = specialization or "stalker"
        if specialization not in {"stalker", "avenger"}:
            raise HTTPException(422, "Choose a vigilante specialization.")
    else:
        specialization = None
    previous = class_progression_row(character, current_catalog, class_id, class_level - 1)
    current = class_progression_row(character, current_catalog, class_id, class_level, specialization=specialization)
    updated_classes = {**classes, class_id: class_level}
    primary_caster = next(iter(casting_class_keys(current_catalog, updated_classes)), None)
    casting_progression = None
    if primary_caster:
        casting_progression = {
            "profile": class_profile(current_catalog, primary_caster),
            "previous": class_progression_row(character, current_catalog, primary_caster, classes.get(primary_caster, 0)),
            "current": class_progression_row(character, current_catalog, primary_caster, updated_classes[primary_caster]),
            "level": updated_classes[primary_caster],
            "class_id": primary_caster,
            "advanced": primary_caster == class_id,
        }
    favored = favored_class_keys(character, classes)
    second_favored = character.ancestry.casefold() == "half-elf" and len(favored) == 1
    favored_options = sorted(
        [(key, class_profile(current_catalog, key)["name"]) for key in CLASSES if key not in favored],
        key=lambda item: item[1].casefold(),
    ) if second_favored else []
    bab = current["bab"] - previous["bab"]
    features = re.split(r",\s*(?![^()]*\))", current["features"]) if current["features"] else []
    choices = ["General feat"] if target % 2 else []
    choices.extend(feature_choices(current))
    if class_level == 1:
        choices.extend(label for label in FIRST_LEVEL_CHOICES.get(class_id, ()) if label not in choices)
    if class_id == "druid" and class_level == 1 and "Druidic" not in values["languages"].split(", "):
        class_language = "Druidic"
    else:
        class_language = ""
    catalog = character_catalog(character)
    trained = combined_class_skills(character, catalog, updated_classes)
    rows = [
        (key, item["name"] + (" (second specialty)" if key.endswith("-2") else ""),
         key.removesuffix("-2") in trained, int(Decimal(values[f"skill.{key}.ranks"] or 0)),
         safe_weapon_url(current_catalog["skills"].get(key.removesuffix("-2"), item).get("url", "")),
         item.get("enabled", True))
        for key, item in skill_rows(catalog)
    ]
    old_bab = sum(class_progression_row(character, current_catalog, key, level)["bab"] for key, level in classes.items())
    feat_bab = float(Decimal(old_bab if len(updated_classes) > 1 else values["bab"] or old_bab) + bab)
    return {
        "class_id": class_id, "profile": profile, "target": target, "values": values, "features": features,
        "class_level": class_level, "class_options": options, "classes": updated_classes, "old_bab": old_bab,
        "specialization": specialization,
        "favored_classes": favored, "favored_options": favored_options,
        "is_favored": class_id in favored,
        "rank_bases": [class_profile(current_catalog, key)["ranks"] for key, count in classes.items() for _ in range(count)],
        "casting_progression": casting_progression,
        "automatic_feats": profile["automatic_feats"] if class_level == 1 else (),
        "class_language": class_language,
        "choices": choices, "rows": rows, "bab": bab,
        "saves": [after - before for before, after in zip(previous["saves"], current["saves"])],
        "current": current,
        "speed": speed, "threshold": XP_TRACKS[speed][target - 1], "eligible_level": eligible_level,
        "human": character.ancestry.casefold() == "human",
        "missing": [ABILITIES[key] for key in ("con", "int") if not values[f"ability.{key}.score"]]
                   + (["Maximum HP"] if not values["hp.total"] else []),
        "fighter_weapon_slots": {index for index, label in enumerate(choices)
                                 if class_id == "fighter" and label.casefold().startswith("weapon training")},
        "fighter_weapon_choices": sorted(fighter_weapon_groups().keys() - trained_weapon_groups(character).keys())
                                  if class_id == "fighter" else [],
        **feat_context(character, current_catalog, values, updated_classes, feat_bab),
        "feat_slots": {index: feat_slot(class_id, class_level, profile, label) for index, label in enumerate(choices)
                       if "feat" in label.casefold()},
        "class_summary": class_summary(current_catalog, updated_classes) if len(updated_classes) > 1 else "",
    }



def feat_context(character, catalog, values, classes, bab):
    feats = catalog["feats"]
    targets = feature_targets(catalog)
    target_keys = {kind: {label.casefold(): key for key, label in entries.items()}
                   for kind, entries in targets.items()}
    feat_names = {name.casefold(): name for name in feats}
    computed = (character.sheet_data or {}).get("computed", {})
    owned = {(entry["name"], entry.get("choice", "")) for entry in computed.get("feats", [])}
    owned.update((name, "") for name in computed.get("automatic_feats", []))
    owned.update((entry["choice"], entry.get("target", ""))
                 for record in (character.play_data or {}).get("advancement_history", [])
                 for entry in record["choices"] if "feat" in entry["feature"].casefold())
    for row in range(56):
        label = values[f"feature.{row}"]
        name = feat_names.get(label.casefold())
        if name and not any(existing == name for existing, _ in owned):
            owned.add((name, ""))
        elif not name and label.endswith(")") and " (" in label:
            base, detail = label[:-1].rsplit(" (", 1)
            name = feat_names.get(base.casefold())
            if name and (key := target_keys.get(feats[name].get("choice"), {}).get(detail.casefold())):
                owned.add((name, key))
    return {
        "feat_catalog": feats, "owned_feats": sorted(owned), "feat_targets": targets, "feat_bab": bab,
        "blocked_class_feats": class_feat_gate(character, catalog, classes, bab, owned),
        "feat_scores": {key: float(Decimal(values[f"ability.{key}.score"] or 0)) for key in ABILITIES},
    }


def sheet_feat_context(character, catalog, values):
    classes = character_classes(character, catalog)
    bab = sum(class_progression_row(character, catalog, key, level)["bab"] for key, level in classes.items())
    return {**feat_context(character, catalog, values, classes, float(Decimal(values["bab"] or bab))),
            "feat_slots": {0: ""}}


def sheet_feat_options(rules):
    options = feat_options(rules)
    owned = set(map(tuple, rules["owned_feats"]))
    available = []
    for name, feat in options.items():
        kind = feat["choice"]
        targets = [key for key in rules["feat_targets"].get(kind, {}) if (name, key) not in owned] if kind else [""]
        if not targets:
            continue
        errors = []
        validate_feats(rules, [{"feature": "feat", "choice": name, "target": targets[0]}], "", errors, options)
        if not errors:
            available.append({"name": name, "url": feat["url"], "choice": kind, "targets": targets if kind else []})
    return available

def feat_slot(class_id, class_level, profile, label):
    label = label.casefold()
    if class_level == 1 and label == "bonus feat" and profile["bonus_feat"] == "monk":
        return "monk"
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
            "monk": item.get("monk", False),
            "scores": {key: item[key] for key in ABILITIES if item.get(key)}, "bab": item.get("bab", 0),
            "requires": item.get("requires", ""), "repeatable": item.get("repeatable", False),
            "choice": item.get("choice", ""),
        }
        for name, item in sorted(advancement["feat_catalog"].items(), key=lambda entry: entry[0].casefold())
        if item.get("enabled", True) and name.casefold() not in advancement["blocked_class_feats"]
    }


def validate_feats(advancement, selections, ability, errors, options=None):
    if options is None:
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
        if slot != "monk" and (feat["bab"] > advancement["feat_bab"] or any(
            advancement["feat_scores"][key] + (key == ability) < score for key, score in feat["scores"].items()
        )):
            errors.append(f"{name} exceeds the character's ability score or base attack bonus.")
        prerequisite = feat["requires"] if slot != "monk" else ""
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



def feat_adjustments(feat, entry, level):
    """Sheet fields changed when a feat is selected in the level-up wizard."""
    for effect, amount in feat.get("effects", {}).items():
        if effect == "hp":
            amount = max(level, amount) if entry["choice"].casefold() == "toughness" else amount
            yield "hp.total", amount
            yield "hp.current", amount
        elif effect in {"fortitude", "reflex", "will"}:
            yield f"save.{effect}.misc", amount
        elif effect == "initiative":
            yield "initiative.misc", amount
        elif effect == "dodge":
            yield "ac.dodge", amount
        elif effect == "selected_skill" or effect.startswith("skill:"):
            skill = entry.get("target") if effect == "selected_skill" else effect.partition(":")[2]
            yield f"skill.{skill}.misc", amount

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
    favored_classes = advancement["favored_classes"]
    second = form.get("second_favored", "")
    if second:
        if second not in {key for key, _ in advancement["favored_options"]}:
            errors.append("Choose an available second favored class.")
        else:
            favored_classes = [*favored_classes, second]
    favored = form.get("favored", "none")
    if favored not in {"hp", "skill", "none"} or (favored != "none" and advancement["class_id"] not in favored_classes):
        errors.append("Choose a reward only for a favored class.")
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
    add("bab", advancement["bab"], advancement["old_bab"])
    changes["skill_points.base"] = str(profile["ranks"])
    if advancement["class_language"]:
        changes["languages"] = ", ".join(filter(None, (values["languages"], advancement["class_language"])))

    after = max(1, profile["ranks"] + old_int + int_increase)
    retroactive = sum(max(1, base + old_int + int_increase) - max(1, base + old_int)
                      for base in advancement["rank_bases"])
    budget = after + retroactive + advancement["human"] + (favored == "skill")
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
    if specialization := advancement["specialization"]:
        changes["vigilante_specialization"] = specialization
        selections.append({"feature": "Vigilante specialization", "choice": specialization.capitalize()})

    existing_features = {values[f"feature.{i}"].casefold() for i in range(56)}
    free = iter(i for i in range(56) if not values[f"feature.{i}"])
    automatic = [{"feature": "Automatic class feat", "choice": name} for name in advancement["automatic_feats"]
                 if not any(name.casefold() == owned.casefold() for owned, _ in advancement["owned_feats"])]
    if any(entry["choice"] == granted["choice"] for entry in selections for granted in automatic):
        errors.append("Choose a feat different from the feats granted automatically by this class.")
    for entry in [*selections, *automatic]:
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
    for entry in [*selections, *automatic]:
        name = entry["choice"].casefold()
        if "feat" not in entry["feature"].casefold():
            continue
        adjustments = []
        if name in feat_names and name not in previous_feats:
            previous_feats.add(name)
            adjustments = [(key, amount) for key, amount in feat_adjustments(feats[feat_names[name]], entry, target)
                           if key in values]
        entry["sheet_adjustments"] = adjustments
        for key, amount in adjustments:
            add(key, amount)
            if key == "hp.total":
                hp += amount

    casting = advancement["casting_progression"]
    if casting:
        previous, current = casting["previous"], casting["current"]
        slots_by_level = current.get("slots", {})
        caster = casting["profile"]["casting_ability"]
        old_mod = (int(number(f"ability.{caster}.score", 10)) - 10) // 2
        new_mod = old_mod + int(ability == caster and int(number(f"ability.{caster}.score", 10)) % 2 == 1)
        if (slots_by_level or current.get("known")) and (casting["advanced"] or new_mod != old_mod):
            delay = casting["profile"]["caster_delay"]
            caster_level = max(1, casting["level"] - delay)
            earlier_level = casting["level"] - casting["advanced"]
            old_caster_level = max(1, earlier_level - delay) if previous.get("slots") or previous.get("known") else 0
            add("caster_level", caster_level - old_caster_level, old_caster_level)
            add("concentration", caster_level - old_caster_level + new_mod - old_mod, old_caster_level + old_mod)
            for level, slots in slots_by_level.items():
                old_slots = previous.get("slots", {}).get(level, 0)
                key = f"spell.{level}.daily"
                if slots != old_slots or not values[key]:
                    add(key, slots - old_slots, old_slots)
            for level in {"0", *slots_by_level}:
                add(f"spell.{level}.dc", new_mod - old_mod, 10 + int(level) + old_mod)
                if level == "0":
                    continue
                old_bonus = max(0, (old_mod - int(level)) // 4 + 1)
                new_bonus = max(0, (new_mod - int(level)) // 4 + 1)
                domain = int(casting["class_id"] == "cleric")
                if level in previous.get("slots", {}):
                    add(f"spell.{level}.bonus", new_bonus - old_bonus, old_bonus + domain)
                else:
                    add(f"spell.{level}.bonus", new_bonus + domain)

    entry = {
        "level": target, "class": profile["name"], "class_id": advancement["class_id"],
        "class_level": advancement["class_level"], "hit_die": roll, "hp": hp,
        "favored": favored, "ability": ability, "features": advancement["features"], "choices": [*selections, *automatic],
    }
    if not errors:
        character.play_data = {
            **(character.play_data or {}), "calculation_version": 1,
            **persist_effects(character, values), **changes, "advancement_history": [*history, entry],
            "class_levels": list(advancement["classes"].items()), "favored_classes": favored_classes,
        }
        character.level = target
        if advancement["class_summary"]:
            character.class_name = advancement["class_summary"]
    return errors

"""First-level creation facts. Source links are kept with the data; prose is original."""
import json
from pathlib import Path

from .reference_links import class_reference

ABILITIES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
POINT_COST = {7: -4, 8: -2, 9: -1, 10: 0, 11: 1, 12: 2, 13: 3, 14: 5, 15: 7, 16: 10, 17: 13, 18: 17}
# Keys are stable draft/validation identifiers; insertion order controls navigation.
STEPS = {1: "Character sheet", 3: "Race", 4: "Class", 2: "Ability scores", 5: "Skill ranks", 6: "Feats", 7: "Hit points", 8: "Equipment", 9: "Combat values", 10: "Description", 12: "Review"}
OUTLINE = "https://www.aonprd.com/Rules.aspx?ID=83"
RACES = {
    "human": {"name": "Human", "mods": {}, "flex": True, "size": "Medium", "speed": 30, "languages": "Common", "traits": "A flexible ability bonus, an extra feat, and an extra skill rank."},
    "dwarf": {"name": "Dwarf", "mods": {"con": 2, "wis": 2, "cha": -2}, "size": "Medium", "speed": 20, "languages": "Common, Dwarven", "traits": "Darkvision 60 ft.; steady speed in armor; stability and conditional defenses."},
    "elf": {"name": "Elf", "mods": {"dex": 2, "int": 2, "con": -2}, "size": "Medium", "speed": 30, "languages": "Common, Elven", "traits": "Low-light vision; keen senses; elven magic, immunities, and weapon familiarity."},
    "gnome": {"name": "Gnome", "mods": {"con": 2, "cha": 2, "str": -2}, "size": "Small", "speed": 20, "languages": "Common, Gnome, Sylvan", "traits": "Low-light vision; keen senses; gnome magic and conditional racial defenses."},
    "half-elf": {"name": "Half-Elf", "mods": {}, "flex": True, "size": "Medium", "speed": 30, "languages": "Common, Elven", "traits": "Low-light vision; keen senses; adaptability grants Skill Focus; elven immunities."},
    "half-orc": {"name": "Half-Orc", "mods": {}, "flex": True, "size": "Medium", "speed": 30, "languages": "Common, Orc", "traits": "Darkvision 60 ft.; intimidating; orc ferocity and weapon familiarity."},
    "halfling": {"name": "Halfling", "mods": {"dex": 2, "cha": 2, "str": -2}, "size": "Small", "speed": 20, "languages": "Common, Halfling", "traits": "Halfling luck; keen senses; sure-footed; conditional resistance to fear."},
}
SKILLS = {}
for ability, names in {
    "str": "Climb|Swim", "dex": "Acrobatics|Disable Device|Escape Artist|Fly|Ride|Sleight of Hand|Stealth",
    "int": "Appraise|Craft|Knowledge (arcana)|Knowledge (dungeoneering)|Knowledge (engineering)|Knowledge (geography)|Knowledge (history)|Knowledge (local)|Knowledge (nature)|Knowledge (nobility)|Knowledge (planes)|Knowledge (religion)|Linguistics|Spellcraft",
    "wis": "Heal|Perception|Profession|Sense Motive|Survival", "cha": "Bluff|Diplomacy|Disguise|Handle Animal|Intimidate|Perform|Use Magic Device",
}.items():
    for name in names.split("|"):
        key = name.lower().replace(" (", "-").replace(")", "").replace(" ", "-")
        SKILLS[key] = {"name": name, "ability": ability, "armor": ability == "dex" and name != "Ride" or name in {"Climb", "Swim", "Ride"}}
KNOWLEDGE = [key for key in SKILLS if key.startswith("knowledge-")]


def class_record(name, hd, ranks, bab, saves, wealth, skills, caster="", group="Core", choices="", automatic=(), bonus=""):
    keys = skills.split()
    if "knowledge-all" in keys:
        keys.remove("knowledge-all")
        keys += KNOWLEDGE
    return {"name": name, "hd": hd, "ranks": ranks, "bab": bab, "saves": saves, "wealth_dice": wealth,
            "skills": keys, "caster": caster, "group": group, "choices": choices,
            "automatic_feats": list(automatic), "bonus_feat": bonus,
            "url": class_reference(name)}


CLASSES = {
    "barbarian": class_record("Barbarian",12,4,1,[2,0,0],3,"acrobatics climb craft handle-animal intimidate knowledge-nature perception ride survival swim",choices="Record rage details and weapon choices."),
    "bard": class_record("Bard",8,6,0,[0,2,2],3,"acrobatics appraise bluff climb craft diplomacy disguise escape-artist intimidate knowledge-all linguistics perception perform profession sense-motive sleight-of-hand spellcraft stealth use-magic-device", "cha", choices="Choose performance specialties."),
    "cleric": class_record("Cleric",8,2,0,[2,0,2],4,"appraise craft diplomacy heal knowledge-arcana knowledge-history knowledge-nobility knowledge-planes knowledge-religion linguistics profession sense-motive spellcraft", "wis", choices="Record deity, two domains, channel energy choice, and deity's favored weapon."),
    "druid": class_record("Druid",8,4,0,[2,0,2],2,"climb craft fly handle-animal heal knowledge-geography knowledge-nature perception profession ride spellcraft survival swim", "wis", choices="Choose nature bond: companion or domain. Add Druidic to languages."),
    "fighter": class_record("Fighter",10,2,1,[2,0,0],5,"climb craft handle-animal intimidate knowledge-dungeoneering knowledge-engineering profession ride survival swim",bonus="combat"),
    "monk": class_record("Monk",8,4,0,[2,2,2],1,"acrobatics climb craft escape-artist intimidate knowledge-history knowledge-religion perception perform profession ride sense-motive stealth swim",automatic=("Improved Unarmed Strike", "Stunning Fist"),bonus="monk"),
    "paladin": class_record("Paladin",10,2,1,[2,0,0],5,"craft diplomacy handle-animal heal knowledge-nobility knowledge-religion profession ride sense-motive spellcraft",choices="Record deity and code of conduct. Spellcasting begins at a later level."),
    "ranger": class_record("Ranger",10,6,1,[2,2,0],5,"climb craft handle-animal heal intimidate knowledge-dungeoneering knowledge-geography knowledge-nature perception profession ride spellcraft stealth survival swim",choices="Choose favored enemy. Spellcasting begins at a later level."),
    "rogue": class_record("Rogue",8,8,0,[0,2,0],4,"acrobatics appraise bluff climb craft diplomacy disable-device disguise escape-artist intimidate knowledge-dungeoneering knowledge-local linguistics perception perform profession sense-motive sleight-of-hand stealth swim use-magic-device"),
    "sorcerer": class_record("Sorcerer",6,2,0,[0,0,2],2,"appraise bluff craft fly intimidate knowledge-arcana profession spellcraft use-magic-device", "cha",choices="Choose bloodline and record its first-level power.",automatic=("Eschew Materials",)),
    "wizard": class_record("Wizard",6,2,0,[0,0,2],2,"appraise craft fly knowledge-all linguistics profession spellcraft", "int",choices="Choose arcane bond, school or universalist, and any opposition schools.",automatic=("Scribe Scroll",)),
    "alchemist": class_record("Alchemist",8,4,0,[2,2,0],3,"appraise craft disable-device fly heal knowledge-arcana knowledge-nature perception profession sleight-of-hand spellcraft survival use-magic-device", "int", "Base", "Record mutagen and bomb details.", ("Brew Potion", "Throw Anything")),
    "cavalier": class_record("Cavalier",10,4,1,[2,0,0],5,"bluff climb craft diplomacy handle-animal intimidate profession ride sense-motive swim",group="Base",choices="Choose order, mount, and tactician teamwork feat.",bonus="teamwork"),
    "gunslinger": class_record("Gunslinger",10,4,1,[2,2,0],5,"acrobatics bluff climb craft handle-animal heal intimidate knowledge-engineering knowledge-local perception profession ride sleight-of-hand survival swim",group="Base",choices="Record gunsmith's starting battered firearm and grit.",automatic=("Gunsmithing",)),
    "inquisitor": class_record("Inquisitor",8,6,0,[2,0,2],4,"bluff climb craft diplomacy disguise heal intimidate knowledge-arcana knowledge-dungeoneering knowledge-nature knowledge-planes knowledge-religion perception profession ride sense-motive spellcraft stealth survival swim", "wis", "Base", "Choose deity, domain, and judgment details."),
    "magus": class_record("Magus",8,2,0,[2,0,2],4,"climb craft fly intimidate knowledge-arcana knowledge-dungeoneering knowledge-planes profession ride spellcraft swim use-magic-device", "int", "Base", "Record arcane pool and spell combat details."),
    "oracle": class_record("Oracle",8,4,0,[0,0,2],3,"craft diplomacy heal knowledge-history knowledge-planes knowledge-religion profession sense-motive spellcraft", "cha", "Base", "Choose mystery, curse, revelation, and cure/inflict bonus spells."),
    "shifter": class_record("Shifter",10,4,1,[2,2,0],3,"acrobatics climb craft fly handle-animal knowledge-nature perception profession ride stealth survival swim",group="Base",choices="Choose shifter aspect and record natural attacks."),
    "summoner": class_record("Summoner",8,2,0,[0,0,2],2,"craft fly handle-animal knowledge-all linguistics profession ride spellcraft use-magic-device", "cha", "Base", "Build the eidolon with your GM and record its choices."),
    "vigilante": class_record("Vigilante",8,6,0,[0,2,2],5,"acrobatics appraise bluff climb craft diplomacy disable-device disguise escape-artist intimidate knowledge-dungeoneering knowledge-engineering knowledge-local knowledge-nobility perception perform profession ride sense-motive sleight-of-hand stealth survival swim use-magic-device",group="Base",choices="Choose social talent and avenger or stalker specialization."),
    "witch": class_record("Witch",6,2,0,[0,0,2],3,"craft fly heal intimidate knowledge-arcana knowledge-history knowledge-nature knowledge-planes profession spellcraft use-magic-device", "int", "Base", "Choose patron, familiar, and first hex."),
    "ninja": class_record("Ninja",8,8,0,[0,2,0],4,"acrobatics appraise bluff climb craft diplomacy disable-device disguise escape-artist intimidate knowledge-local knowledge-nobility linguistics perception perform profession sense-motive sleight-of-hand stealth swim use-magic-device",group="Alternate",choices="Record poison use and sneak attack."),
    "samurai": class_record("Samurai",10,4,1,[2,0,0],5,"bluff climb craft diplomacy handle-animal intimidate profession ride sense-motive swim",group="Alternate",choices="Choose order and mount; record resolve."),
}
# Archives of Nethys class tables, including the separate Unchained variants.
CLASS_PROGRESSIONS = json.loads((Path(__file__).parent / "data" / "class_progressions.json").read_text())
ADDED_CLASSES = CLASS_PROGRESSIONS.keys() - CLASSES.keys()
for class_id, profile in CLASS_PROGRESSIONS.items():
    if class_id in CLASSES:
        continue
    first = profile["levels"][0]
    CLASSES[class_id] = {
        "name": profile["name"], "url": profile["url"], "group": profile["group"],
        "hd": profile["hd"], "ranks": profile["ranks"], "wealth_dice": profile["wealth_dice"],
        "bab": first["bab"], "saves": first["saves"], "skills": sorted(
            (set(profile["skills"]) & SKILLS.keys()) |
            (set(KNOWLEDGE) if "knowledge-all" in profile["skills"] else set())
        ),
        "caster": profile["caster"] if first.get("slots") or first.get("known") else "",
        "choices": first["features"], "automatic_feats": [], "bonus_feat": "",
    }
for class_id, bonus in {
    "monk-unchained": "monk",
}.items():
    CLASSES[class_id]["bonus_feat"] = bonus
for class_id, feats in {
    "brawler": ["Improved Unarmed Strike"], "monk-unchained": ["Improved Unarmed Strike", "Stunning Fist"],
    "rogue-unchained": ["Weapon Finesse"], "skald": ["Scribe Scroll"],
}.items():
    CLASSES[class_id]["automatic_feats"] = feats

ALIGNMENTS = {"LG":"Lawful good", "NG":"Neutral good", "CG":"Chaotic good", "LN":"Lawful neutral", "N":"True neutral", "CN":"Chaotic neutral", "LE":"Lawful evil", "NE":"Neutral evil", "CE":"Chaotic evil"}
FEATS = {
    "Improved Initiative": {"combat": True, "hint": "+4 initiative."},
    "Toughness": {"hint": "+3 HP at first level."},
    "Great Fortitude": {"hint": "+2 Fortitude."}, "Iron Will": {"hint": "+2 Will."}, "Lightning Reflexes": {"hint": "+2 Reflex."},
    "Dodge": {"combat": True, "dex": 13, "hint": "+1 dodge AC."},
    "Power Attack": {"combat": True, "str": 13, "bab": 1, "hint": "Optional attack/damage trade; activate separately during play."},
    "Weapon Finesse": {"combat": True, "hint": "Dexterity to hit with eligible finesse weapons."},
    "Point-Blank Shot": {"combat": True, "hint": "Conditional ranged bonus within 30 ft.; not added to base attacks."},
    "Precise Shot": {"combat": True, "requires": "Point-Blank Shot", "hint": "Avoid the normal shooting-into-melee penalty."},
    "Combat Reflexes": {"combat": True, "hint": "Additional attacks of opportunity based on Dexterity."},
    "Skill Focus": {"choice": "skill", "hint": "+3 to the selected skill at first level."},
    "Weapon Focus": {"combat": True, "bab": 1, "choice": "weapon", "hint": "+1 to hit with the selected weapon; confirm proficiency."},
    "Improved Unarmed Strike": {"combat": True, "hint": "Unarmed attacks count as armed."},
    "Alertness": {"hint": "+2 Perception and Sense Motive at first level."},
    "Combat Expertise": {"combat": True, "int": 13, "hint": "Optional defensive attack trade; activate during play."},
    "Improved Grapple": {"combat": True, "dex": 13, "requires": "Improved Unarmed Strike", "hint": "Conditional grapple bonuses; monk bonus feats may bypass prerequisites."},
    "Catch Off-Guard": {"combat": True, "hint": "Use improvised melee weapons."},
    "Throw Anything": {"combat": True, "hint": "Use improvised ranged weapons."},
    "Deflect Arrows": {"combat": True, "dex": 13, "requires": "Improved Unarmed Strike", "hint": "Deflect an arrow when the feat's conditions apply."},
    "Scorpion Style": {"combat": True, "requires": "Improved Unarmed Strike", "hint": "A special unarmed attack; track its effect during play."},
}
MONK_BONUS = ["Catch Off-Guard", "Combat Reflexes", "Deflect Arrows", "Dodge", "Improved Grapple", "Scorpion Style", "Throw Anything"]
# Costs are copper pieces; weights are pounds. Small equipment weighs half.
EQUIPMENT = {
    "dagger": {"name":"Dagger", "kind":"weapon", "cost":200, "weight":1, "damage":"1d4", "small_damage":"1d3", "finesse":True, "group":"simple"},
    "quarterstaff": {"name":"Quarterstaff", "kind":"weapon", "cost":0, "weight":4, "damage":"1d6", "small_damage":"1d4", "group":"simple"},
    "longsword": {"name":"Longsword", "kind":"weapon", "cost":1500, "weight":4, "damage":"1d8", "small_damage":"1d6", "group":"martial"},
    "rapier": {"name":"Rapier", "kind":"weapon", "cost":2000, "weight":2, "damage":"1d6", "small_damage":"1d4", "finesse":True, "group":"martial"},
    "shortsword": {"name":"Shortsword", "kind":"weapon", "cost":1000, "weight":2, "damage":"1d6", "small_damage":"1d4", "finesse":True, "group":"martial"},
    "greataxe": {"name":"Greataxe", "kind":"weapon", "cost":2000, "weight":12, "damage":"1d12", "small_damage":"1d10", "two_handed":True, "group":"martial"},
    "shortbow": {"name":"Shortbow", "kind":"weapon", "cost":3000, "weight":2, "damage":"1d6", "small_damage":"1d4", "ranged":True, "bow":True, "group":"martial"},
    "longbow": {"name":"Longbow", "kind":"weapon", "cost":7500, "weight":3, "damage":"1d8", "small_damage":"1d6", "ranged":True, "bow":True, "group":"martial"},
    "light-crossbow": {"name":"Light crossbow", "kind":"weapon", "cost":3500, "weight":4, "damage":"1d8", "small_damage":"1d6", "ranged":True, "group":"simple"},
    "padded": {"name":"Padded armor", "kind":"armor", "cost":500, "weight":10, "armor":1, "max_dex":8, "acp":0, "category":"light"},
    "leather": {"name":"Leather armor", "kind":"armor", "cost":1000, "weight":15, "armor":2, "max_dex":6, "acp":0, "category":"light"},
    "studded-leather": {"name":"Studded leather", "kind":"armor", "cost":2500, "weight":20, "armor":3, "max_dex":5, "acp":-1, "category":"light"},
    "chain-shirt": {"name":"Chain shirt", "kind":"armor", "cost":10000, "weight":25, "armor":4, "max_dex":4, "acp":-2, "category":"light"},
    "hide": {"name":"Hide armor", "kind":"armor", "cost":1500, "weight":25, "armor":4, "max_dex":4, "acp":-3, "category":"medium"},
    "scale-mail": {"name":"Scale mail", "kind":"armor", "cost":5000, "weight":30, "armor":5, "max_dex":3, "acp":-4, "category":"medium"},
    "light-shield": {"name":"Light wooden shield", "kind":"shield", "cost":300, "weight":5, "shield":1, "acp":-1},
    "heavy-shield": {"name":"Heavy wooden shield", "kind":"shield", "cost":700, "weight":10, "shield":2, "acp":-2},
    "backpack": {"name":"Backpack", "kind":"gear", "cost":200, "weight":2},
    "bedroll": {"name":"Bedroll", "kind":"gear", "cost":10, "weight":5},
    "rations": {"name":"Trail rations (1 day)", "kind":"gear", "cost":50, "weight":1},
    "waterskin": {"name":"Waterskin (full)", "kind":"gear", "cost":100, "weight":4},
    "rope": {"name":"Hemp rope (50 ft.)", "kind":"gear", "cost":100, "weight":10},
    "torch": {"name":"Torch", "kind":"gear", "cost":1, "weight":1},
    "arrows": {"name":"Arrows (20)", "kind":"gear", "cost":100, "weight":3},
    "bolts": {"name":"Crossbow bolts (10)", "kind":"gear", "cost":100, "weight":1},
    "spellbook": {"name":"Blank spellbook", "kind":"gear", "cost":1500, "weight":3},
    "holy-symbol": {"name":"Wooden holy symbol", "kind":"gear", "cost":100, "weight":0},
    "thieves-tools": {"name":"Thieves' tools", "kind":"gear", "cost":3000, "weight":1},
    "outfit": {"name":"Starting outfit (free, up to 10 gp)", "kind":"gear", "cost":0, "weight":0},
}
SPELL_SUGGESTIONS = ["Alarm", "Bless", "Burning Hands", "Charm Person", "Color Spray", "Comprehend Languages", "Cure Light Wounds", "Detect Magic", "Enlarge Person", "Entangle", "Feather Fall", "Grease", "Identify", "Light", "Mage Armor", "Magic Missile", "Protection from Evil", "Read Magic", "Shield", "Sleep", "Summon Monster I", "Unseen Servant"]

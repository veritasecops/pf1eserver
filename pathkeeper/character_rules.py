"""Bounded inputs and server-side first-level calculations for the creation wizard."""
from copy import deepcopy
from math import floor

from fastapi import HTTPException

from .class_catalog import class_profile, creation_class
from .pf1_data import ABILITIES, ALIGNMENTS, CLASSES, EQUIPMENT, FEATS, MONK_BONUS, POINT_COST, RACES, SKILLS


def defaults(owner_id):
    return {"name":"", "owner_id":owner_id, "campaign_id":None, "method":"point_buy", "point_budget":15,
            "abilities":{key:10 for key in ABILITIES}, "ability_roll":"", "assignments":list(range(6)),
            "race":"human", "flex_ability":"str", "class_id":"", "favored_bonus":"hp", "vigilante_specialization":"stalker",
            "skills":{}, "expert_skills":[], "skill_specialties":"", "feats":[], "bonus_feat":{},
            "adaptability":"perception", "wealth_method":"average", "wealth_roll":"", "manual_gold":0,
            "equipment":{}, "equipment_prices":{}, "armor":"", "shield":"", "weapon":"", "extra_spending":0,
            "inventory_notes":"", "alignment":"N", "age":"", "gender":"", "appearance":"",
            "personality":"", "languages":"", "deity":"", "notes":"", "spells":[], "cantrips":[], "spell_notes":""}


def bounded_int(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise HTTPException(422, f"{name} must be a whole number between {low} and {high}.")
    return value


def clean(payload, owner_id, catalog=None):
    from .rule_catalog import default_catalog, equipment
    catalog = catalog or default_catalog()
    SKILLS, EQUIPMENT = catalog['skills'], equipment(catalog)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Enter a character draft object.")
    data = defaults(owner_id)
    if set(payload) - set(data):
        raise HTTPException(422, "The draft contains unsupported fields. Reload the wizard.")
    data.update(deepcopy(payload))
    for key, maximum in {"name":150,"skill_specialties":1000,"inventory_notes":3000,"age":30,
                         "gender":80,"appearance":2000,"personality":2000,"languages":500,"deity":100,"notes":10000,"spell_notes":3000}.items():
        if not isinstance(data[key], str) or len(data[key]) > maximum:
            raise HTTPException(422, f"{key.replace('_',' ').capitalize()} is too long or invalid.")
        data[key] = data[key].strip()
    for key, choices in {"method":{"point_buy","standard","classic","heroic","manual"}, "race":RACES,
                         "class_id":{"",*CLASSES}, "flex_ability":ABILITIES, "favored_bonus":{"hp","skill","none"},
                         "wealth_method":{"average","rolled","manual"}, "vigilante_specialization":{"stalker","avenger"}, "alignment":ALIGNMENTS}.items():
        if not isinstance(data[key], str) or data[key] not in choices:
            raise HTTPException(422, f"Choose a valid {key.replace('_',' ')}.")
    data["owner_id"] = bounded_int(data["owner_id"], 1, 2**63-1, "Owner")
    if data["campaign_id"] is not None:
        data["campaign_id"] = bounded_int(data["campaign_id"], 1, 2**63-1, "Campaign")
    if type(data["point_budget"]) is not int or data["point_budget"] not in {10,15,20,25}:
        raise HTTPException(422, "Choose a 10, 15, 20, or 25 point budget.")
    for key in ("manual_gold", "extra_spending"):
        data[key] = bounded_int(data[key], 0, 100000000, key.replace("_", " "))
    if not isinstance(data["abilities"], dict) or set(data["abilities"]) != set(ABILITIES):
        raise HTTPException(422, "Enter all six ability scores.")
    data["abilities"] = {key:bounded_int(data["abilities"][key],1,30,ABILITIES[key]) for key in ABILITIES}
    for key in ("ability_roll", "wealth_roll"):
        if not isinstance(data[key], str) or len(data[key]) > 32:
            raise HTTPException(422, "Choose a valid saved roll.")
    if not isinstance(data["assignments"], list) or len(data["assignments"]) != 6 or any(type(value) is not int or not 0 <= value <= 5 for value in data["assignments"]):
        raise HTTPException(422, "Assign six rolled scores.")
    if not isinstance(data["skills"], dict) or set(data["skills"]) - set(SKILLS):
        raise HTTPException(422, "Choose skills from the skill list.")
    data["skills"] = {key:bounded_int(value,0,1,"First-level skill ranks") for key,value in data["skills"].items()}
    expert_skills = data["expert_skills"]
    if not isinstance(expert_skills, list) or len(expert_skills) > 10 or any(
        not isinstance(key, str) or key not in SKILLS for key in expert_skills
    ) or len(set(expert_skills)) != len(expert_skills):
        raise HTTPException(422, "Select up to ten different Expert class skills.")
    if data["class_id"] != "expert":
        data["expert_skills"] = []
    if not isinstance(data["adaptability"],str) or data["adaptability"] not in SKILLS:
        raise HTTPException(422, "Choose a skill for half-elf adaptability.")
    if not isinstance(data["feats"], list) or len(data["feats"]) > 2:
        raise HTTPException(422, "Too many general feats for first level.")
    if not isinstance(data["bonus_feat"], dict):
        raise HTTPException(422, "Choose a class bonus feat.")
    for entry in data["feats"] + ([data["bonus_feat"]] if data["bonus_feat"] else []):
        if not isinstance(entry, dict) or set(entry) - {"name","choice"}:
            raise HTTPException(422, "Enter a feat name and optional choice.")
        if any(not isinstance(entry.get(key,""),str) or len(entry.get(key,"")) > 100 for key in ("name","choice")):
            raise HTTPException(422, "Feat names and choices must be 100 characters or fewer.")
    if not isinstance(data["equipment"], dict) or set(data["equipment"]) - set(EQUIPMENT):
        raise HTTPException(422, "Choose equipment from the catalog; record other gear in notes.")
    data["equipment"] = {key:bounded_int(value,0,100,"Equipment quantity") for key,value in data["equipment"].items()}
    if not isinstance(data['equipment_prices'],dict) or set(data['equipment_prices'])-set(EQUIPMENT):
        raise HTTPException(422,'Choose agreed prices for catalog equipment only.')
    data['equipment_prices']={key:bounded_int(value,0,100000000,'Agreed equipment price') for key,value in data['equipment_prices'].items()}
    if data["equipment"].get("outfit",0) > 1:
        raise HTTPException(422, "Only one starting outfit is free.")
    for key, kind in (("armor","armor"),("shield","shield"),("weapon","weapon")):
        if not isinstance(data[key],str) or data[key] and (data[key] not in EQUIPMENT or EQUIPMENT[data[key]]["kind"] != kind):
            raise HTTPException(422, f"Choose a valid {key}.")
    for key in ("spells","cantrips"):
        if not isinstance(data[key],list) or len(data[key]) > 80 or any(not isinstance(value,str) or not 1 <= len(value.strip()) <= 100 for value in data[key]):
            raise HTTPException(422, "Enter spell names of 1–100 characters, one per line.")
        data[key] = [value.strip() for value in data[key]]
    return data


def calculate(data, rolls, catalog=None):
    from .rule_catalog import default_catalog, equipment, effect_total, class_skills as skill_list
    catalog = catalog or default_catalog()
    FEATS, SKILLS, EQUIPMENT = catalog['feats'], catalog['skills'], equipment(catalog)
    MONK_BONUS = [name for name,meta in FEATS.items() if meta.get('monk')]
    errors, warnings = [], []
    def error(step, message): errors.append({"step":step,"message":message})
    race, cls = RACES[data["race"]], creation_class(catalog, data["class_id"])
    base = dict(data["abilities"])
    method = data["method"]
    if method in {"standard","classic","heroic"}:
        roll = rolls.get(data["ability_roll"])
        if not roll or roll["purpose"] != "ability" or roll["result"].get("method") != method:
            error(2, "Roll a set of six ability scores using the selected method.")
        elif len(set(data["assignments"])) != 6:
            error(2, "Use each rolled score exactly once.")
        else:
            base = {key:roll["result"]["groups"][data["assignments"][index]]["total"] for index,key in enumerate(ABILITIES)}
    point_spent = sum(POINT_COST.get(value,0) for value in base.values())
    if method == "point_buy":
        if any(value not in POINT_COST for value in base.values()): error(2, "Point-buy scores must be between 7 and 18 before racial adjustments.")
        if point_spent > data["point_budget"]: error(2, "The ability scores exceed the selected point budget.")
        elif point_spent < data["point_budget"]: warnings.append(f"{data['point_budget'] - point_spent} ability points remain unspent.")
    if method == "manual": warnings.append("Manual ability scores require your GM's approval.")
    racial = {key:race["mods"].get(key,0) + (2 if race.get("flex") and data["flex_ability"] == key else 0) for key in ABILITIES}
    scores = {key:base[key] + racial[key] for key in ABILITIES}
    if min(scores.values()) < 1: error(3, "A racial adjustment reduces an ability below 1.")
    modifiers = {key:(value-10)//2 for key,value in scores.items()}
    if not data["name"]: error(10, "Give your character a name.")
    if not cls: error(4, "Choose a class.")
    else:
        if data["class_id"] == "antipaladin" and data["alignment"] != "CE": error(10, "A standard antipaladin must be chaotic evil.")
        if data["class_id"] == "paladin" and data["alignment"] != "LG": error(10, "A standard paladin must be lawful good.")
        if data["class_id"] in {"monk", "monk-unchained"} and not data["alignment"].startswith("L"): error(10, "A standard monk must have a lawful alignment.")
        if data["class_id"] in {"barbarian", "barbarian-unchained"} and data["alignment"].startswith("L"): error(10, "A standard barbarian cannot have a lawful alignment.")
        if data["class_id"] in {"druid","shifter"} and "N" not in data["alignment"]: error(10, "A standard druid or shifter must have a neutral alignment component.")
    general_slots = 1 + (data["race"] == "human")
    feat_entries = [entry for entry in data["feats"] if entry.get("name","").strip()]
    if len(feat_entries) != general_slots: error(6, f"Choose {general_slots} general feat{'s' if general_slots != 1 else ''}.")
    bonus = cls["bonus_feat"] if cls else ""
    if bonus and not data["bonus_feat"].get("name","").strip(): error(6, "Choose the class bonus feat.")
    if bonus and data["bonus_feat"].get("name"): feat_entries += [data["bonus_feat"]]
    automatic = cls["automatic_feats"] if cls else []
    if data["race"] == "half-elf": feat_entries += [{"name":"Skill Focus","choice":data["adaptability"]}]
    feat_names = [entry["name"].strip() for entry in feat_entries] + automatic
    seen = set()
    bab = cls["bab"] if cls else 0
    if data["class_id"] == "vigilante" and data.get("vigilante_specialization","stalker") == "avenger": bab = 1
    for entry in feat_entries:
        name, choice = entry["name"].strip(), entry.get("choice","").strip()
        metadata = FEATS.get(name)
        identity = (name,choice if (metadata or {}).get("repeatable") else "")
        if identity in seen or name in automatic: error(6, f"{name} is already included; choose another feat.")
        seen.add(identity)
        monk_bonus = bonus == "monk" and entry == data["bonus_feat"]
        if not metadata:
            warnings.append(f"Confirm {name} and its prerequisites with your GM; custom feat effects are recorded but not calculated.")
            continue
        if not metadata.get("enabled",True): error(6, f"{name} is archived; choose another feat.")
        if not monk_bonus:
            for ability in ABILITIES:
                if modifiers is not None and scores[ability] < metadata.get(ability,0): error(6, f"{name} needs {ABILITIES[ability]} {metadata[ability]}.")
            if bab < metadata.get("bab",0): error(6, f"{name} needs base attack bonus +{metadata['bab']}.")
            if metadata.get("requires") and metadata["requires"] not in feat_names: error(6, f"{name} requires {metadata['requires']}.")
        if metadata.get("choice") == "skill" and choice not in SKILLS: error(6, f"Choose a skill for {name}.")
        if metadata.get("choice") == "weapon" and (choice not in EQUIPMENT or EQUIPMENT[choice]["kind"] != "weapon"): error(6, "Choose a weapon for Weapon Focus.")
    if bonus == "combat" and data["bonus_feat"].get("name") in FEATS and not FEATS[data["bonus_feat"]["name"]].get("combat"):
        error(6, "A fighter's class bonus feat must be a combat feat.")
    if bonus == "monk" and data["bonus_feat"].get("name") not in MONK_BONUS: error(6, "Choose one of the first-level monk bonus feats.")
    if bonus in {"teamwork","technique"}: warnings.append(f"Confirm the class {bonus} feat and its prerequisites with your GM.")
    effects = lambda target, choice=None: effect_total(feat_entries + [{"name":name} for name in automatic], catalog, target, choice)
    hp = max(1, (cls["hd"] if cls else 0) + modifiers["con"]) + (data["favored_bonus"] == "hp") + effects("hp")
    skill_budget = max(1,(cls["ranks"] if cls else 0) + modifiers["int"]) + (data["race"] == "human") + (data["favored_bonus"] == "skill")
    for key,ranks in data['skills'].items():
        if ranks and not SKILLS[key].get('enabled',True): error(5,f"{SKILLS[key]['name']} is archived; remove its rank.")
    for entry in feat_entries:
        choice = entry.get('choice','')
        kind = FEATS.get(entry.get('name'),{}).get('choice')
        if kind == 'skill' and choice in SKILLS and not SKILLS[choice].get('enabled',True): error(6,'Choose an available skill for the feat.')
        if kind == 'weapon' and choice in EQUIPMENT and not EQUIPMENT[choice].get('enabled',True): error(6,'Choose an available weapon for the feat.')
    ranks_used = sum(data["skills"].values())
    if ranks_used != skill_budget: error(5, f"Allocate exactly {skill_budget} skill ranks; {ranks_used} are assigned.")
    if data["class_id"] == "expert" and len(data.get("expert_skills", ())) != 10:
        error(4, "Choose ten Expert class skills.")
    class_skills = set(skill_list(catalog, data["class_id"], data.get("expert_skills", ())))
    gold = (cls["wealth_dice"] * 3500 if cls else 0)
    if cls and not cls["wealth_dice"] and data["wealth_method"] != "manual":
        error(8, "Enter GM-approved starting wealth for this NPC class.")
    if data["wealth_method"] == "rolled":
        wealth = rolls.get(data["wealth_roll"])
        if not wealth or wealth["purpose"] != "wealth" or wealth["result"].get("class_id") != data["class_id"] or len(wealth["result"].get("dice", ())) != (cls["wealth_dice"] if cls else 0):
            error(8, "Roll starting wealth for the selected class.")
        else: gold = wealth["result"]["gold_cp"]
    elif data["wealth_method"] == "manual":
        gold = data["manual_gold"]
        warnings.append("Manual starting wealth requires your GM's approval.")
    equipment = [{"id":key,"quantity":quantity,**EQUIPMENT[key],
                  "cost":EQUIPMENT[key]['cost'] if EQUIPMENT[key]['cost'] is not None else data.get('equipment_prices',{}).get(key)}
                 for key,quantity in data["equipment"].items() if quantity]
    for item in equipment:
        if not item.get("enabled",True): error(8,f"{item['name']} is archived; remove it from starting equipment.")
    spent = sum((item["cost"] or 0)*item["quantity"] for item in equipment) + data["extra_spending"]
    for item in equipment:
        if item.get('cost') is None: warnings.append(f"{item['name']} has a special or variable price ({item.get('cost_text','see reference')}); enter its actual cost under Other equipment cost.")
        if item.get('weight') is None: warnings.append(f"{item['name']} has an unspecified weight; its weight is excluded from the inventory total. Record the actual weight on the sheet.")
    if spent > gold: error(8, "Equipment costs exceed starting wealth.")
    for slot in ("armor","shield","weapon"):
        if data[slot] and not data["equipment"].get(data[slot]): error(8, f"Add the equipped {slot} to inventory first.")
    armor, shield, weapon = (EQUIPMENT.get(data[key],{}) for key in ("armor","shield","weapon"))
    dex_ac = min(modifiers["dex"], armor.get("max_dex",100), shield.get("max_dex",100))
    acp = armor.get("acp",0) + shield.get("acp",0)
    small = race["size"] == "Small"
    dodge = effects("dodge")
    monk_ac = modifiers["wis"] if data["class_id"] in {"monk", "monk-unchained"} and not armor and not shield else 0
    ac = 10 + armor.get("armor",0) + shield.get("shield",0) + dex_ac + small + dodge + monk_ac
    skill_totals = {}
    for key, metadata in SKILLS.items():
        ranks = data["skills"].get(key,0)
        bonus_value = metadata.get("bonus",0)
        if key == "perception" and data["race"] in {"elf","half-elf","gnome","halfling"}: bonus_value += 2
        if key == "intimidate" and data["race"] == "half-orc": bonus_value += 2
        if key in {"acrobatics","climb"} and data["race"] == "halfling": bonus_value += 2
        if key == "stealth" and small: bonus_value += 4
        if key == "fly" and small: bonus_value += 2
        bonus_value += effects("skill:"+key) + effects("selected_skill",key)
        skill_totals[key] = ranks + modifiers[metadata["ability"]] + (3 if ranks and key in class_skills else 0) + bonus_value + (acp if metadata["armor"] else 0)
    saves = {key:(cls["saves"][index] if cls else 0) + modifiers[ability] + (data["race"] == "halfling") + effects(key)
             for index,(key,ability,feat) in enumerate((("fortitude","con","Great Fortitude"),("reflex","dex","Lightning Reflexes"),("will","wis","Iron Will")))}
    initiative = modifiers["dex"] + effects("initiative")
    attack_mod = modifiers["dex"] if weapon.get("ranged") or weapon.get("finesse") and any(FEATS.get(name,{}).get("finesse") for name in feat_names) else modifiers["str"]
    weapon_focus = effects("selected_weapon",data["weapon"])
    damage_mod = 0 if weapon.get("ranged") else modifiers["str"]
    if weapon.get('ranged') and weapon.get('add_strength'): damage_mod = modifiers['str']
    composite_penalty = 0
    if weapon.get("bow"):
        rating = weapon.get('strength_rating')
        damage_mod = min(modifiers['str'],rating) if rating is not None else min(0,modifiers['str'])
        if rating is not None and modifiers['str'] < rating: composite_penalty = -2
    if weapon.get("two_handed") and not weapon.get("ranged") and damage_mod > 0: damage_mod = floor(damage_mod*1.5)
    if weapon.get("damage") in {"—","see text","See text",""}: damage_mod = 0
    if armor or shield: warnings.append("Confirm armor/shield proficiency and spell failure; nonproficiency and spell failure are not applied automatically.")
    if weapon: warnings.append("Attack assumes weapon proficiency. Conditional combat actions and temporary effects are applied during play.")
    if data["class_id"] in {"druid","shifter"} and data["armor"] in {"chain-shirt","scale-mail","studded-leather"}: warnings.append("Review the class's restrictions on metal armor with your GM.")
    caster = cls["caster"] if cls else ""
    progression = class_profile(catalog, data["class_id"]) if cls else {}
    starting_known = progression["levels"][0].get("known", {}) if progression else {}
    spell_count = starting_known.get("1")
    if progression.get("starting_book"):
        spell_count = progression["starting_book"] + max(0, modifiers["int"])
    if spell_count is not None and len(data["spells"]) != spell_count: error(11, f"Record {spell_count} starting first-level spells or formulae, one per line.")
    if len(set(name.casefold() for name in data["spells"])) != len(data["spells"]): error(11, "Choose different starting spells rather than repeating the same name.")
    if caster:
        if scores[caster] < 11: warnings.append(f"{ABILITIES[caster]} is below 11; you cannot cast first-level spells using the normal class rules.")
        warnings.append("Confirm spell names, class lists, opposition schools, domain/mystery additions, and prepared spells with your GM.")
    speed = race["speed"] + (10 if data["class_id"] in {"barbarian", "barbarian-unchained"} and armor.get("category") != "heavy" else 0)
    if armor.get("category") in {"medium","heavy"} and data["race"] != "dwarf": speed = armor.get("speed_"+str(speed)) or {20:15,30:20,40:30}.get(speed,speed)
    cantrip_count = starting_known.get("0")
    if cantrip_count is not None and len(data["cantrips"]) != cantrip_count: error(11, f"Record {cantrip_count} different starting cantrips or orisons.")
    if len(set(name.casefold() for name in data["cantrips"])) != len(data["cantrips"]): error(11,"Do not repeat cantrip or orison names.")
    if data["class_id"] == "oracle" and len(data["spells"]) != 2: error(11,"Record two chosen first-level oracle spells; record the free cure/inflict spell separately in spell notes.")
    languages = race["languages"] + (", Druidic" if data["class_id"] == "druid" else "")
    return {"base":base,"racial":racial,"scores":scores,"modifiers":modifiers,"point_spent":point_spent,
            "hp":hp,"skill_budget":skill_budget,"ranks_used":ranks_used,"class_skills":sorted(class_skills),"skill_totals":skill_totals,
            "general_slots":general_slots,"bonus_feat":bonus,"automatic_feats":automatic,"feats":feat_entries,
            "gold_cp":gold,"spent_cp":spent,"remaining_cp":gold-spent,"equipment":equipment,
            "weight":sum((item["weight"] or 0)*item["quantity"]*(.5 if small and item["kind"] in {"armor","shield","weapon"} else 1) for item in equipment),
            "ac":ac,"touch_ac":10+dex_ac+small+dodge+monk_ac,"flat_ac":10+armor.get("armor",0)+shield.get("shield",0)+min(0,dex_ac)+small+monk_ac,
            "armor_check_penalty":acp,"saves":saves,"initiative":initiative,"bab":bab,"melee":bab+modifiers["str"]+small,
            "ranged":bab+modifiers["dex"]+small,"cmb":bab+modifiers["str"]-small,"cmd":10+bab+modifiers["str"]+modifiers["dex"]-small+dodge+monk_ac,
            "weapon_attack":bab+attack_mod+small+weapon_focus+composite_penalty,"weapon_damage":weapon.get("small_damage" if small else "damage",("1d4" if small else "1d6") if data["class_id"] == "monk" else ("1d2" if small else "1d3")),
            "damage_modifier":damage_mod,"speed":speed,"automatic_languages":languages,"bonus_languages":max(0,modifiers["int"]),
            "caster":caster,"spell_count":spell_count,"cantrip_count":cantrip_count,"spell_dc":11+modifiers.get(caster,0),"errors":errors,"warnings":list(dict.fromkeys(warnings))}

"""Versioned rule data. Creation snapshots retain the rules used to create them."""
from copy import deepcopy

from .models import RuleCatalog
from .pf1_data import CLASSES, EQUIPMENT, FEATS, MONK_BONUS, SKILLS

EFFECTS = {
    'hp': 'Hit points (first level)', 'initiative': 'Initiative', 'dodge': 'Dodge AC and CMD',
    'fortitude': 'Fortitude save', 'reflex': 'Reflex save', 'will': 'Will save',
    'selected_skill': 'Selected skill', 'selected_weapon': 'Selected weapon attack',
}


def default_catalog(legacy=False):
    feats, skills = deepcopy(FEATS), deepcopy(SKILLS)
    for name, meta in feats.items():
        meta.update(enabled=True, monk=name in MONK_BONUS, repeatable=name in {'Skill Focus','Weapon Focus'}, effects={})
    for name, key, amount in [('Toughness','hp',3),('Improved Initiative','initiative',4),('Dodge','dodge',1),
                              ('Great Fortitude','fortitude',2),('Lightning Reflexes','reflex',2),('Iron Will','will',2),
                              ('Skill Focus','selected_skill',3),('Weapon Focus','selected_weapon',1)]:
        feats[name]['effects'][key] = amount
    feats['Alertness']['effects'] = {'skill:perception':2,'skill:sense-motive':2}
    feats['Weapon Finesse']['finesse'] = True
    trained = {'disable-device','handle-animal','linguistics','profession','sleight-of-hand','spellcraft','use-magic-device'}
    for key, meta in skills.items():
        meta.update(enabled=True, bonus=0, trained=key in trained or key.startswith('knowledge-'),
                    classes=[name for name,cls in CLASSES.items() if key in cls['skills']])
    from .weapons import table_weapons
    weapons = {key:{**deepcopy(value),'enabled':True} for key,value in EQUIPMENT.items() if value['kind']=='weapon'} if legacy else deepcopy(table_weapons())
    from .armor import table_armor
    armor={key:{**deepcopy(value),'enabled':True} for key,value in EQUIPMENT.items() if value['kind'] in {'armor','shield'}} if legacy else deepcopy(table_armor())
    for key,item in armor.items():
        if key in EQUIPMENT: item['aliases']=list(dict.fromkeys([*item.get('aliases',[]),EQUIPMENT[key]['name']]))
    return {'feats':feats, 'skills':skills, 'weapons':weapons, 'armor':armor}


def load_catalog(db):
    if 'rule_catalog' not in db.info:
        record = db.get(RuleCatalog, 1)
        db.info['rule_catalog'] = deepcopy(record.data) if record else default_catalog()
    return db.info['rule_catalog']


def equipment(catalog):
    return {**EQUIPMENT, **catalog['weapons'], **catalog.get('armor',{})}


def class_skills(catalog, class_id):
    return [key for key,meta in catalog['skills'].items() if class_id in meta.get('classes',[])]


def effect_total(feats, catalog, target, choice=None):
    # Multiple copies with the same choice never stack their own bonus.
    seen, total = set(), 0
    for feat in feats:
        identity = (feat.get('name'),feat.get('choice',''))
        if identity in seen: continue
        seen.add(identity)
        meta = catalog['feats'].get(feat.get('name'),{})
        if target.startswith('selected_') and feat.get('choice') != choice: continue
        total += meta.get('effects',{}).get(target,0)
    return total


def character_catalog(character):
    return (character.sheet_data or {}).get('catalog') or default_catalog(legacy=True)

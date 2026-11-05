"""Derived play-sheet totals. Inputs and situational bonuses remain editable."""
from decimal import Decimal, InvalidOperation
from math import floor

from .class_catalog import class_key, creation_class
from .pf1_data import ABILITIES, RACES
from .rule_catalog import character_catalog, class_skills as skill_list, effect_total


def class_record(character, catalog):
    return creation_class(catalog, class_key(character, catalog)) or {}


def base_speed_race(character):
    selected=(character.sheet_data or {}).get('input',{}).get('race')
    return RACES.get(selected) or next((race for race in RACES.values() if race['name'].casefold()==str(character.ancestry or '').casefold()),{})


def calculated_fields(character, values):
    SKILLS = character_catalog(character)["skills"]
    locked = {'level','next_level','player','class_name','speed.base','initiative.total','initiative.dex','cmb.total','cmd.total',
              'ac.total','ac.flat','ac.touch','skill_points.total','skill_points.int','load.total'}
    for ability in ABILITIES:
        locked.update({f'ability.{ability}.mod',f'ability.{ability}.temp_mod'})
    for save in ('fortitude','reflex','will'):
        locked.update({f'save.{save}.total',f'save.{save}.ability'})
    for kind in ('cmb','cmd'):
        locked.update(f'{kind}.{part}' for part in ('bab','str'))
    locked.add('cmd.dex')
    # Size modifiers are automatic when the entered size is recognized.
    if str(values.get('size','')).casefold() in SIZE_MODIFIERS:
        locked.update({'ac.size','cmb.size','cmd.size'})
    for skill in SKILLS:
        for key in (skill,skill+'-2') if skill in {'craft','perform','profession'} else (skill,):
            locked.update({f'skill.{key}.total',f'skill.{key}.ability'})
    locked.update(f'weapon.{row}.{part}' for row in range(6) for part in ('name','quantity','attack','critical','type','range','ammunition','damage'))
    locked.update(f'armor.{row}.{part}' for row in range(6) for part in ('name','quantity','type','bonus','max_dex','penalty','failure','weight'))
    locked.update(f'spell.{level}.known' for level in range(10))
    # These are calculated by the first-level wizard. At later levels they need
    # manual advancement because hit-die rolls and class progression aren't recorded.
    if int(values.get("level") or character.level) == 1 and (character.sheet_data or {}).get('computed'):
        locked.update(key for key in ('hp.total','bab','skill_points.base',
                      'save.fortitude.base','save.reflex.base','save.will.base') if values.get(key,'') != '')
    return locked


SIZE_MODIFIERS = {'fine':8,'diminutive':4,'tiny':2,'small':1,'medium':0,'large':-1,'huge':-2,'gargantuan':-4,'colossal':-8}


def recalculate(character, values, equipment_previous=None, equipment_keep=()):
    """Recompute from editable components; a missing essential input stays blank."""
    race=base_speed_race(character)
    if race: values['speed.base']=str(race['speed'])
    catalog = character_catalog(character)
    SKILLS = catalog["skills"]
    def number(key, default=None):
        value = values.get(key,'')
        if value == '': return default
        try:
            value = Decimal(str(value))
            return value if value.is_finite() and value.copy_abs() <= 1000000000 else None
        except InvalidOperation:
            return None

    def write(key, value):
        if value is None:
            values[key] = ''
        elif isinstance(value,Decimal) and value != value.to_integral_value():
            values[key] = format(value,'f').rstrip('0').rstrip('.')
        else:
            values[key] = str(int(value))

    def total(key, required, optional=(), constant=0):
        parts = [number(part) for part in required] + [number(part,Decimal(0)) for part in optional]
        write(key,None if any(part is None for part in parts) else sum(parts,Decimal(constant)))

    def modifier(ability):
        return number(f'ability.{ability}.temp_mod') if values.get(f'ability.{ability}.temp_score','') != '' else number(f'ability.{ability}.mod')

    for ability in ABILITIES:
        for score,mod in [('score','mod'),('temp_score','temp_mod')]:
            value = number(f'ability.{ability}.{score}')
            write(f'ability.{ability}.{mod}',None if value is None else floor((value-10)/2))
    cls = class_record(character, catalog)
    snapshot = character.sheet_data or {}
    if int(values.get("level") or character.level) == 1 and snapshot.get('computed') and cls:
        con = modifier('con')
        inputs = snapshot.get('input',{})
        feats = snapshot['computed'].get('feats',[])
        extra_hp = int(inputs.get('favored_bonus') == 'hp') + effect_total(feats + [{'name':name} for name in snapshot['computed'].get('automatic_feats',[])],catalog,'hp')
        write('hp.total',None if con is None else max(Decimal(1),Decimal(cls['hd'])+con)+extra_hp)
        write('bab',snapshot['computed'].get('bab',cls['bab']))
        write('skill_points.base',cls['ranks'])
        for index,save in enumerate(('fortitude','reflex','will')):
            write(f'save.{save}.base',cls['saves'][index])
    dex,strength,intelligence = modifier('dex'),modifier('str'),modifier('int')
    write('initiative.dex',dex)
    total('initiative.total',['initiative.dex'],['initiative.misc'])
    for save,ability in [('fortitude','con'),('reflex','dex'),('will','wis')]:
        write(f'save.{save}.ability',modifier(ability))
        total(f'save.{save}.total',[f'save.{save}.base',f'save.{save}.ability'],[f'save.{save}.magic',f'save.{save}.misc'])
    for kind in ('cmb','cmd'):
        write(f'{kind}.bab',number('bab'))
        write(f'{kind}.str',strength)
    write('cmd.dex',dex)
    size = SIZE_MODIFIERS.get(str(values.get('size','')).casefold())
    if size is not None:
        write('ac.size',size)
        write('cmb.size',-size)
        write('cmd.size',-size)
    total('cmb.total',['cmb.bab','cmb.str','cmb.size'],['cmb.misc'])
    total('cmd.total',['cmd.bab','cmd.str','cmd.dex','cmd.size'],['cmd.misc'],10)
    from .equipment_effects import apply_effects
    apply_effects(character, values, equipment_previous, equipment_keep)
    ac_parts = ['ac.armor','ac.shield','ac.dex','ac.size','ac.natural','ac.deflection','ac.dodge','ac.misc']
    total('cmd.total',['cmd.bab','cmd.str','cmd.dex','cmd.size'],['cmd.misc'],10)
    total('ac.total',[],ac_parts,10)
    total('ac.touch',[],['ac.dex','ac.size','ac.deflection','ac.dodge','ac.misc'],10)
    # Positive Dexterity and dodge bonuses don't apply while flat-footed.
    parts = [number(part,Decimal(0)) for part in ac_parts if part not in {'ac.dex','ac.dodge'}]
    ac_dex = number('ac.dex',Decimal(0))
    write('ac.flat',None if ac_dex is None or any(p is None for p in parts) else Decimal(10)+sum(parts)+min(Decimal(0),ac_dex))
    class_skills = set(skill_list(catalog, snapshot.get('input',{}).get('class_id',''), snapshot.get('input',{}).get('expert_skills',()))) if snapshot else set(cls.get('skills',[]))
    for key,meta in SKILLS.items():
        for row in (key,key+'-2') if key in {'craft','perform','profession'} else (key,):
            write(f'skill.{row}.ability',modifier(meta['ability']))
            ranks = number(f'skill.{row}.ranks',Decimal(0))
            total(f'skill.{row}.total',[f'skill.{row}.ability'],[f'skill.{row}.ranks',f'skill.{row}.misc'],3 if ranks is not None and ranks > 0 and key in class_skills else 0)
    write('skill_points.int',intelligence)
    base = number('skill_points.base')
    misc = number('skill_points.misc',Decimal(0))
    write('skill_points.total',None if base is None or intelligence is None or misc is None else max(Decimal(1),base+intelligence)+misc)
    for level in range(10):
        write(f'spell.{level}.known',len([line for line in values.get(f'spell.{level}.list','').splitlines() if line.strip()]))
    weights = [number(f'gear.{row}.weight') for row in range(56) if values.get(f'gear.{row}.name', '').strip()]
    write('load.total', None if any(weight is None for weight in weights) else sum(weights, Decimal(0)))
    from .character_weapons import apply_inventory
    return apply_inventory(character,values)

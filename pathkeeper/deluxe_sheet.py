"""Editable play records, laid out like the four-page deluxe character sheet."""
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from .pf1_data import ABILITIES, ALIGNMENTS, CLASSES, EQUIPMENT, RACES, SKILLS
from .sheet_calculations import calculated_fields, recalculate

WEAPON_COLUMNS = [('name','Weapon'),('attack','Attack bonus'),('critical','Critical'),('type','Type'),('range','Range'),('ammunition','Ammunition'),('damage','Damage'),('notes','Notes')]
ARMOR_COLUMNS = [('name','Item'),('type','Type'),('bonus','Armor bonus'),('max_dex','Max Dex'),('penalty','Check penalty'),('failure','Spell failure'),('weight','Weight'),('notes','Notes')]
GEAR_COLUMNS = [('name','Item'),('weight','Weight')]
FACTION_COLUMNS = [('type','Type'),('value','Value')]
SAVES = [('fortitude','Fortitude','con'),('reflex','Reflex','dex'),('will','Will','wis')]
SKILL_ROWS = sorted([(key,meta) for key,meta in SKILLS.items()],key=lambda item:item[1]['name'])
for key in ('craft','perform','profession'):
    index = next(i for i,(name,_) in enumerate(SKILL_ROWS) if name == key)
    SKILL_ROWS.insert(index+1,(key+'-2',SKILLS[key]))
TRAINED_ONLY = {'disable-device','handle-animal','linguistics','profession','sleight-of-hand','spellcraft','use-magic-device'} | {k for k in SKILLS if k.startswith('knowledge-')}
FIELDS = {}


def register(key, label, kind='text', maximum=200):
    FIELDS[key] = {'label':label,'kind':kind,'maximum':maximum}


for key,label in [('name','Character name'),('alignment','Alignment'),('player','Player'),('class_name','Character class'),('deity','Deity'),('homeland','Homeland'),('ancestry','Race'),('size','Size'),('gender','Gender'),('age','Age'),('height','Height'),('weight','Weight'),('hair','Hair'),('eyes','Eyes'),('campaign','Campaign'),('gm','DM / Game Master')]:
    register(key,label,maximum=150 if key == 'name' else 100 if key in {'class_name','ancestry'} else 200)
register('level','Level','number')
FIELDS['alignment']['kind'] = 'select'
for ability,label in ABILITIES.items():
    for part,title in [('score','Ability score'),('mod','Ability modifier'),('temp_score','Temporary score'),('temp_mod','Temporary modifier')]:
        register(f'ability.{ability}.{part}',f'{label}: {title}','number')
for key,label in [('hp.total','Total hit points'),('hp.current','Current hit points'),('hp.nonlethal','Nonlethal damage'),('bab','Base attack bonus'),('initiative.total','Initiative total'),('initiative.dex','Initiative Dexterity modifier'),('initiative.misc','Initiative miscellaneous modifier')]:
    register(key,label,'number')
for key,label in [('base','Base speed'),('armor','Speed with armor'),('fly','Fly speed'),('climb','Climb speed'),('burrow','Burrow speed')]:
    register('speed.'+key,label+' (ft.)','number')
register('speed.maneuverability','Fly maneuverability')
for key,label,_ in SAVES:
    for part,title in [('total','Total'),('base','Base save'),('ability','Ability modifier'),('magic','Magic modifier'),('misc','Miscellaneous modifier')]:
        register(f'save.{key}.{part}',f'{label}: {title}','number')
for key in ('cmb','cmd'):
    for part in ('total','bab','str','dex','size','misc'):
        if key == 'cmb' and part == 'dex': continue
        register(f'{key}.{part}',f'{key.upper()}: {part.capitalize()}','number')
for part,title in [('total','Total'),('armor','Armor bonus'),('shield','Shield bonus'),('dex','Dexterity modifier'),('size','Size modifier'),('natural','Natural armor'),('deflection','Deflection bonus'),('dodge','Dodge bonus'),('misc','Miscellaneous modifier'),('flat','Flat-footed'),('touch','Touch')]:
    register('ac.'+part,'AC: '+title,'number')
for key,label in [('temporary_modifiers','Temporary modifiers'),('save_modifiers','Saving throw modifiers'),('combat_modifiers','Combat maneuver modifiers'),('languages','Languages'),('campaign_traits','Campaign traits'),('domain','Domain / school / special'),('spell_notes','Spell notes'),('appearance','Appearance'),('personality','Personality'),('inventory_notes','Inventory notes'),('skill_specialties','Skill specialties'),('notes','Notes')]:
    register(key,label,'textarea',10000 if key == 'notes' else 5000)
register('resistance.spell','Spell resistance','number')
for i in range(3):
    for part,title in [('damage','Damage reduction'),('bypass','Damage bypass'),('energy','Energy resistance'),('type','Energy type')]:
        register(f'resistance.{i}.{part}',f'{title} {i+1}')
for prefix,columns,count in [('weapon',WEAPON_COLUMNS,6),('armor',ARMOR_COLUMNS,6),('gear',GEAR_COLUMNS,56),('faction',FACTION_COLUMNS,4)]:
    for i in range(count):
        for part,title in columns: register(f'{prefix}.{i}.{part}',f'{prefix.capitalize()} {i+1}: {title}')
for i in range(56): register(f'feature.{i}',f'Feat, class or racial ability {i+1}',maximum=500)
for key,meta in SKILL_ROWS:
    for part,title in [('total','Total'),('ability','Ability modifier'),('ranks','Ranks'),('misc','Miscellaneous modifier')]:
        register(f'skill.{key}.{part}',f'{meta["name"]}{" (second specialty)" if key.endswith("-2") else ""}: {title}','number')
    if key.removesuffix('-2') in {'craft','perform','profession'}: register(f'skill.{key}.specialty',f'{meta["name"]} specialty {2 if key.endswith("-2") else 1}')
for key,title in [('skill_points.total','Skill points per level'),('skill_points.base','Base skill points'),('skill_points.int','Intelligence skill modifier'),('skill_points.misc','Other skill points'),('concentration','Concentration check'),('caster_level','Caster level check'),('experience','Experience'),('next_level','Next level'),('load.total','Total carried'),('load.light','Light load'),('load.medium','Medium load'),('load.heavy','Heavy load'),('load.overhead','Lift overhead'),('load.ground','Lift off ground'),('load.push','Push or pull'),('money.pp','Platinum pieces'),('money.gp','Gold pieces'),('money.sp','Silver pieces'),('money.cp','Copper pieces'),('money.stored','Gold stored')]:
    register(key,title,'number')
for level in range(10):
    for part,title in [('known','Spells known'),('dc','Save DC'),('daily','Spells per day'),('bonus','Bonus spells')]: register(f'spell.{level}.{part}',f'Level {level}: {title}','number')
    register(f'spell.{level}.list',f'{"Cantrips / orisons" if not level else "Level "+str(level)+" spells"}','textarea',10000)
    for slot in range(4 if level == 0 else 8): register(f'spell.{level}.used.{slot}',f'Level {level}: slot {slot+1} used','checkbox')


def baseline(character, owner, campaign=None, gm=None):
    """Seed existing creation data without changing a saved creation snapshot."""
    data = {key:'' for key in FIELDS}
    data.update(name=character.name,ancestry=character.ancestry,class_name=character.class_name,level=str(character.level),notes=character.notes,
                player=owner.name,campaign=campaign.name if campaign else '',gm=gm.name if gm else '')
    sheet = character.sheet_data or {}
    inputs,values = sheet.get('input',{}),sheet.get('computed',{})
    cls = next((value for value in CLASSES.values() if value['name'].casefold() == character.class_name.casefold()),{})
    race = RACES.get(inputs.get('race'),{})
    if not values: return data
    for key in ('alignment','gender','age','deity','appearance','personality','skill_specialties','spell_notes','inventory_notes'):
        data[key] = inputs.get(key,'')
    data['size'] = race.get('size','')
    data['languages'] = ', '.join(filter(None,[values.get('automatic_languages',''),inputs.get('languages','')]))
    for ability in ABILITIES:
        data[f'ability.{ability}.score'] = values.get('scores',{}).get(ability,'')
        data[f'ability.{ability}.mod'] = values.get('modifiers',{}).get(ability,'')
    for field,source in [('hp.total','hp'),('hp.current','hp'),('bab','bab'),('initiative.total','initiative'),('ac.total','ac'),('ac.flat','flat_ac'),('ac.touch','touch_ac'),('cmb.total','cmb'),('cmd.total','cmd'),('speed.armor','speed'),('skill_points.total','skill_budget'),('load.total','weight')]: data[field] = values.get(source,'')
    mods = values.get('modifiers',{})
    data['initiative.dex'] = mods.get('dex','')
    data['initiative.misc'] = values.get('initiative',0)-mods.get('dex',0)
    data['skill_points.base'],data['skill_points.int'] = cls.get('ranks',''),mods.get('int','')
    data['skill_points.misc'] = values.get('skill_budget',0)-cls.get('ranks',0)-mods.get('int',0)
    data['speed.base'] = race.get('speed','')
    for i,(key,_,ability) in enumerate(SAVES):
        base = cls.get('saves',[0,0,0])[i]
        total = values.get('saves',{}).get(key,0)
        data.update({f'save.{key}.total':total,f'save.{key}.base':base,f'save.{key}.ability':mods.get(ability,0),f'save.{key}.magic':0,f'save.{key}.misc':total-base-mods.get(ability,0)})
    small = race.get('size') == 'Small'
    for kind in ('cmb','cmd'):
        for part,value in [('bab',values.get('bab',0)),('str',mods.get('str',0)),('size',-int(small)),('misc',0)]: data[f'{kind}.{part}'] = value
    data['cmd.dex'] = mods.get('dex',0)
    data['cmd.misc'] = values.get('cmd',10)-10-values.get('bab',0)-mods.get('str',0)-mods.get('dex',0)+int(small)
    armor,shield = (EQUIPMENT.get(inputs.get(key),{}) for key in ('armor','shield'))
    dex = min(mods.get('dex',0),armor.get('max_dex',100))
    dodge = int(any(entry.get('name') == 'Dodge' for entry in values.get('feats',[])))
    data['ac.dodge'] = dodge
    for key,value in [('armor',armor.get('armor',0)),('shield',shield.get('shield',0)),('dex',dex),('size',int(small)),('natural',0),('deflection',0),('misc',values.get('ac',10)-10-armor.get('armor',0)-shield.get('shield',0)-dex-int(small)-dodge)]: data['ac.'+key] = value
    for key,meta in SKILL_ROWS:
        second = key.endswith('-2')
        rank = 0 if second else inputs.get('skills',{}).get(key,0)
        mod = mods.get(meta['ability'],0)
        total = mod if second else values.get('skill_totals',{}).get(key,mod)
        data.update({f'skill.{key}.total':total,f'skill.{key}.ability':mod,f'skill.{key}.ranks':rank,f'skill.{key}.misc':total-mod-rank-(3 if rank and key in cls.get('skills',[]) else 0)})
    feats = [entry['name']+(f" ({entry['choice']})" if entry.get('choice') else '') for entry in values.get('feats',[])] + values.get('automatic_feats',[])
    if race.get('traits'): feats.append(race['traits'])
    for i,feat in enumerate(feats[:56]): data[f'feature.{i}'] = feat
    equipment = values.get('equipment',[])
    for i,item in enumerate(equipment[:56]):
        data[f'gear.{i}.name'] = f"{item['name']} × {item['quantity']}"
        data[f'gear.{i}.weight'] = str(item['weight']*item['quantity']*(.5 if small and item['kind'] in {'weapon','armor','shield'} else 1))
    for i,item in enumerate([e for e in equipment if e['kind'] == 'weapon'][:6]):
        data[f'weapon.{i}.name'] = item['name']
        data[f'weapon.{i}.damage'] = item.get('small_damage' if small else 'damage','')
        if item['id'] == inputs.get('weapon'):
            data[f'weapon.{i}.attack'] = values.get('weapon_attack','')
            modifier = values.get('damage_modifier',0)
            data[f'weapon.{i}.damage'] = str(values.get('weapon_damage',''))+(f'{modifier:+d}' if modifier else '')
    for i,item in enumerate([e for e in equipment if e['kind'] in {'armor','shield'}][:6]):
        for part,value in [('name',item['name']),('type',item.get('category',item['kind'])),('bonus',item.get('armor',item.get('shield',''))),('max_dex',item.get('max_dex','')),('penalty',item.get('acp','')),('weight',item['weight']*(.5 if small else 1))]: data[f'armor.{i}.{part}'] = value
    cp = values.get('remaining_cp',0)
    data['money.gp'],cp = divmod(cp,100)
    data['money.sp'],data['money.cp'] = divmod(cp,10)
    for level,key in [(0,'cantrips'),(1,'spells')]:
        data[f'spell.{level}.list'] = '\n'.join(inputs.get(key,[]))
        data[f'spell.{level}.known'] = len(inputs.get(key,[]))
    if values.get('caster'):
        mod = mods.get(values['caster'],0)
        data['caster_level'] = character.level
        data['concentration'] = character.level+mod
        for level in range(10): data[f'spell.{level}.dc'] = 10+level+mod
    return {key:str(value) for key,value in data.items()}


def sheet_values(character, owner, campaign=None, gm=None):
    values = baseline(character,owner,campaign,gm)
    saved = character.play_data or {}
    values.update({key:value for key,value in saved.items() if key in FIELDS})
    # Older sheets grouped the wizard's Dodge bonus into AC Misc. Separate it
    # once without counting the existing bonus twice. New saves carry a version.
    if not saved.get('calculation_version') and 'ac.misc' in saved and 'ac.dodge' not in saved:
        try:
            old_misc, dodge = Decimal(str(values['ac.misc'])), Decimal(str(values['ac.dodge'] or 0))
            if old_misc.is_finite() and dodge.is_finite():
                values['ac.misc'] = str(old_misc-dodge)
        except InvalidOperation:
            pass
    # These fields have a single source of truth in the character record.
    values.update(name=character.name,ancestry=character.ancestry,class_name=character.class_name,level=str(character.level),notes=character.notes,player=owner.name)
    alignment = values['alignment']
    values['alignment'] = next((key for key,label in ALIGNMENTS.items() if alignment.casefold() in {key.casefold(),label.casefold()}),'')
    return recalculate(character, values)


def parse_sheet(form, locked=None):
    locked = locked or {}
    unknown = set(form)-{'csrf','version'}-set(FIELDS)
    missing = {key for key,meta in FIELDS.items() if meta['kind'] != 'checkbox'}-set(form)-set(locked)
    if missing: raise HTTPException(422,'The sheet is incomplete. Reload before saving.')
    if unknown: raise HTTPException(422,'The sheet contains unsupported fields. Reload before saving.')
    values,errors = {},[]
    for key,meta in FIELDS.items():
        if key in locked:
            values[key] = locked[key]
            continue
        entries = form.getlist(key)
        value = form.get(key,'')
        if len(entries) > 1 or not isinstance(value,str):
            errors.append(f'{meta["label"]}: enter one value.')
            continue
        value = value.strip()
        values[key] = value
        if len(value) > meta['maximum']:
            errors.append(f'{meta["label"]}: use {meta["maximum"]} characters or fewer.')
        elif meta['kind'] == 'checkbox' and value not in {'','1'}:
            errors.append(f'{meta["label"]}: invalid checkbox.')
        elif meta['kind'] == 'select' and value and value not in ALIGNMENTS:
            errors.append('Alignment: choose an alignment from the list.')
        elif meta['kind'] == 'number' and value:
            try:
                number = Decimal(value)
                if not number.is_finite() or number.copy_abs() > 1000000000: raise InvalidOperation
                if key == 'level':
                    if number != int(number) or not 1 <= number <= 40: raise InvalidOperation
                    values[key] = str(int(number))
                if (key.endswith('.ranks') or key in {'hp.total','hp.nonlethal','experience','next_level'}) and (number != int(number) or number < 0): raise InvalidOperation
            except (InvalidOperation,ValueError): errors.append(f'{meta["label"]}: enter a valid number'+(' from 1 to 40.' if key == 'level' else '.'))
    for key in ('name','level'):
        if not values.get(key): errors.append(f'{FIELDS[key]["label"]} is required.')
    if len(str(values)) > 150000: errors.append('The sheet is too large. Shorten the notes before saving.')
    return values,errors


def view_context(character, owner, campaign=None, gm=None, values=None, errors=()):
    cls = next((c for c in CLASSES.values() if c['name'].casefold() == character.class_name.casefold()),{})
    values = values if values is not None else sheet_values(character,owner,campaign,gm)
    return dict(deluxe=values,sheet_fields=FIELDS,readonly_fields=calculated_fields(character,values),
                abilities=ABILITIES,alignments=ALIGNMENTS,save_rows=SAVES,skill_rows=SKILL_ROWS,class_skills=cls.get('skills',[]),trained_only=TRAINED_ONLY,
                weapon_columns=WEAPON_COLUMNS,armor_columns=ARMOR_COLUMNS,gear_columns=GEAR_COLUMNS,faction_columns=FACTION_COLUMNS,
                sheet_errors=errors)

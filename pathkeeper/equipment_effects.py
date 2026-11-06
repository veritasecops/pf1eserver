"""Equipment contributions, kept separate from a player's manual modifiers."""
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from .class_catalog import class_key
from .rule_catalog import character_catalog, equipment
from .trait_rules import FAST_MOVEMENT, MONKS, armor_training, load_category, nimble


def number(value, default=Decimal(0)):
    try:
        result = Decimal(str(value)) if str(value).strip() else default
        return result if result is not None and result.is_finite() else default
    except InvalidOperation:
        return default


def active_armor(character, values):
    from .character_weapons import inventory
    slots = {'armor': [], 'shield': []}
    for entry in inventory(character, values, character_catalog(character)):
        row = entry.get('armor_row')
        if row is None or values.get(f'armor.{row}.equipped') != '1':
            continue
        item = entry['item']
        kind = item.get('kind') or ('shield' if values.get(f'armor.{row}.type') == 'shield' else 'armor')
        if kind in slots:
            slots[kind].append((row, item or {'kind':kind,
                kind:number(values.get(f'armor.{row}.bonus', '')),
                'max_dex':number(values.get(f'armor.{row}.max_dex', ''), Decimal(100)),
                'acp':number(values.get(f'armor.{row}.penalty', ''))}))
    return slots


def validate_armor(character, values):
    for kind, entries in active_armor(character, values).items():
        if len(entries) > 1:
            raise HTTPException(422, 'Equip only one suit of armor and one shield at a time.')


def carried_weight(character, values):
    weights = [number(values.get(f'gear.{row}.weight', ''), None) for row in range(56)
               if values.get(f'gear.{row}.name', '').strip()]
    for entry in (character.play_data or {}).get('backpack', []):
        if 'catalog' in entry:
            weight = number(entry['catalog'].get('weight'), None)
            weights.append(None if weight is None else weight * entry['quantity'])
    return None if None in weights else sum(weights, Decimal(0))


def contributions(character, values, original=False):
    from .sheet_calculations import base_speed_race
    catalog = character_catalog(character)
    snapshot = character.sheet_data or {}
    source = snapshot.get('input', {})
    cls = class_key(character, catalog)
    race = base_speed_race(character)
    def modifier(ability):
        if original and snapshot.get('computed'):
            return number(snapshot['computed'].get('modifiers', {}).get(ability, 0))
        key = f'ability.{ability}.temp_mod' if values.get(f'ability.{ability}.temp_score') else f'ability.{ability}.mod'
        return number(values.get(key, ''))
    if original:
        items = equipment(catalog)
        armor, shield = (items.get(source.get(slot), {}) for slot in ('armor', 'shield'))
    else:
        slots = active_armor(character, values)
        # Legacy sheets can contain conflicting markers. Keep them viewable so
        # the player can correct them; new saves enforce one item per slot.
        armor = max((item for _, item in slots['armor']), key=lambda item:item.get('armor', 0), default={})
        shield = max((item for _, item in slots['shield']), key=lambda item:item.get('shield', 0), default={})
    base = race.get('speed', number(values.get('speed.base', '')))
    category = armor.get('category')
    speed = base + (10 if cls == 'barbarian' and category != 'heavy' else 0)
    if category in {'medium', 'heavy'} and race.get('name') != 'Dwarf':
        speed = armor.get('speed_' + str(int(speed))) or {20: 15, 30: 20, 40: 30}.get(speed, speed)
    dex = min(modifier('dex'), number(armor.get('max_dex', 100)), number(shield.get('max_dex', 100)))
    monk = modifier('wis') if cls == 'monk' and not armor and not shield else 0
    penalty = number(armor.get('acp', 0)) + number(shield.get('acp', 0))
    dodge = 0
    if not original:
        level = int(values.get("level") or getattr(character, "level", 1))
        weight = carried_weight(character, values)
        strength = number(values.get('ability.str.temp_score') or values.get('ability.str.score', ''), None)
        size = (values.get('size') or race.get('size', '')).casefold()
        load = load_category(strength, size, weight)
        training = armor_training(cls, level) if armor else 0
        armor_cap = number(armor.get('max_dex', 100))
        dex = min(modifier('dex'), armor_cap + training, number(shield.get('max_dex', 100)))
        penalty = min(0, number(armor.get('acp', 0)) + training) + number(shield.get('acp', 0))
        # Older creation snapshots already include these two Unchained bonuses
        # in their editable starting values. Remove that baked-in component.
        baked_monk = baked_speed = 0
        if snapshot.get('computed'):
            start_armor = equipment(catalog).get(source.get('armor'), {})
            if cls == 'monk-unchained' and not start_armor and not source.get('shield'):
                baked_monk = number(snapshot['computed'].get('modifiers', {}).get('wis', 0))
            if cls == 'barbarian-unchained' and start_armor.get('category') != 'heavy':
                baked_speed = 10
                if start_armor.get('category') == 'medium' and race.get('name') != 'Dwarf':
                    speeds = {20: 15, 30: 20, 40: 30}
                    baked_speed = (
                        (start_armor.get(f'speed_{base + 10}') or speeds.get(base + 10, base + 10))
                        - (start_armor.get(f'speed_{base}') or speeds.get(base, base))
                    )
        speed = base + (10 if cls in FAST_MOVEMENT and category != 'heavy' and load != 'heavy' else 0)
        if cls in MONKS and not armor and not shield and load not in {'medium', 'heavy'}:
            speed += 10 * min(6, level // 3)
            monk = max(0, modifier('wis')) + level // 4
        elif cls == 'shifter' and level >= 2 and not armor and not shield and load not in {'medium', 'heavy'}:
            monk = max(0, modifier('wis')) + level // 4
        else:
            monk = 0
        monk -= baked_monk
        armor_slows = category in {'medium', 'heavy'} and not (
            cls == 'fighter' and level >= (3 if category == 'medium' else 7)
        )
        if armor_slows and race.get('name') != 'Dwarf':
            speed = armor.get('speed_' + str(int(speed))) or max(10 if speed >= 10 else 5, 5 * ((2 * int(speed) + 14) // 15))
        speed -= baked_speed
        dodge = nimble(cls, level, category, load)
    result = {'ac.armor':armor.get('armor', 0), 'ac.shield':shield.get('shield', 0),
              'ac.dex':dex, 'ac.misc':monk, 'cmd.misc':monk + dodge, 'ac.dodge':dodge, 'speed.armor':speed}
    for key, meta in catalog['skills'].items():
        if meta.get('armor'):
            for row in (key, key+'-2') if key in {'craft','perform','profession'} else (key,):
                result[f'skill.{row}.misc'] = penalty
    if original and not snapshot.get('computed'):
        # Preserve existing hand-entered modifiers on legacy characters. Blank
        # DEX and speed fields can start following their known base values.
        for key in ('ac.dex', 'speed.armor'):
            if values.get(key, '') == '': result[key] = 0
        result['ac.misc'] = result['cmd.misc'] = 0
    return {key:format(number(value), 'f') for key, value in result.items()}


def apply_effects(character, values, previous=None, keep=()):
    previous = previous if previous is not None else (character.play_data or {}).get('equipment_effects')
    if previous is None:
        previous = contributions(character, values, original=True)
    current = contributions(character, values)
    for key, amount in current.items():
        delta = number(amount) - number(previous.get(key, 0))
        if delta and key not in keep:
            updated = number(values.get(key, '')) + delta
            if abs(updated) > 1000000000:
                raise HTTPException(422, 'An equipment adjustment exceeds the supported field range.')
            values[key] = format(updated, 'f')
    return current


def persist_effects(character, values):
    current = contributions(character, values)
    return {'equipment_effects':current, 'speed.base':values.get('speed.base',''), **{key:values[key] for key in current}}

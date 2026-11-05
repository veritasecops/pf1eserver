"""Atomic removal and sale of complete weapon and armor inventory entries."""
from decimal import Decimal
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .character_weapons import character_values, inventory, purchase_response
from .database import commit, get_db
from .rule_catalog import character_catalog, equipment, load_catalog
from .security import audit, context, digest, get_character, integer, read_form
from .treasure import COINS, treasure

router = APIRouter()


@router.post('/characters/{character_id}/equipment/dispose')
async def dispose_equipment(character_id: int, request: Request, db: Session = Depends(get_db)):
    from .workspace import verify_version
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    form = await read_form(ctx)
    db.refresh(character, with_for_update=True)
    character = get_character(ctx, character_id)
    request_id = str(form.get('request_id', ''))
    if not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise HTTPException(422, 'Enter a valid inventory operation identifier.')
    fingerprint = digest(json.dumps(sorted((key, value) for key, value in form.multi_items() if key != 'csrf')))
    previous = (character.play_data or {}).get('equipment_disposal', {})
    if previous.get('id') == request_id and previous.get('actor') == ctx.user.id:
        if previous.get('fingerprint') != fingerprint or previous.get('version') != character.version:
            raise HTTPException(409, 'The character changed after this inventory operation. Reload the sheet.')
        return purchase_response(ctx, character, previous.get('changed_fields', []))
    verify_version(form, character)
    kind, action = str(form.get('kind', '')), str(form.get('action', ''))
    if kind not in {'weapon', 'armor'} or action not in {'remove', 'sell'}:
        raise HTTPException(422, 'Choose a weapon or armor entry to remove or sell.')
    row = integer(form, 'row', 0, 5)
    values = character_values(ctx, character)
    entries = inventory(character, values, load_catalog(db))
    row_key = 'row' if kind == 'weapon' else 'armor_row'
    matches = [entry for entry in entries if entry.get(row_key) == row]
    if len(matches) != 1 or not values.get(f'{kind}.{row}.name', '').strip():
        raise HTTPException(409, 'This inventory entry changed or was already removed. Reload the sheet.')
    entry = matches[0]
    try: coins = json.loads(str(form.get('coins', '{}')))
    except (TypeError, ValueError): raise HTTPException(422, 'Enter sale proceeds by coin type.') from None
    if not isinstance(coins, dict) or set(coins) - set(COINS):
        raise HTTPException(422, 'Use PP, GP, SP, and CP for sale proceeds.')
    if any(type(amount) is not int or not 0 <= amount <= 1000000000 for amount in coins.values()):
        raise HTTPException(422, 'Sale proceeds must be nonnegative whole coin amounts.')
    if action == 'remove' and any(coins.values()):
        raise HTTPException(422, 'Use Sell to receive coins for this item.')
    if action == 'sell' and not any(coins.values()):
        raise HTTPException(422, 'Enter the sale proceeds, or use Remove without payment.')
    changes = {field:'' for field in values if field.startswith(f'{kind}.{row}.')}
    gear = entry.get('gear_row')
    if gear is not None and values.get(f'gear.{gear}.name') == entry.get('gear_label'):
        changes.update({field:'' for field in values if field.startswith(f'gear.{gear}.')})
    treasure(values)
    for coin, amount in coins.items():
        changes['money.' + coin] = format(Decimal(str(values.get('money.' + coin, '') or '0')) + amount, 'f')
    treasure({**values, **changes})
    entries.remove(entry)
    from .equipment_effects import contributions, persist_effects
    from .sheet_calculations import recalculate
    before = contributions(character, values)
    character.play_data = {**(character.play_data or {}), 'weapon_inventory':entries}
    updated = recalculate(character, {**values, **changes}, equipment_previous=before)
    changes.update({key:updated[key] for key in contributions(character, updated)})
    character.play_data = {**(character.play_data or {}), **changes, **persist_effects(character, updated), 'weapon_inventory':entries,
        'equipment_disposal':{'id':request_id, 'actor':ctx.user.id, 'fingerprint':fingerprint,
                             'version':character.version + 1, 'changed_fields':list(changes)}}
    audit(db, ctx.user, 'character.equipment_' + ('sold' if action == 'sell' else 'removed'),
          f"{action.capitalize()} {entry['quantity']} inventory units on {character.name}; proceeds {sum(coins.get(c, 0)*v for c, v in COINS.items())} copper pieces.")
    commit(db)
    return purchase_response(ctx, character, changes)

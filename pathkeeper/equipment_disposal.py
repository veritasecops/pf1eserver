"""Atomic removal and sale of complete equipment and backpack entries."""
from decimal import Decimal
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .backpack import ITEM_ID
from .character_weapons import character_values, inventory, purchase_response
from .database import commit, get_db
from .rule_catalog import character_catalog, equipment, load_catalog
from .security import audit, context, digest, get_character, integer, read_form
from .treasure import COINS, treasure, record_coin_change

router = APIRouter()


def sale_changes(form, action, values):
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
    if not any(coins.values()):
        return {}, 0
    treasure(values)
    changes = {'money.' + coin: format(Decimal(str(values.get('money.' + coin, '') or '0')) + amount, 'f')
               for coin, amount in coins.items()}
    treasure({**values, **changes})
    return changes, sum(amount * COINS[coin] for coin, amount in coins.items())


@router.post('/characters/{character_id}/equipment/dispose')
async def dispose_equipment(character_id: int, request: Request, db: Session = Depends(get_db)):
    from .workspace import verify_version
    from .equipment_effects import contributions, persist_effects
    from .sheet_calculations import recalculate
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
    if kind not in {'weapon', 'armor', 'backpack'} or action not in {'remove', 'sell'}:
        raise HTTPException(422, 'Choose an inventory entry to remove or sell.')
    values = character_values(ctx, character)
    coin_changes, proceeds = sale_changes(form, action, values)
    operation = {'id':request_id, 'actor':ctx.user.id, 'fingerprint':fingerprint,
                 'version':character.version + 1}
    if kind == 'backpack':
        item_id = str(form.get('row', ''))
        if not ITEM_ID.fullmatch(item_id):
            raise HTTPException(422, 'Choose a valid backpack entry.')
        data = character.play_data or {}
        items = data.get('backpack', [])
        entry = next((item for item in items if item['id'] == item_id), None)
        if entry is None:
            raise HTTPException(409, 'This backpack entry was already removed. Reload the sheet.')
        before = contributions(character, values)
        character.play_data = {**data, **coin_changes, 'backpack': [item for item in items if item['id'] != item_id],
                               'equipment_disposal': operation}
        updated = recalculate(character, {**values, **coin_changes}, equipment_previous=before)
        character.play_data = {**character.play_data, **persist_effects(character, updated)}
        if action == 'sell':
            record_coin_change(db, character, ctx.user, 'backpack_sale', values, updated)
        audit(db, ctx.user, 'character.backpack_' + ('sold' if action == 'sell' else 'removed'),
              f"{action.capitalize()} {entry['quantity']} × {entry['name']} on {character.name}; proceeds {proceeds} copper pieces.")
        commit(db)
        return purchase_response(ctx, character)
    row = integer(form, 'row', 0, 5)
    entries = inventory(character, values, load_catalog(db))
    row_key = 'row' if kind == 'weapon' else 'armor_row'
    matches = [entry for entry in entries if entry.get(row_key) == row]
    if len(matches) != 1 or not values.get(f'{kind}.{row}.name', '').strip():
        raise HTTPException(409, 'This inventory entry changed or was already removed. Reload the sheet.')
    entry = matches[0]
    changes = {field:'' for field in values if field.startswith(f'{kind}.{row}.')}
    gear = entry.get('gear_row')
    if gear is not None and values.get(f'gear.{gear}.name') == entry.get('gear_label'):
        changes.update({field:'' for field in values if field.startswith(f'gear.{gear}.')})
    changes.update(coin_changes)
    entries.remove(entry)
    before = contributions(character, values)
    character.play_data = {**(character.play_data or {}), 'weapon_inventory':entries}
    updated = recalculate(character, {**values, **changes}, equipment_previous=before)
    changes.update({key:updated[key] for key in contributions(character, updated)})
    character.play_data = {**(character.play_data or {}), **changes, **persist_effects(character, updated), 'weapon_inventory':entries,
        'equipment_disposal':{**operation, 'changed_fields':list(changes)}}
    if action == 'sell':
        record_coin_change(db, character, ctx.user, 'equipment_sale', values, updated)
    audit(db, ctx.user, 'character.equipment_' + ('sold' if action == 'sell' else 'removed'),
          f"{action.capitalize()} {entry['quantity']} inventory units on {character.name}; proceeds {proceeds} copper pieces.")
    commit(db)
    return purchase_response(ctx, character, changes)

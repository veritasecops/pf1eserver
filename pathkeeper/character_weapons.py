"""Character purchases and their saved inventory; coin amounts use copper pieces."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from math import floor
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import commit, get_db
from .models import Campaign, Character, RuleCatalog, User
from .rule_catalog import character_catalog, effect_total, load_catalog, equipment
from .armor import armor_fields, purchasable
from .equipment_index import sheet_gear
from .security import audit, context, digest, get_character, integer, read_form

router = APIRouter()
PARTS = ('name','quantity','attack','critical','type','range','ammunition','damage')
from .treasure import COINS, treasure, deduct_coins


def character_values(ctx, character):
    from .deluxe_sheet import sheet_values
    owner=ctx.db.get(User,character.owner_id)
    campaign=ctx.db.get(Campaign,character.campaign_id) if character.campaign_id else None
    gm=ctx.db.get(User,campaign.owner_id) if campaign else None
    return sheet_values(character,owner,campaign,gm)


def inventory(character, values, catalog):
    saved=(character.play_data or {}).get('weapon_inventory')
    entries=deepcopy(saved) if saved is not None else []
    names={}
    for key,item in catalog['weapons'].items():
        if item.get('kind')!='weapon': continue
        for name in [item['name'],*item.get('aliases',[])]: names.setdefault(name.casefold(),key)
    snapshot=character.sheet_data or {}
    sources={item['id']:item for item in snapshot.get('computed',{}).get('equipment',[])}
    for key,item in (snapshot.get('catalog') or {}).get('weapons',{}).items():
        if key in catalog['weapons']: names.setdefault(item['name'].casefold(),key)
    for key,item in sources.items():
        if key in catalog['weapons'] and item.get('kind')=='weapon': names.setdefault(item['name'].casefold(),key)
    for row in range(0 if saved is not None else 6):
        name=values.get(f'weapon.{row}.name','').strip()
        if not name: continue
        key=names.get(name.casefold())
        item={**catalog['weapons'].get(key,{}),**sources.get(key,{})}
        quantity=sources.get(key,{}).get('quantity',1)
        agreed=snapshot.get('input',{}).get('equipment_prices',{}).get(key)
        entries.append({'id':key,'row':row,'quantity':quantity,'item':item,'agreed_unit_price':agreed,
                        'fields':{part:values.get(f'weapon.{row}.{part}','') for part in PARTS if part!='quantity'}})
    # Ammunition recorded by the wizard is carried in the gear table.
    for key,item in sources.items():
        if (item.get('category') in {'ammunition','extra'}) and not any(entry.get('id')==key for entry in entries):
            entries.append({'id':key,'row':None,'quantity':item['quantity'],'item':deepcopy(item),'agreed_unit_price':snapshot.get('input',{}).get('equipment_prices',{}).get(key)})
    armors=catalog.get('armor',{})
    armor_names={name.casefold():key for key,item in armors.items() for name in [item['name'],*item.get('aliases',[])]}
    for key,item in sources.items():
        if key in armors: armor_names.setdefault(item['name'].casefold(),key)
    for row in range(6):
        if any(entry.get('armor_row')==row for entry in entries): continue
        name=values.get(f'armor.{row}.name','').strip()
        if not name: continue
        key=armor_names.get(name.casefold())
        item={**armors.get(key,{}),**sources.get(key,{})}
        quantity=sources.get(key,{}).get('quantity',1)
        entries.append({'id':key,'row':None,'armor_row':row,'quantity':quantity,'item':item,
                        'armor_fields':{part:values.get(f'armor.{row}.{part}','') for part in ('name','type','bonus','max_dex','penalty','failure','weight')},
                        'agreed_unit_price':snapshot.get('input',{}).get('equipment_prices',{}).get(key)})
    for entry in entries:
        item=entry['item']
        expected=f"{item.get('name','')} × {entry['quantity']}"
        for row in range(56):
            if values.get(f'gear.{row}.name')==expected:
                entry.update(gear_row=row,gear_label=expected,gear_quantity=entry['quantity'])
                break
    return entries


def apply_inventory(character, values):
    """Refresh managed weapon statistics while preserving editable row notes."""
    from .sheet_calculations import SIZE_MODIFIERS
    from .class_catalog import class_key
    from .trait_rules import fighter_weapon_bonus, trained_weapon_groups
    catalog=character_catalog(character)
    snapshot=character.sheet_data or {}
    class_id = class_key(character, catalog)
    level = int(values.get('level') or getattr(character, 'level', 1))
    trained = trained_weapon_groups(character) if class_id == 'fighter' else {}
    feats=snapshot.get('computed',{}).get('feats',[])+[{'name':name} for name in snapshot.get('computed',{}).get('automatic_feats',[])]
    def number(key):
        try:
            value=Decimal(str(values.get(key,'')))
            return value if value.is_finite() else None
        except InvalidOperation: return None
    def ability(key):
        return number(f'ability.{key}.temp_mod' if values.get(f'ability.{key}.temp_score','')!='' else f'ability.{key}.mod')
    for entry in inventory(character, values, catalog):
        if entry.get('armor_row') is not None:
            prefix=f"armor.{entry['armor_row']}."
            fields=entry.get('armor_fields') or armor_fields(entry['item'],entry['quantity'],values.get('size',''))
            for part,value in fields.items(): values[prefix+part]=value
            values[prefix+'quantity']=str(entry['quantity'])
            continue
        row=entry.get('row')
        if row is None: continue
        prefix=f'weapon.{row}.'
        if 'fields' in entry and not (values.get(prefix+'equipped')=='1' and entry['item'].get('damage')):
            for part,value in entry['fields'].items(): values[prefix+part]=value
        else:
            item=entry['item']
            for part,key in [('name','name'),('critical','critical'),('type','damage_type'),('range','range')]: values[prefix+part]=str(item.get(key,''))
            values[prefix+'ammunition']=''
            strength,dex,bab=ability('str'),ability('dex'),number('bab')
            finesse=any(catalog['feats'].get(feat.get('name'),{}).get('finesse') for feat in feats)
            swashbuckler_weapon = (class_id == 'swashbuckler' and not item.get('ranged')
                                   and item.get('category') in {'light', 'one-handed'}
                                   and item.get('damage_type', '').upper() == 'P')
            attack_ability=dex if item.get('ranged') or item.get('finesse') and finesse or swashbuckler_weapon else strength
            class_bonus = fighter_weapon_bonus(trained, item, level)
            if swashbuckler_weapon:
                class_bonus += (level - 1) // 4
            size=SIZE_MODIFIERS.get(str(values.get('size','')).casefold(),0)
            rating=item.get('strength_rating')
            penalty=-2 if item.get('bow') and rating is not None and strength is not None and strength<rating else 0
            values[prefix+'attack']='' if bab is None or attack_ability is None else str(int(bab+attack_ability+size+effect_total(feats,catalog,'selected_weapon',entry['id'])+class_bonus+penalty))
            damage=str(item.get('small_damage' if str(values.get('size','')).casefold()=='small' else 'damage',''))
            modifier=Decimal(0) if item.get('ranged') and not item.get('add_strength') else strength
            if item.get('bow') and strength is not None: modifier=min(strength,rating if rating is not None else 0)
            if modifier is not None and modifier>0 and item.get('two_handed') and not item.get('ranged'): modifier=Decimal(floor(modifier*Decimal('1.5')))
            if modifier is not None: modifier += class_bonus
            if damage.casefold() not in {'—','see text',''} and modifier:
                # Each end is displayed separately; off-hand combat still needs adjudication.
                damage='/'.join(part+f'{int(modifier):+d}' for part in damage.split('/'))
            values[prefix+'damage']=damage
        values[prefix+'quantity']=str(entry['quantity'])
    return values


def shop_state(ctx,character):
    values=character_values(ctx,character)
    catalog=load_catalog(ctx.db)
    entries=inventory(character,values,catalog)
    record=ctx.db.get(RuleCatalog,1)
    owned,prices={},{}
    for entry in entries:
        key=entry.get('id')
        if key:
            owned[key]=owned.get(key,0)+entry['quantity']
            if entry.get('agreed_unit_price') is not None: prices[key]=entry['agreed_unit_price']
    return {'version':character.version,'catalog_version':record.version if record else 0,
            'equipment':{**catalog['weapons'],**catalog.get('armor',{}),**sheet_gear(catalog)},'owned':owned,'prices':prices,'budget':treasure(values),
            'maxNewArmor':6-sum(bool(values.get(f'armor.{row}.name','').strip()) for row in range(6)),
            'maxNewWeapons':6-sum(bool(values.get(f'weapon.{row}.name','').strip()) for row in range(6))}


@router.get('/characters/{character_id}/equipment')
@router.get('/characters/{character_id}/weapons')
async def weapon_shop(character_id: int,request: Request,db: Session=Depends(get_db)):
    ctx=context(request,db)
    return shop_state(ctx,get_character(ctx,character_id))


@router.post('/characters/{character_id}/equipment')
@router.post('/characters/{character_id}/weapons')
async def purchase_weapons(character_id: int,request: Request,db: Session=Depends(get_db)):
    from .character_rules import bounded_int
    from .workspace import autosave_response, verify_version
    ctx=context(request,db)
    character=get_character(ctx,character_id)
    form=await read_form(ctx)
    db.refresh(character,with_for_update=True)
    character=get_character(ctx,character_id)
    request_id=str(form.get('request_id',''))
    if not re.fullmatch(r'[a-f0-9]{32}',request_id): raise HTTPException(422,'Enter a valid purchase identifier.')
    fingerprint=digest(json.dumps(sorted((key,value) for key,value in form.multi_items() if key!='csrf')))
    previous=(character.play_data or {}).get('weapon_purchase',{})
    if previous.get('id')==request_id and previous.get('actor')==ctx.user.id:
        if previous.get('fingerprint')!=fingerprint or previous.get('version')!=character.version: raise HTTPException(409,'The character changed after this purchase. Reload before buying again.')
        return purchase_response(ctx,character)
    verify_version(form,character)
    record=db.scalar(select(RuleCatalog).where(RuleCatalog.id==1).with_for_update())
    if integer(form,'catalog_version',0,2**31-1)!=(record.version if record else 0): raise HTTPException(409,'Equipment prices or rules changed. Reload the picker before buying.')
    try: cart=json.loads(str(form.get('payload','')))
    except (ValueError,TypeError): raise HTTPException(422,'The equipment selection could not be read.') from None
    if not isinstance(cart,dict) or set(cart)-{'quantities','prices'}: raise HTTPException(422,'Choose equipment quantities and optional agreed prices.')
    quantities,prices=cart.get('quantities'),cart.get('prices',{})
    if not isinstance(quantities,dict) or not quantities or not isinstance(prices,dict) or set(prices)-set(quantities): raise HTTPException(422,'Select at least one equipment entry.')
    prices={key:bounded_int(price,0,100000000,'Agreed equipment price') for key,price in prices.items()}
    catalog=load_catalog(db)
    values=character_values(ctx,character)
    entries=inventory(character,values,catalog)
    changes={}
    cost=0
    gear = sheet_gear(catalog)
    existing_equipment = equipment(catalog)
    for key,quantity in quantities.items():
        item = gear.get(key) or existing_equipment.get(key)
        if not item or not item.get('enabled',True) or (key not in gear and not purchasable(item)):
            raise HTTPException(422, 'Choose available equipment from the catalog.')
        quantity=bounded_int(quantity,1,100,'Equipment quantity')
        bounded_int(sum(entry['quantity'] for entry in entries if entry.get('id')==key)+quantity,1,100,'Total inventory quantity')
        entry=next((entry for entry in entries if entry.get('id')==key),None)
        if item['cost'] is None:
            prior=entry.get('agreed_unit_price') if entry else None
            if prior is not None:
                if key in prices and prices[key]!=prior: raise HTTPException(422,'Use the existing agreed unit price for this item.')
                price=prior
            elif key not in prices: raise HTTPException(422,f"Enter the agreed unit price for {item['name']}.")
            else: price=prices[key]
        elif key in prices: raise HTTPException(422,'Published equipment prices are calculated by the server.')
        else: price=item['cost']
        cost+=quantity*price
        if entry:
            entry['quantity']=bounded_int(entry['quantity']+quantity,1,100,'Total inventory quantity')
            if item['cost'] is None: entry['agreed_unit_price']=price
        else:
            row=None
            if item['kind']=='weapon':
                used={entry['row'] for entry in entries if entry.get('row') is not None}
                row=next((index for index in range(6) if index not in used),None)
                if row is None: raise HTTPException(422,'The six weapon rows are full. Choose an existing weapon or ammunition.')
            entry={'id':key,'row':row,'quantity':quantity,'item':{**deepcopy(item),'cost':price},'agreed_unit_price':price if item['cost'] is None else None}
            if item['kind'] in {'armor','shield'}:
                used={entry['armor_row'] for entry in entries if entry.get('armor_row') is not None}
                armor_row=next((index for index in range(6) if index not in used),None)
                if armor_row is None: raise HTTPException(422,'The six armor rows are full. Choose an existing armor item.')
                entry['armor_row']=armor_row
                changes[f'armor.{armor_row}.notes']=values.get(f'armor.{armor_row}.notes','') or item.get('notes','')
            entries.append(entry)
            if row is not None: changes[f'weapon.{row}.notes']=values.get(f'weapon.{row}.notes','') or '\n'.join(text for text in (item.get('special',''),item.get('notes','')) if text and text!='—')
        gear_row=entry.get('gear_row')
        if gear_row is not None and values.get(f'gear.{gear_row}.name')==entry.get('gear_label'):
            gear_quantity=entry.get('gear_quantity',0)+quantity
        else:
            gear_row=next((index for index in range(56) if not values.get(f'gear.{index}.name','').strip()),None)
            if gear_row is None: raise HTTPException(422,'The gear table is full. Clear a gear row before purchasing.')
            gear_quantity=quantity
        label=f"{entry['item']['name']} × {gear_quantity}"
        entry.update(gear_row=gear_row,gear_quantity=gear_quantity,gear_label=label)
        changes[f'gear.{gear_row}.name']=label
        weight=entry['item'].get('weight')
        changes[f'gear.{gear_row}.weight']=str(weight*gear_quantity*(.5 if str(values.get('size','')).casefold()=='small' and item['kind'] in {'weapon','armor','shield'} else 1)) if weight is not None else values.get(f'gear.{gear_row}.weight','') or item.get('weight_text','Special')
        values.update(changes)
    changes.update(deduct_coins(values,cost))
    from .equipment_effects import persist_effects
    character.play_data={**(character.play_data or {}),**persist_effects(character,values),**changes,'weapon_inventory':entries,
                         'weapon_purchase':{'id':request_id,'actor':ctx.user.id,'fingerprint':fingerprint,'version':character.version+1}}
    audit(db,ctx.user,'character.weapons_purchased',f'Purchased {sum(quantities.values())} equipment units for {cost} copper pieces on {character.name}.')
    commit(db)
    return purchase_response(ctx,character)


def purchase_response(ctx,character,changed_fields=()):
    from .workspace import autosave_response
    response=autosave_response(ctx,character)
    body=json.loads(response.body)
    values=character_values(ctx,character)
    body['purchase_fields']={key:value for key,value in values.items() if key.startswith(('weapon.','armor.','gear.')) or key in {'money.pp','money.gp','money.sp','money.cp'} or key in changed_fields}
    from fastapi.responses import JSONResponse
    return JSONResponse(body,headers={'Cache-Control':'no-store'})

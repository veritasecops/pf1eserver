from copy import deepcopy
import json
import secrets

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper.character_weapons import deduct_coins, treasure
from pathkeeper.database import engine
from pathkeeper.models import AuditEvent, Character, CoinTransaction, RuleCatalog
from pathkeeper.rule_catalog import default_catalog
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_campaign, seed_character


def setup_sheet(env):
    character=seed_character(env.player)
    client=env.login(env.player)
    path=f'/characters/{character.id}'
    form=SheetForm(client.get(path).text)
    form.values.update({'bab':'5','ability.str.score':'16','ability.dex.score':'14','size':'Medium','weapon.0.notes':'Keep my personal note'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    assert env.post(client, path + '/treasure', {
        'version': SheetForm(client.get(path).text).values['version'], 'request_id': secrets.token_hex(16),
        'action': 'add', 'coin': 'gp', 'amount': 100,
    }).status_code == 200
    return client,character.id


def purchase_data(client,character_id,quantities,prices=None,**changes):
    state=client.get(f'/characters/{character_id}/weapons').json()
    return {'version':state['version'],'catalog_version':state['catalog_version'],
            'request_id':secrets.token_hex(16),'payload':json.dumps({'quantities':quantities,'prices':prices or {}}),**changes}


def test_purchases_populate_locked_fields_notes_and_inventory_and_deduct_once(env):
    client,character_id=setup_sheet(env)
    path=f'/characters/{character_id}'
    payload=purchase_data(client,character_id,{'longsword':2,'dagger':3})
    response=env.post(client,path+'/weapons',payload)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['purchase_fields']['money.gp']=='64'
    assert result['values']['weapon.0.name']=='Longsword'
    assert result['values']['weapon.0.quantity']=='2'
    assert result['values']['weapon.0.attack']=='8'
    assert result['values']['weapon.0.damage']=='1d8+3'
    assert result['values']['weapon.0.critical']=='19-20/x2'
    assert result['purchase_fields']['weapon.0.notes']=='Keep my personal note'
    assert 'Longsword × 2' in result['purchase_fields'].values()
    retry=env.post(client,path+'/weapons',payload)
    assert retry.status_code==200 and retry.json()['version']==result['version']
    with Session(engine()) as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.event=='character.weapons_purchased'))
        assert db.get(Character,character_id).play_data['weapon_inventory'][0]['quantity']==2
        rows = db.scalars(select(CoinTransaction).where(CoinTransaction.character_id == character_id)
                          .order_by(CoinTransaction.id)).all()
        assert [(row.source, row.net_cp) for row in rows] == [('chest_add', 10000), ('equipment_purchase', -3600)]
    form=SheetForm(client.get(path).text)
    assert {'weapon.0.name','weapon.0.quantity','weapon.0.attack','weapon.0.damage','weapon.0.ammunition'} <= form.readonly
    assert 'weapon.0.notes' not in form.readonly
    form.values.update({'weapon.0.name':'Forged weapon','weapon.0.quantity':'99','weapon.0.attack':'999',
                        'weapon.0.damage':'99d20','weapon.0.notes':'Updated note','ability.str.score':'18'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    saved=SheetForm(client.get(path).text)
    assert saved.values['weapon.0.name']=='Longsword' and saved.values['weapon.0.quantity']=='2'
    assert saved.values['weapon.0.attack']=='9' and saved.values['weapon.0.damage']=='1d8+4'
    assert saved.values['weapon.0.notes']=='Updated note' and saved.values['money.gp']=='64'
    # Intervening sheet edits make an old purchase retry stale rather than buying twice.
    assert env.post(client,path+'/weapons',payload).status_code==409


def test_existing_legacy_weapon_and_notes_are_preserved_when_buying_more(env):
    client,character_id=setup_sheet(env)
    with Session(engine()) as db:
        character=db.get(Character,character_id)
        character.play_data={**character.play_data,'weapon.0.name':'Longsword','weapon.0.attack':'12','weapon.0.damage':'1d8+7','weapon.0.notes':'Legacy note'}
        db.commit()
    path=f'/characters/{character_id}'
    result=env.post(client,path+'/weapons',purchase_data(client,character_id,{'longsword':2})).json()
    assert result['values']['weapon.0.quantity']=='3'
    assert result['values']['weapon.0.attack']=='12'
    assert result['purchase_fields']['weapon.0.notes']=='Legacy note'
    assert result['purchase_fields']['money.gp']=='70'


@pytest.mark.parametrize('quantities,prices',[
    ({'longbow':2},{}), ({'dagger':-1},{}), ({'dagger':True},{}), ({'dagger':101},{}),
    ({'dagger':1.5},{}), ({'backpack':1},{}), ({'missing':1},{}),
    ({'longsword':1},{'longsword':1}), ({'shield-light':1},{}),
    ({'shield-light':1},{'shield-light':True}),
    ({'dagger':1,'quarterstaff':1,'club':1,'longspear':1,'sickle':1,'shortspear':1,'javelin':1},{}),
])
def test_failed_purchases_never_change_inventory_or_treasure(env,quantities,prices):
    client,character_id=setup_sheet(env)
    path=f'/characters/{character_id}'
    with Session(engine()) as db:
        before=deepcopy(db.get(Character,character_id).play_data)
        version=db.get(Character,character_id).version
    response=env.post(client,path+'/weapons',purchase_data(client,character_id,quantities,prices))
    assert response.status_code==422,response.text
    with Session(engine()) as db:
        character=db.get(Character,character_id)
        assert character.play_data==before and character.version==version


def test_special_prices_ammunition_and_free_weapons(env):
    client,character_id=setup_sheet(env)
    path=f'/characters/{character_id}'
    response=env.post(client,path+'/weapons',purchase_data(client,character_id,{'shield-light':1,'arrows':2,'quarterstaff':1},{'shield-light':925}))
    assert response.status_code==200,response.text
    fields=response.json()['purchase_fields']
    assert treasure(fields)==8875
    arrows = next(item for item in response.json()['backpack'] if item['catalog_id'] == 'arrows')
    assert arrows['name'] == 'Arrows, common (20)' and arrows['quantity'] == 2
    assert 'Arrows, common (20) × 2' in fields.values()
    again=env.post(client,path+'/weapons',purchase_data(client,character_id,{'shield-light':1}))
    assert again.status_code==200 and treasure(again.json()['purchase_fields'])==7950


def test_access_csrf_catalog_and_character_version_are_checked(env):
    client,character_id=setup_sheet(env)
    path=f'/characters/{character_id}/weapons'
    payload=purchase_data(client,character_id,{'dagger':1})
    other=env.login(env.player2)
    assert other.get(path).status_code==404
    assert env.post(other,path,payload).status_code==404
    assert client.post(path,data=payload).status_code==403
    assert env.post(client,path,{**payload,'version':1}).status_code==409
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1,data=default_catalog()))
        db.commit()
    assert env.post(client,path,payload).status_code==409


def test_gear_capacity_is_checked_before_spending(env):
    client,character_id=setup_sheet(env)
    with Session(engine()) as db:
        character=db.get(Character,character_id)
        character.play_data={**character.play_data,**{f'gear.{row}.name':f'Existing gear {row}' for row in range(256)}}
        db.commit()
    response=env.post(client,f'/characters/{character_id}/weapons',purchase_data(client,character_id,{'dagger':1}))
    assert response.status_code==422
    assert client.get(f'/characters/{character_id}/weapons').json()['budget']==10000


def test_coin_change_preserves_denominations_and_excludes_stored_treasure():
    values={'money.pp':'10','money.gp':'0','money.sp':'0','money.cp':'0','money.stored':'5000'}
    assert deduct_coins(values,1500)=={'money.pp':'8','money.gp':'5','money.sp':'0','money.cp':'0'}
    values={'money.gp':'100','money.sp':'2','money.cp':'3'}
    assert deduct_coins(values,155)=={'money.pp':'0','money.gp':'98','money.sp':'6','money.cp':'8'}
    assert treasure({'money.gp':'10.5'})==1050


def test_a_new_special_price_requires_agreement_after_a_published_price_changes(env):
    client,character_id=setup_sheet(env)
    path=f'/characters/{character_id}/weapons'
    assert env.post(client,path,purchase_data(client,character_id,{'longsword':1})).status_code==200
    with Session(engine()) as db:
        catalog=default_catalog()
        catalog['weapons']['longsword'].update(cost=None,cost_text='special')
        db.add(RuleCatalog(id=1,data=catalog))
        db.commit()
    assert 'longsword' not in client.get(path).json()['prices']
    assert env.post(client,path,purchase_data(client,character_id,{'longsword':1})).status_code==422
    bought=env.post(client,path,purchase_data(client,character_id,{'longsword':1},{'longsword':2000}))
    assert bought.status_code==200 and treasure(bought.json()['purchase_fields'])==6500
    assert client.get(path).json()['prices']['longsword']==2000


def test_special_materials_and_miscellaneous_share_the_equipment_cart(env):
    client, character_id = setup_sheet(env)
    path = f'/characters/{character_id}/equipment'
    state = client.get(path).json()
    catalog = state['equipment']
    categories = state['equipment_categories']
    assert 'Martial' in categories['Weapons'] and 'Heavy' in categories['Armor']
    assert 'Martial' in catalog['longsword']['categories']
    assert 'Light' in catalog['leather']['categories']
    material = 'special-materials-adamantine'
    abacus = 'miscellaneous-abacus'
    assert sum(item['kind'] == 'material' for item in catalog.values()) >= 48
    assert len({category for item in catalog.values() if item['kind'] == 'misc' for category in item['categories']}) == 27
    assert catalog[material]['cost'] is None and '+3,000 gp' in catalog[material]['cost_text']
    assert catalog[abacus]['cost'] == 200 and catalog[abacus]['weight'] == 2
    assert catalog['miscellaneous-airship']['cost'] == 5000000
    assert catalog['miscellaneous-fungal-eyes']['cost'] == 1800000
    cart = {material: 1, abacus: 2, 'dagger': 1}
    assert env.post(client, path, purchase_data(client, character_id, cart)).status_code == 422
    payload = purchase_data(client, character_id, cart, {material: 700})
    response = env.post(client, path, payload)
    assert response.status_code == 200, response.text
    fields = response.json()['purchase_fields']
    assert treasure(fields) == 8700
    items = {item['catalog_id']: item for item in response.json()['backpack']}
    assert items[abacus]['quantity'] == 2 and items[abacus]['unit_cp'] == 200
    assert items[abacus]['catalog']['weight'] == 2
    assert items[abacus]['catalog']['url'] == catalog[abacus]['url']
    assert items[material]['catalog']['cost_text'] == catalog[material]['cost_text']
    assert 'Adamantine × 1' in fields.values() and 'Abacus × 2' in fields.values()
    assert response.json()['values']['weapon.0.name'] == 'Dagger'
    assert env.post(client, path, payload).json()['purchase_fields'] == fields
    state = client.get(path).json()
    assert state['owned'][material] == 1 and state['prices'][material] == 700
    second = env.post(client, path, purchase_data(client, character_id, {abacus: 1}))
    stack = next(item for item in second.json()['backpack'] if item['catalog_id'] == abacus)
    assert stack['id'] == items[abacus]['id'] and stack['quantity'] == 3
    state = second.json()
    assert state['values']['load.total'] == ''
    removed = env.post(client, path + '/dispose', {
        'version': state['version'], 'request_id': secrets.token_hex(16), 'kind': 'backpack',
        'row': items[material]['id'], 'action': 'remove', 'coins': '{}',
    })
    assert removed.status_code == 200
    assert float(removed.json()['values']['load.total']) == 7

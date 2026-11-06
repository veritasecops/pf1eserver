from copy import deepcopy
import json
import secrets

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper.character_rules import calculate, defaults
from pathkeeper.database import engine
from pathkeeper.models import Character, CoinTransaction
from pathkeeper.rule_catalog import default_catalog
from .test_character_weapons import setup_sheet, purchase_data
from .test_character_wizard import fighter
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character


def disposal(client, character, kind='weapon', row=0, action='remove', coins=None, **changes):
    state=client.get(f'/characters/{character}/equipment').json()
    return dict(version=state['version'],request_id=secrets.token_hex(16),kind=kind,row=row,action=action,
                coins=json.dumps(coins or {}),**changes)


def test_remove_clears_complete_entry_gear_and_weight_and_survives_autosave(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    bought=env.post(client,path+'/equipment',purchase_data(client,character,{'longsword':2,'leather':1})).json()
    assert bought['values']['load.total']=='23'
    sword = next(item for item in bought['backpack'] if item['catalog_id'] == 'longsword')
    response = env.post(client, path + '/equipment/dispose',
                        disposal(client, character, kind='backpack', row=sword['id']))
    assert response.status_code==200,response.text
    body=response.json()
    assert all(item['id'] != sword['id'] for item in body['backpack'])
    assert body['purchase_fields']['weapon.0.name']==body['purchase_fields']['weapon.0.notes']==''
    assert body['purchase_fields']['gear.0.name']==body['purchase_fields']['gear.0.weight']==''
    assert body['purchase_fields']['money.gp']=='60'
    assert body['values']['load.total']=='15'
    shop=client.get(path+'/equipment').json()
    assert shop['owned']=={'leather':1} and shop['maxNewWeapons']==6
    form=SheetForm(client.get(path).text)
    form.values['notes']='Still removed'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=SheetForm(client.get(path).text)
    assert form.values['weapon.0.name']==form.values['gear.0.name']==''
    result=env.post(client,path+'/equipment',purchase_data(client,character,{'dagger':1})).json()
    assert result['values']['weapon.0.name']=='Dagger' and result['values']['load.total']=='16'


def test_sale_credits_exact_coin_types_once_and_checks_retries(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    env.post(client,path+'/equipment',purchase_data(client,character,{'leather':2}))
    payload=disposal(client,character,kind='armor',action='sell',coins={'pp':2,'gp':3,'sp':4,'cp':5})
    response=env.post(client,path+'/equipment/dispose',payload)
    assert response.status_code==200,response.text
    body=response.json();fields=body['purchase_fields']
    assert {coin:fields['money.'+coin] for coin in ['pp','gp','sp','cp']}=={'pp':'2','gp':'83','sp':'4','cp':'5'}
    assert fields['armor.0.name']==fields['armor.0.notes']==fields['gear.0.name']==''
    assert body['values']['load.total']=='0'
    retry=env.post(client,path+'/equipment/dispose',payload)
    assert retry.status_code==200 and retry.json()==body
    assert env.post(client,path+'/equipment/dispose',{**payload,'coins':'{"gp":999}'}).status_code==409
    assert client.get(path+'/equipment').json()['owned']=={}


def test_creation_armor_effects_reverse_once_preserving_manual_offsets(env):
    character=seed_character(env.player)
    data=fighter(defaults(env.player.id));data.update(method='manual',wealth_method='manual',manual_gold=500000)
    data['abilities']['dex']=18
    data['equipment'].pop('leather');data['equipment']['full-plate']=1;data['armor']='full-plate'
    catalog=default_catalog();computed=calculate(data,{},catalog)
    with Session(engine()) as db:
        saved=db.get(Character,character.id);saved.level=1
        saved.sheet_data={'schema':1,'input':data,'catalog':catalog,'computed':computed,'rolls':[]}
        saved.play_data={'ac.armor':'11','ac.dex':'2','skill.climb.misc':'-5','speed.armor':'25'}
        db.commit()
    client=env.login(env.player);path=f'/characters/{character.id}'
    before=SheetForm(client.get(path).text)
    armor_row=next(row for row in range(6) if before.values[f'armor.{row}.name']=='Full plate')
    result=env.post(client,path+'/equipment/dispose',disposal(client,character.id,kind='armor',row=armor_row))
    assert result.status_code==200,result.text
    fields=result.json()['purchase_fields']
    assert fields['ac.armor']=='2' and fields['ac.dex']=='5'
    assert fields['skill.climb.misc']=='1' and fields['speed.armor']=='35'
    assert result.json()['values']['ac.total']=='19'
    # Buying and removing the same catalog item again cannot reverse creation effects twice.
    bought=env.post(client,path+'/equipment',purchase_data(client,character.id,{'full-plate':1}))
    assert bought.status_code==200,bought.text
    again=env.post(client,path+'/equipment/dispose',disposal(client,character.id,kind='armor',row=armor_row))
    assert again.status_code==200,again.text
    sheet=SheetForm(client.get(path).text)
    assert sheet.values['ac.armor']=='2' and sheet.values['skill.climb.misc']=='1'


@pytest.mark.parametrize('changes',[
    {'coins':'{"gp":-1}'},{'coins':'{"gp":1.5}'},{'coins':'{"gp":true}'},{'coins':'{"gp":1000000001}'},
    {'coins':'{"gold":1}'},{'coins':'[]'},{'coins':'bad'},{'coins':'{}'},
    {'kind':'gear'},{'row':6},{'action':'gift'},{'request_id':'bad'},
])
def test_invalid_sales_are_atomic(env,changes):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    env.post(client,path+'/equipment',purchase_data(client,character,{'dagger':1}))
    payload=disposal(client,character,action='sell',coins={'gp':1});payload.update(changes)
    with Session(engine()) as db:before=deepcopy(db.get(Character,character).play_data)
    assert env.post(client,path+'/equipment/dispose',payload).status_code==422
    with Session(engine()) as db:assert db.get(Character,character).play_data==before


def test_access_csrf_stale_versions_overflow_and_detached_gear(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    env.post(client,path+'/equipment',purchase_data(client,character,{'dagger':1}))
    payload=disposal(client,character,action='sell',coins={'gp':1})
    assert env.post(env.login(env.player2),path+'/equipment/dispose',payload).status_code==404
    assert env.post(client,path+'/equipment/dispose',payload,use_csrf=False).status_code==403
    assert env.post(client,path+'/equipment/dispose',{**payload,'version':1}).status_code==409
    form=SheetForm(client.get(path).text)
    assert env.post(client, path + '/treasure', {
        'version': form.values['version'], 'request_id': secrets.token_hex(16), 'action': 'add', 'coin': 'gp',
        'amount': 1000000000 - int(form.values['money.gp']),
    }).status_code == 200
    form = SheetForm(client.get(path).text)
    assert env.post(client, path + '/backpack', {
        'version': form.values['version'], 'item_id': secrets.token_hex(16),
        'name': 'My unrelated bag', 'quantity': 1, 'value': '0',
    }).status_code == 200
    payload=disposal(client,character,action='sell',coins={'gp':1})
    assert env.post(client,path+'/equipment/dispose',payload).status_code==422
    payload=disposal(client,character)
    assert env.post(env.login(env.admin),path+'/equipment/dispose',payload).status_code==200
    saved=SheetForm(client.get(path).text)
    assert saved.values['gear.1.name']=='My unrelated bag × 1' and saved.values['money.gp']=='1000000000'
    assert env.post(client,path+'/equipment/dispose',disposal(client,character)).status_code==409


def test_carried_weight_is_calculated_and_unknown_weights_stay_blank(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    form=SheetForm(client.get(path).text)
    assert 'load.total' in form.readonly
    with Session(engine()) as db:
        record = db.get(Character, character)
        record.play_data = {**(record.play_data or {}), 'backpack': [
            {'id': secrets.token_hex(16), 'name': 'A pack', 'quantity': 1, 'unit_cp': 0, 'gear_row': 0, 'gear_weight': '2.5'},
            {'id': secrets.token_hex(16), 'name': 'A rope', 'quantity': 1, 'unit_cp': 0, 'gear_row': 1, 'gear_weight': '3'},
        ]}
        db.commit()
    saved = SheetForm(client.get(path).text)
    assert saved.values['load.total'] == '5.5'
    saved.values['gear.1.weight'] = 'Special'
    assert env.post(client, path + '/play-sheet', saved.values).status_code == 303
    assert SheetForm(client.get(path).text).values['load.total'] == '5.5'


def test_backpack_add_remove_and_sell_use_the_sheet_treasure(env):
    client, character = setup_sheet(env)
    path = f'/characters/{character}'
    page = client.get(path)
    assert 'id="open-backpack"' in page.text and 'id="character-backpack"' in page.text
    version = SheetForm(page.text).values['version']
    add = {'version': version, 'item_id': secrets.token_hex(16), 'name': 'Silver brooch', 'quantity': 2, 'value': '3.25'}
    assert env.post(client, path + '/backpack', {**add, 'value': '3.251'}).status_code == 422
    added = env.post(client, path + '/backpack', add)
    assert added.status_code == 200, added.text
    result = added.json()
    assert result['backpack'] == [{'id': add['item_id'], 'name': 'Silver brooch', 'quantity': 2, 'unit_cp': 325,
                                  'gear_row': 0, 'gear_weight': '0'}]
    assert result['purchase_fields']['gear.0.name'] == 'Silver brooch × 2'
    assert env.post(client, path + '/backpack', add).json()['backpack'] == result['backpack']
    assert env.post(client, path + '/backpack', {
        'version': result['version'], 'item_id': add['item_id'], 'action': 'note', 'notes': 'Family heirloom',
    }).json()['purchase_fields']['gear.0.notes'] == 'Family heirloom'
    assert result['purchase_fields']['money.gp'] == '100'
    sheet = SheetForm(client.get(path).text)
    sheet.values['notes'] = 'Keep backpack on autosave'
    assert env.post(client, path + '/play-sheet', sheet.values).status_code == 303
    sale = disposal(client, character, kind='backpack', row=add['item_id'], action='sell', coins={'gp': 6, 'sp': 5})
    sold = env.post(client, path + '/equipment/dispose', sale)
    assert sold.status_code == 200, sold.text
    result = sold.json()
    assert result['backpack'] == []
    assert result['purchase_fields']['money.gp'] == '106'
    assert result['purchase_fields']['money.sp'] == '5'
    assert env.post(client, path + '/equipment/dispose', sale).json()['purchase_fields'] == result['purchase_fields']
    second = {**add, 'version': result['version'], 'item_id': secrets.token_hex(16), 'name': 'Empty pouch'}
    assert env.post(client, path + '/backpack', second).status_code == 200
    remove = disposal(client, character, kind='backpack', row=second['item_id'])
    removed = env.post(client, path + '/equipment/dispose', remove)
    assert removed.status_code == 200
    assert removed.json()['backpack'] == []
    assert removed.json()['purchase_fields']['money.gp'] == '106'
    assert removed.json()['purchase_fields']['money.sp'] == '5'
    with Session(engine()) as db:
        sales = db.scalars(select(CoinTransaction).where(CoinTransaction.character_id == character,
                                                         CoinTransaction.source == 'backpack_sale')).all()
        assert len(sales) == 1 and sales[0].net_cp == 650 and sales[0].delta['sp'] == '5'

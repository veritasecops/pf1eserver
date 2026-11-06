import secrets
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character, User
from pathkeeper.deluxe_sheet import baseline
from pathkeeper.character_rules import calculate, defaults
from .test_character_wizard import fighter
from .test_character_weapons import setup_sheet, purchase_data
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character


def test_wizard_equipped_choices_seed_both_inventory_views(env):
    data=fighter(defaults(env.player.id))
    data.update(equipment={'dagger':1,'leather':1,'buckler':1},weapon='dagger',armor='leather',shield='buckler')
    from pathkeeper.rule_catalog import default_catalog
    catalog=default_catalog()
    character=Character(owner_id=env.player.id,name='Tester',ancestry='Human',class_name='Fighter',level=1,
                        sheet_data={'input':data,'computed':calculate(data,{},catalog),'catalog':catalog})
    with Session(engine()) as db:
        values=baseline(character,db.get(User,env.player.id))
    assert values['weapon.0.equipped']=='1'
    assert values['armor.0.equipped']=='1' and values['armor.1.equipped']=='1'
    assert all(values[f'gear.{row}.equipped']=='1' for row in range(3))


def test_weapon_armor_and_gear_markers_sync_and_persist_after_purchase(env):
    client,character=setup_sheet(env)
    path=f'/characters/{character}'
    response=env.post(client,path+'/equipment',purchase_data(client,character,{'dagger':1,'leather':1}))
    assert response.status_code==200,response.text
    assert response.json()['equipment_state']['weapon.0.equipped']==''
    form=SheetForm(client.get(path).text)
    assert all(key in form.names for key in ('weapon.0.equipped','armor.0.equipped','gear.0.equipped'))
    assert 'weapon.0.equipped' not in form.readonly
    form.values['weapon.0.equipped']='1'
    form.values['armor.0.equipped']='1'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    saved=SheetForm(client.get(path).text)
    assert saved.values['weapon.0.equipped']==saved.values['gear.0.equipped']=='1'
    assert saved.values['armor.0.equipped']==saved.values['gear.1.equipped']=='1'
    saved.values.pop('gear.0.equipped')
    assert env.post(client,path+'/play-sheet',saved.values).status_code==303
    saved=SheetForm(client.get(path).text)
    assert saved.values.get('weapon.0.equipped','')==saved.values.get('gear.0.equipped','')==''
    assert saved.values['armor.0.equipped']=='1'
    assert env.post(client,path+'/equipment',purchase_data(client,character,{'dagger':1,'buckler':1})).status_code==200
    saved=SheetForm(client.get(path).text)
    assert saved.values['armor.0.equipped']=='1' and saved.values['gear.1.equipped']=='1'
    assert saved.values.get('armor.1.equipped','')==''
    assert saved.values['money.gp']=='81'


def test_manual_equipment_can_be_equipped_and_empty_rows_are_cleared(env):
    character=seed_character(env.player);client=env.login(env.player);path=f'/characters/{character.id}'
    form=SheetForm(client.get(path).text)
    item_id = secrets.token_hex(16)
    assert env.post(client, path + '/backpack', {
        'version': form.values['version'], 'item_id': item_id, 'name': 'Backpack', 'quantity': 1, 'value': '0',
    }).status_code == 200
    form = SheetForm(client.get(path).text)
    form.values.update({'gear.0.name':'Forged name','gear.0.equipped':'1','gear.1.equipped':'1'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    saved=SheetForm(client.get(path).text)
    assert saved.values['gear.0.equipped']=='1' and not saved.values.get('gear.1.equipped')
    assert saved.values['gear.0.name'] == 'Backpack × 1'
    from .test_equipment_disposal import disposal
    assert env.post(client, path + '/equipment/dispose',
                    disposal(client, character.id, kind='backpack', row=item_id)).status_code == 200
    assert not SheetForm(client.get(path).text).values.get('gear.0.equipped')


def test_equipment_marker_validation_and_permissions(env):
    character=seed_character(env.player);client=env.login(env.player);path=f'/characters/{character.id}'
    form=SheetForm(client.get(path).text)
    form.values.update({'gear.0.name':'Backpack','gear.0.equipped':'yes'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==422
    form.values['gear.0.equipped']='1'
    other=env.login(env.player2)
    assert env.post(other,path+'/play-sheet',form.values).status_code==404
    assert client.post(path+'/play-sheet',data={key:value for key,value in form.values.items() if key!='csrf'}).status_code==403

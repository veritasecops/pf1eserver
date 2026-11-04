from copy import deepcopy
import json

from sqlalchemy.orm import Session

from pathkeeper.armor import table_armor
from pathkeeper.character_rules import calculate, clean, defaults
from pathkeeper.database import engine
from pathkeeper.models import Character, RuleCatalog, SchemaMigration
from pathkeeper.rule_catalog import default_catalog
from .test_character_wizard import fighter, save, finish
from .test_character_weapons import setup_sheet, purchase_data
from .test_deluxe_sheet import SheetForm
from .test_weapon_picker import setup_shop, catalog_version


def test_import_and_all_armor_calculations():
    entries=table_armor()
    assert len(entries)==72
    assert {kind:sum(item['category']==kind for item in entries.values()) for kind in ('light','medium','heavy','shield','extra')}==dict(light=19,medium=14,heavy=16,shield=14,extra=9)
    assert entries['full-plate']['cost']==150000
    assert entries['chain-shirt']['spell_failure']==20
    assert entries['shield-tower']['max_dex']==2
    assert entries['stoneplate']['speed_30']==15
    assert not set(entries)&set(default_catalog()['weapons'])
    catalog=default_catalog()
    for key,item in entries.items():
        data=fighter(defaults(1))
        data.update(equipment={key:1},armor=key if item['kind']=='armor' else '',shield=key if item['kind']=='shield' else '',weapon='')
        result=calculate(clean(data,1,catalog),{},catalog)
        assert result['spent_cp']==item['cost']
        assert isinstance(result['weight'],(int,float))


def test_wizard_mixed_cart_persists_equipped_armor_and_shield(env):
    client,draft,version=setup_shop(env)
    path=f'/api/character-drafts/{draft}/equipment'
    payload={'version':version,'catalog_version':catalog_version(client,draft),'payload':json.dumps({'quantities':{'dagger':1,'chain-shirt':1,'buckler':1}})}
    response=env.post(client,path,payload)
    assert response.status_code==200,response.text
    body=response.json()
    assert body['computed']['remaining_cp']==5800
    assert env.post(client,path,payload).status_code==409
    data=body['data']
    data.update(armor='chain-shirt',shield='buckler',weapon='dagger')
    saved=save(env,client,draft,body['version'],data,8)
    assert saved.status_code==200,saved.text
    assert saved.json()['computed']['armor_check_penalty']==-3
    made=finish(env,client,draft,saved.json()['version'])
    assert made.status_code==200,made.text
    sheet=SheetForm(client.get(made.json()['location']).text)
    assert sheet.values['armor.1.name']=='Chain shirt'
    assert sheet.values['armor.1.failure']=='20%'
    assert sheet.values['money.gp']=='58'


def test_sheet_mixed_purchase_idempotency_readonly_notes_and_autosave(env):
    client,character=setup_sheet(env)
    path=f'/characters/{character}'
    payload=purchase_data(client,character,{'dagger':1,'leather':2,'buckler':1})
    response=env.post(client,path+'/equipment',payload)
    assert response.status_code==200,response.text
    body=response.json()
    assert body['purchase_fields']['money.gp']=='73'
    retry=env.post(client,path+'/equipment',payload)
    assert retry.status_code==200 and retry.json()['version']==body['version']
    assert body['values']['armor.0.name']=='Leather'
    assert body['values']['armor.0.quantity']=='2'
    assert body['values']['armor.1.bonus']=='1'
    assert body['values']['armor.1.failure']=='5%'
    assert body['armor_links']['0']['url']==table_armor()['leather']['url']
    form=SheetForm(client.get(path).text)
    assert 'armor.0.bonus' in form.readonly and 'armor.0.notes' not in form.readonly
    form.values.update({'armor.0.name':'Forged','armor.0.bonus':'99','armor.0.notes':'Personal armor note'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=SheetForm(client.get(path).text)
    assert form.values['armor.0.name']=='Leather' and form.values['armor.0.bonus']=='2'
    assert form.values['armor.0.notes']=='Personal armor note'
    repeat=env.post(client,path+'/equipment',purchase_data(client,character,{'leather':1}))
    assert repeat.status_code==200
    assert repeat.json()['values']['armor.0.quantity']=='3'
    assert repeat.json()['purchase_fields']['money.gp']=='63'


def test_sheet_armor_limit_and_insufficient_funds_are_atomic(env):
    client,character=setup_sheet(env)
    path=f'/characters/{character}'
    for cart in ({'dagger':1,'full-plate':1}, {'padded':1,'leather':1,'haramaki':1,'reinforced-tunic':1,'hide':1,'buckler':1,'light-shield':1}):
        response=env.post(client,path+'/equipment',purchase_data(client,character,cart))
        assert response.status_code==422
        state=client.get(path+'/equipment').json()
        assert state['budget']==10000 and state['owned']=={}


def test_admin_armor_round_trip_and_archiving(env):
    client=env.login(env.admin)
    assert client.get('/administration/catalog?kind=armor').status_code==200
    assert client.get('/administration/catalog/armor/leather').status_code==200
    item=deepcopy(table_armor()['leather'])
    data={key:'' if value is None else str(value) for key,value in item.items() if key not in {'aliases','kind','enabled'}}
    data.update(key='leather',version=1,enabled='on',aliases='Old leather',armor='3',cost='1200',url='https://example.com/leather')
    assert env.post(client,'/administration/catalog/armor',data).status_code==303
    with Session(engine()) as db:
        entry=db.get(RuleCatalog,1).data['armor']['leather']
        assert entry['armor']==3 and entry['cost']==1200 and entry['aliases']==['Old leather']
    data.update(version=2,url='javascript:alert(1)')
    assert env.post(client,'/administration/catalog/armor',data).status_code==422
    other=env.login(env.player)
    assert env.post(other,'/administration/catalog/armor',data).status_code==403


def test_armor_migration_is_repeatable_and_preserves_admin_data(env,isolated_database):
    from pathkeeper.migrations import migrate
    data=default_catalog();data.pop('armor')
    data['weapons']['dagger']['cost']=999
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1,data=data));db.commit()
    migrate(isolated_database)
    with Session(engine()) as db:
        record=db.get(RuleCatalog,1)
        assert len(record.data['armor'])==72 and record.data['weapons']['dagger']['cost']==999
        changed=deepcopy(record.data);changed['armor']['leather']['cost']=777
        record.data=changed;db.commit()
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(RuleCatalog,1).data['armor']['leather']['cost']==777
        assert db.get(SchemaMigration,11)

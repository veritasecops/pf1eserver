from copy import deepcopy
import json
import re

import pytest
from sqlalchemy.orm import Session

from pathkeeper.character_rules import calculate, clean, defaults
from pathkeeper.database import engine
from pathkeeper.deluxe_sheet import baseline
from pathkeeper.models import Character, RuleCatalog, SchemaMigration, User
from pathkeeper.rule_catalog import default_catalog
from pathkeeper.weapons import table_weapons, merge_weapon_tables, safe_weapon_url
from .test_character_wizard import fighter, start, save, finish
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character


def weapon_form(key='longsword',version=1,**changes):
    item=deepcopy(table_weapons()[key])
    form={name:('on' if value else '') if isinstance(value,bool) else '' if value is None else str(value)
          for name,value in item.items() if name not in {'kind','aliases'}}
    form['aliases']='\n'.join(item.get('aliases',[]))
    return {**form,'key':key,'version':version,**changes}


def test_import_contains_all_requested_tables_and_exact_reference_values():
    weapons=table_weapons()
    assert len(weapons)==279
    assert sum(w['kind']=='weapon' for w in weapons.values())==243
    assert {group:sum(w['group']==group for w in weapons.values()) for group in ('simple','martial','exotic')}=={'simple':50,'martial':111,'exotic':118}
    assert all(safe_weapon_url(w['url'])==w['url'] for w in weapons.values())
    assert weapons['longsword']['critical']=='19-20/x2'
    assert weapons['quarterstaff']['damage']=='1d6/1d6'
    assert weapons['blowgun']['small_damage']=='1'
    assert weapons['net']['damage']=='—'
    assert weapons['shield-light']['cost'] is None and weapons['shield-light']['cost_text']=='3 gp/9 gp'
    assert weapons['shield-light']['weight'] is None
    assert weapons['longbow-composite-plus-3']['strength_rating']==3
    assert weapons['dagger']['url']=='https://www.d20pfsrd.com/equipment/weapons/weapon-descriptions/dagger'
    assert 'arrows' in weapons and 'bolts' in weapons and weapons['arrows']['kind']=='gear'
    for key in weapons:
        assert 'firearm' not in key and 'musket' not in key and 'pistol' not in key


@pytest.mark.parametrize('url',['javascript:alert(1)','data:text/html,test','//evil.example/x','https://user:password@example.com','https://example.com/\nx','https://example.com:bad/x'])
def test_unsafe_weapon_links_are_rejected(url):
    assert safe_weapon_url(url)==''


def test_every_imported_weapon_survives_validation_and_calculation():
    catalog=default_catalog()
    for key,item in catalog['weapons'].items():
        data=fighter(defaults(1))
        data.update(equipment={key:1},armor='',shield='',weapon=key if item['kind']=='weapon' else '')
        result=calculate(clean(data,1,catalog),{},catalog)
        assert isinstance(result['weight'],(int,float))
        assert result['spent_cp']==(item['cost'] or 0)
        if item['cost'] is None: assert any('actual cost' in message for message in result['warnings'])


def test_weapon_admin_round_trip_all_aspects_and_safe_links(env):
    admin=env.login(env.admin)
    assert admin.get('/administration/catalog?kind=weapons').status_code==200
    form=weapon_form(damage='1d8/1d6',small_damage='1d6/1d4',critical='19–20/×3',range='15 ft.',
                     damage_type='B or P',special='trip, reach',source='House rules',cost='3200',cost_text='32 gp',
                     weight='6.5',weight_text='6.5 lbs.',category='two-handed',two_handed='on',notes='Custom rules',
                     url='https://www.d20pfsrd.com/equipment/weapons/weapon-descriptions/longsword#test',aliases='Old sword')
    response=env.post(admin,'/administration/catalog/weapons',form)
    assert response.status_code==303
    with Session(engine()) as db:
        item=db.get(RuleCatalog,1).data['weapons']['longsword']
        for field in ('damage','small_damage','critical','range','damage_type','special','source','url','notes','category'):
            assert item[field]==form[field]
        assert item['weight']==6.5 and item['cost']==3200 and item['two_handed']
        assert item['aliases']==['Old sword']
    page=admin.get('/administration/catalog/weapons/longsword')
    assert 'Open weapon reference' in page.text and form['url'] in page.text
    assert env.post(admin,'/administration/catalog/weapons',weapon_form(version=2,url='javascript:alert(1)')).status_code==422
    assert env.post(admin,'/administration/catalog/weapons',weapon_form(version=2,group='firearm')).status_code==422
    # Double damage, flat damage, non-damaging attacks and variable prices all round-trip.
    version=2
    for key in ('quarterstaff','blowgun','net','shield-light','arrows'):
        assert env.post(admin,'/administration/catalog/weapons',weapon_form(key,version=version)).status_code==303
        version+=1



def test_new_sheet_seeds_weapon_stats_and_live_links_follow_admin_edits(env):
    client,draft_id,version,data=start(env)
    response=save(env,client,draft_id,version,fighter(data))
    made=finish(env,client,draft_id,response.json()['version'])
    path=made.json()['location']
    page=client.get(path)
    form=SheetForm(page.text)
    assert form.values['weapon.0.critical']=='19-20/x2'
    assert form.values['weapon.0.type']=='S'
    assert form.values['weapon.0.range']=='—'
    original=table_weapons()['longsword']['url']
    assert original in page.text
    form.values['weapon.0.attack']='99'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    admin=env.login(env.admin)
    updated='https://www.d20pfsrd.com/equipment/weapons/weapon-descriptions/longsword#updated'
    assert env.post(admin,'/administration/catalog/weapons',weapon_form(url=updated)).status_code==303
    changed=client.get(path)
    assert updated in changed.text
    edited=SheetForm(changed.text)
    assert edited.values['weapon.0.attack']=='99'
    edited.values['weapon.0.name']='Rapier'
    response=client.post(path+'/play-sheet',data=edited.values,headers={'Accept':'application/json','X-Sheet-Save-Id':'a'*32})
    assert response.status_code==200
    assert response.json()['weapon_links']['0']['url']==table_weapons()['rapier']['url']
    current=SheetForm(client.get(path).text)
    current.values['weapon.0.name']='A custom weapon'
    response=client.post(path+'/play-sheet',data=current.values,headers={'Accept':'application/json','X-Sheet-Save-Id':'b'*32})
    assert response.status_code==200 and '0' not in response.json()['weapon_links']


def test_migration_enriches_catalog_without_rewriting_characters_or_admin_overrides(env,isolated_database):
    from pathkeeper.migrations import migrate
    migrate(isolated_database)
    character=seed_character(env.player)
    old=default_catalog(legacy=True)
    original_data=fighter(defaults(env.player.id))
    snapshot={'input':original_data,'computed':calculate(original_data,{},old),'catalog':deepcopy(old)}
    custom=deepcopy(old)
    custom['weapons']['longsword']['cost']=1900
    custom['weapons']['longsword']['enabled']=False
    custom['weapons']['custom-sabre']={**custom['weapons']['rapier'],'name':'Custom sabre'}
    with Session(engine()) as db:
        record=db.get(Character,character.id)
        record.sheet_data=snapshot
        db.get(RuleCatalog,1).data=custom
        db.delete(db.get(SchemaMigration,10))
        db.commit()
        version=record.version
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        record=db.get(RuleCatalog,1)
        assert len(record.data['weapons'])==280
        assert record.data['weapons']['longsword']['cost']==1900
        assert not record.data['weapons']['longsword']['enabled']
        assert record.data['weapons']['longsword']['critical']=='19-20/x2'
        assert db.get(SchemaMigration,10)
        character=db.get(Character,character.id)
        assert character.sheet_data==snapshot and character.version==version
    page=env.login(env.player).get(f'/characters/{character.id}')
    assert table_weapons()['longsword']['url'] in page.text


def test_composite_bows_thrown_weapons_and_slings_calculate_strength():
    data=fighter(defaults(1))
    data['abilities']['str']=16 # human flexible +2 -> Strength modifier +4
    data.update(armor='',shield='')
    for key,damage in [('javelin',4),('sling',4),('longbow',0),('longbow-composite-plus-3',3)]:
        data.update(weapon=key,equipment={key:1})
        assert calculate(data,{})['damage_modifier']==damage
    data['abilities']['str']=10 # final modifier +1, below the +3 bow rating
    result=calculate(data,{})
    assert result['damage_modifier']==1 and result['weapon_attack']==-1 # BAB +1, DEX 0, mismatch -2

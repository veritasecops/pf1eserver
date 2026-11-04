from copy import deepcopy
import json
import re

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.deities import choose_deity, deity_choices, table_deities
from pathkeeper.models import Character, RuleCatalog, SchemaMigration
from pathkeeper.rule_catalog import default_catalog
from pathkeeper.weapons import safe_weapon_url
from .test_character_wizard import start, fighter, save, finish
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character


def test_requested_deity_sections_and_individual_links():
    data=table_deities()
    assert len(data)==157
    assert data['atheism']['name']=='Atheism'
    assert data['atheism']['url']=='https://pathfinderwiki.com/wiki/Atheism'
    assert set(data['irori']['sections'])=={'In the Inner Sea Region','Ascended deities','In other regions'}
    assert data['aroden']['sections']==['Ascended deities']
    assert data['anubis']['regions']==['Osirion']
    assert all(item['name'] and safe_weapon_url(item['url']) for item in data.values())
    assert choose_deity('Sarenrae',data)=='sarenrae'
    assert choose_deity('Unknown old belief',data,'Unknown old belief')=='Unknown old belief'
    with pytest.raises(HTTPException): choose_deity('Unknown new belief',data)


def test_admin_deity_create_edit_archive_and_safety(env):
    admin=env.login(env.admin)
    assert admin.get('/administration/catalog?kind=deities').status_code==200
    assert admin.get('/administration/catalog/deities/new').status_code==200
    payload=dict(key='house-patron',new='1',version=1,name='House Patron',url='https://example.com/patron',enabled='on')
    assert env.post(admin,'/administration/catalog/deities',payload).status_code==303
    payload.update(new='0',version=2,name='House Protector')
    assert env.post(admin,'/administration/catalog/deities',payload).status_code==303
    with Session(engine()) as db:
        item=db.get(RuleCatalog,1).data['deities']['house-patron']
        assert item['name']=='House Protector' and item['aliases']==['House Patron']
    payload.update(version=3,url='javascript:alert(1)')
    assert env.post(admin,'/administration/catalog/deities',payload).status_code==422
    payload.update(url='https://example.com/patron',enabled='')
    assert env.post(admin,'/administration/catalog/deities',payload).status_code==303
    with Session(engine()) as db:
        data=db.get(RuleCatalog,1).data['deities']
        assert 'house-patron' not in {item['id'] for item in deity_choices(data)[0]}
        assert 'house-patron' in {item['id'] for item in deity_choices(data,'House Patron')[0]}
        assert choose_deity('house-patron',data,'House Patron')=='house-patron'
        with pytest.raises(HTTPException): choose_deity('house-patron',data)
    player=env.login(env.player)
    assert player.get('/administration/catalog?kind=deities').status_code==403
    assert env.post(player,'/administration/catalog/deities',payload).status_code==403
    assert admin.post('/administration/catalog/deities',data=payload).status_code==403


def test_wizard_deity_choice_reaches_created_sheet(env):
    client,draft,version,data=start(env)
    data=fighter(data);data['deity']='atheism'
    saved=save(env,client,draft,version,data,10)
    assert saved.status_code==200,saved.text
    page=client.get(f'/characters/drafts/{draft}')
    boot=json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert any(item['id']=='atheism' and item['url'].endswith('/Atheism') for item in boot['deities'])
    made=finish(env,client,draft,saved.json()['version'])
    assert made.status_code==200,made.text
    sheet=SheetForm(client.get(made.json()['location']).text)
    assert sheet.values['deity']=='atheism' and 'sarenrae' in sheet.options['deity']
    with Session(engine()) as db:
        character=db.get(Character,int(made.json()['location'].rsplit('/',1)[1]))
        assert character.sheet_data['input']['deity']=='atheism'


def test_wizard_rejects_unlisted_deity(env):
    client,draft,version,data=start(env)
    data['deity']='Not a catalog selection'
    assert save(env,client,draft,version,data,10).status_code==422


def test_sheet_uses_live_catalog_and_preserves_legacy_selections(env):
    character=seed_character(env.player)
    with Session(engine()) as db:
        db.get(Character,character.id).play_data={'deity':'Sarenrae'}
        catalog=default_catalog();catalog['deities']['sarenrae'].update(name='Sun Goddess',aliases=['Sarenrae'],url='https://example.com/sun')
        db.add(RuleCatalog(id=1,data=catalog));db.commit()
    client=env.login(env.player);path=f'/characters/{character.id}'
    page=client.get(path)
    form=SheetForm(page.text)
    assert form.values['deity']=='sarenrae'
    assert 'Sun Goddess' in page.text and 'https://example.com/sun' in page.text
    form.values['deity']='atheism'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    assert SheetForm(client.get(path).text).values['deity']=='atheism'
    form=SheetForm(client.get(path).text);form.values['deity']='Invalid patron'
    assert env.post(client,path+'/play-sheet',form.values).status_code==422
    with Session(engine()) as db:
        db.get(Character,character.id).play_data={'deity':'An old custom belief'};db.commit()
    form=SheetForm(client.get(path).text)
    assert form.values['deity']=='An old custom belief'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303


def test_deity_migration_preserves_other_catalogs_and_repeats(env,isolated_database):
    from pathkeeper.migrations import migrate
    data=default_catalog();data.pop('deities');data['armor']['leather']['cost']=1234
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1,data=data));db.commit()
    migrate(isolated_database)
    with Session(engine()) as db:
        record=db.get(RuleCatalog,1)
        assert len(record.data['deities'])==157 and record.data['armor']['leather']['cost']==1234
        updated=deepcopy(record.data);updated['deities']['atheism']['url']='https://example.com/belief'
        record.data=updated;db.commit()
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(RuleCatalog,1).data['deities']['atheism']['url']=='https://example.com/belief'
        assert db.get(SchemaMigration,12)


def test_sheet_and_editing_wizard_keep_the_same_deity(env):
    client,draft,version,data=start(env)
    data=fighter(data);data['deity']='atheism'
    saved=save(env,client,draft,version,data,10)
    made=finish(env,client,draft,saved.json()['version'])
    path=made.json()['location']
    form=SheetForm(client.get(path).text);form.values['deity']='sarenrae'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    page=client.get(path+'/sheet/edit')
    boot=json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot['data']['deity']=='sarenrae'
    boot['data']['deity']='irori'
    saved=save(env,client,boot['draft_id'],boot['version'],boot['data'],10)
    assert saved.status_code==200,saved.text
    made=finish(env,client,boot['draft_id'],saved.json()['version'])
    assert made.status_code==200,made.text
    assert SheetForm(client.get(path).text).values['deity']=='irori'

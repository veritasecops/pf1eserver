from copy import deepcopy
import json
import re

from sqlalchemy.orm import Session

from pathkeeper.character_rules import calculate, defaults
from pathkeeper.database import engine
from pathkeeper.models import AuditEvent, Character, RuleCatalog, User
from pathkeeper.rule_catalog import default_catalog
from pathkeeper.deluxe_sheet import sheet_values
from .test_character_wizard import fighter, start, save, finish
from .test_deluxe_sheet import SheetForm


def feat_form(key='Improved Initiative',version=1,**changes):
    return {**dict(key=key,version=version,enabled='on',hint='Custom initiative bonus.',combat='on'),
            'effect.initiative':'6',**changes}


def test_catalog_admin_access_and_csrf(env):
    for account in (env.player,env.gm):
        client=env.login(account)
        assert client.get('/administration/catalog').status_code==403
        assert env.post(client,'/administration/catalog/feats',feat_form()).status_code==403
    admin=env.login(env.admin)
    for kind in ('feats','skills','weapons'):
        assert admin.get('/administration/catalog',params={'kind':kind}).status_code==200
        assert admin.get(f'/administration/catalog/{kind}/new').status_code==200
    assert admin.post('/administration/catalog/feats',data=feat_form()).status_code==403
    assert admin.get('/administration/catalog?kind=bogus').status_code==404


def test_feat_edits_drive_wizard_and_server_and_freeze_character(env):
    client,draft_id,version,data=start(env)
    data=fighter(data)
    admin=env.login(env.admin)
    assert admin.get('/administration/catalog/feats/Improved%20Initiative').status_code==200
    response=env.post(admin,'/administration/catalog/feats',feat_form())
    assert response.status_code==303
    response=save(env,client,draft_id,version,data)
    assert response.status_code==200
    assert response.json()['computed']['initiative']==6
    page=client.get(f'/characters/drafts/{draft_id}')
    boot=json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot['feats']['Improved Initiative']['effects']['initiative']==6
    made=finish(env,client,draft_id,response.json()['version'])
    assert made.status_code==200
    char_id=int(made.json()['location'].rsplit('/',1)[1])
    assert env.post(admin,'/administration/catalog/feats',feat_form(version=1)).status_code==409
    assert env.post(admin,'/administration/catalog/feats',feat_form(version=2,**{'effect.initiative':'9'})).status_code==303
    with Session(engine()) as db:
        character=db.get(Character,char_id)
        assert character.sheet_data['catalog']['feats']['Improved Initiative']['effects']['initiative']==6
        assert sheet_values(character,db.get(User,character.owner_id))['initiative.total']=='6'
        assert db.query(AuditEvent).filter(AuditEvent.event=='catalog.updated').count()==2


def test_add_skill_weapon_and_feat_with_effects_and_choices(env):
    admin=env.login(env.admin)
    assert env.post(admin,'/administration/catalog/skills',dict(new='1',key='lore',name='Lore',version=1,
        enabled='on',ability='wis',bonus='2',classes=['fighter'],trained='on',armor='on')).status_code==303
    weapon=dict(new='1',key='sabre',name='Sabre',version=2,enabled='on',cost='1500',weight='3.25',
                damage='1d8',small_damage='1d6',group='martial',finesse='on')
    assert env.post(admin,'/administration/catalog/weapons',weapon).status_code==303
    form=feat_form('Lore Training',version=3,new='1',choice='skill',repeatable='on',**{'effect.selected_skill':'4','effect.initiative':'0'})
    assert env.post(admin,'/administration/catalog/feats',form).status_code==303
    client,draft_id,version,data=start(env)
    data=fighter(data)
    data.update(skills={'lore':1,'ride':1,'climb':1},feats=[{'name':'Lore Training','choice':'lore'},{'name':'Toughness'}],equipment={'sabre':1},weapon='sabre',armor='',shield='')
    response=save(env,client,draft_id,version,data)
    assert response.status_code==200
    computed=response.json()['computed']
    assert computed['skill_totals']['lore']==10 # WIS 0 + rank 1 + class 3 + catalog 2 + feat 4
    assert computed['weapon_damage']=='1d8'
    made=finish(env,client,draft_id,response.json()['version'])
    assert made.status_code==200, made.text
    page=client.get(made.json()['location'])
    assert 'skill.lore.total' in page.text and 'Lore' in page.text and 'Sabre' in page.text
    form = SheetForm(page.text)
    form.values['ability.wis.score'] = '14'
    assert env.post(client,made.json()['location']+'/play-sheet',form.values).status_code == 303
    saved = SheetForm(client.get(made.json()['location']).text)
    assert saved.values['skill.lore.total'] == '12'
    with Session(engine()) as db:
        char=db.get(Character,int(made.json()['location'].rsplit('/',1)[1]))
        values=sheet_values(char,db.get(User,char.owner_id))
        assert values['skill.lore.total']=='12'


def test_rules_validate_prerequisites_archive_and_effect_types(env):
    admin=env.login(env.admin)
    invalid=feat_form(**{'effect.selected_skill':'3'})
    response=env.post(admin,'/administration/catalog/feats',invalid)
    assert response.status_code==422 and 'requires a skill selection' in response.text
    assert env.post(admin,'/administration/catalog/feats',feat_form(requires='Improved Initiative')).status_code==422
    assert env.post(admin,'/administration/catalog/feats',feat_form(dex='13')).status_code==303
    client,draft_id,version,data=start(env)
    response=save(env,client,draft_id,version,fighter(data))
    assert any('Dexterity 13' in e['message'] for e in response.json()['computed']['errors'])
    assert env.post(admin,'/administration/catalog/feats',feat_form(version=2,enabled='')).status_code==303
    response=save(env,client,draft_id,response.json()['version'],fighter(data))
    assert any('archived' in e['message'] for e in response.json()['computed']['errors'])


def test_default_modifiers_match_existing_rules_and_custom_modifiers_apply():
    data=fighter(defaults(1))
    original=calculate(data,{})
    catalog=default_catalog()
    catalog['feats']['Toughness']['effects']['hp']=5
    catalog['feats']['Combat Reflexes']['effects']={'fortitude':3,'skill:climb':2,'selected_weapon':2}
    catalog['feats']['Combat Reflexes']['choice']='weapon'
    data['bonus_feat']['choice']='longsword'
    changed=calculate(data,{},catalog)
    assert changed['hp']==original['hp']+2
    assert changed['saves']['fortitude']==original['saves']['fortitude']+3
    assert changed['skill_totals']['climb']==original['skill_totals']['climb']+2
    assert changed['weapon_attack']==original['weapon_attack']+2


def test_catalog_migration_is_idempotent_and_keeps_edits(env,isolated_database):
    from pathkeeper.migrations import migrate
    from pathkeeper.models import SchemaMigration
    migrate(isolated_database)
    with Session(engine()) as db:
        record=db.get(RuleCatalog,1)
        updated=deepcopy(record.data)
        updated['feats']['Toughness']['effects']['hp']=7
        record.data=updated
        db.commit()
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(SchemaMigration,9)
        assert db.get(RuleCatalog,1).data['feats']['Toughness']['effects']['hp']==7


def test_archive_skills_weapons_and_change_class_lists(env):
    admin=env.login(env.admin)
    assert env.post(admin,'/administration/catalog/skills',dict(key='perception',name='Perception',version=1,
        enabled='on',ability='wis',bonus='1',classes=['fighter'])).status_code==303
    client,draft_id,version,data=start(env)
    response=save(env,client,draft_id,version,fighter(data))
    assert response.json()['computed']['skill_totals']['perception']==5
    assert env.post(admin,'/administration/catalog/skills',dict(key='perception',name='Perception',version=2,
        ability='wis',bonus='1',classes=['fighter'])).status_code==303
    response=save(env,client,draft_id,response.json()['version'],fighter(data))
    assert any('archived' in e['message'] for e in response.json()['computed']['errors'])
    assert env.post(admin,'/administration/catalog/weapons',dict(key='longsword',name='Longsword',version=3,
        cost='1500',weight='4',damage='1d8',small_damage='1d6',group='martial')).status_code==303
    response=save(env,client,draft_id,response.json()['version'],fighter(data))
    assert any('Longsword is archived' in e['message'] for e in response.json()['computed']['errors'])

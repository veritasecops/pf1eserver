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


def test_character_class_editor_updates_creation_and_future_advancement(env):
    from pathkeeper.class_catalog import class_profile
    from pathkeeper.class_editor import SAVES, SPELL_FIELDS
    from pathkeeper.level_up import feature_choices

    admin = env.login(env.admin)
    player, draft_id, version, data = start(env)
    data = fighter(data)
    original = calculate(data, {})
    assert player.get('/administration/catalog?kind=classes').status_code == 403
    listing = admin.get('/administration/catalog?kind=classes&q=Fighter')
    assert listing.status_code == 200
    assert re.search(r'<a class="catalog-source-link" href="https://www.aonprd.com/[^"]+"[^>]*>Fighter</a>', listing.text)
    assert 'Class reference' not in listing.text
    editor = admin.get('/administration/catalog/classes/fighter')
    assert editor.status_code == 200 and 'name="level.20.bab"' in editor.text
    profile = class_profile(default_catalog(), 'fighter')
    form = {field: profile[field] for field in (
        'name', 'url', 'choices', 'group', 'hd', 'ranks', 'bab', 'wealth_dice',
        'casting_ability', 'caster_delay', 'book', 'starting_book', 'bonus_feat',
    )}
    form.update(key='fighter', version=1, class_skills=[*profile['skills'], 'perception'], automatic_feats='', swap_first=0, swap_frequency=0)
    form.update(zip(SAVES, profile['saves']))
    for level, row in enumerate(profile['levels'], 1):
        prefix = f'level.{level}.'
        form.update({prefix + key: value for key, value in zip(SAVES, row['saves'])})
        form[prefix + 'bab'] = row['bab']
        form[prefix + 'features'] = row['features']
        form[prefix + 'choices'] = '\n'.join(feature_choices(row))
        form[prefix + 'statistics'] = '\n'.join(f'{key}={value}' for key, value in row.get('statistics', {}).items())
        for column in SPELL_FIELDS:
            form[prefix + column] = ', '.join(f'{key}={value}' for key, value in row.get(column, {}).items())
    form.update(name='Vanguard', hd=12)
    assert env.post(admin, '/administration/catalog/classes', {**form, 'hd': 11}).status_code == 422
    assert env.post(admin, '/administration/catalog/classes', form).status_code == 303
    assert env.post(admin, '/administration/catalog/classes', form).status_code == 409
    saved = save(env, player, draft_id, version, data)
    assert saved.json()['computed']['hp'] == original['hp'] + 2
    assert 'perception' in saved.json()['computed']['class_skills']
    made = finish(env, player, draft_id, saved.json()['version'])
    assert made.status_code == 200, made.text
    path = made.json()['location']
    form.update(version=2, hd=10, **{
        'level.2.bab': 3, 'level.2.features': 'Vanguard training', 'level.2.choices': 'Choose a weapon group',
    })
    assert env.post(admin, '/administration/catalog/classes', form).status_code == 303
    sheet = SheetForm(player.get(path).text)
    assert sheet.values['class_name'] == 'Vanguard'
    assert sheet.values['hp.total'] == str(original['hp'] + 2)
    sheet.values['experience'] = '3000'
    assert env.post(player, path + '/play-sheet', sheet.values).status_code == 303
    wizard = player.get(path + '/level-up')
    assert 'Hit Die result (d10)' in wizard.text and 'Choose a weapon group' in wizard.text
    sheet = SheetForm(player.get(path).text)
    response = env.post(player, path + '/level-up', {
        'version': sheet.values['version'], 'target': 2, 'hit_die': 4, 'favored': 'none',
        'rank_climb': 1, 'rank_swim': 2, 'choice_0': 'Heavy blades', 'reviewed': '1',
    })
    assert response.status_code == 303, response.text
    sheet = SheetForm(player.get(path).text)
    assert sheet.values['level'] == '2' and sheet.values['bab'] == '3'


def test_full_feat_index_is_searchable_and_preserves_custom_rules(env):
    from pathkeeper.feats import merge_feat_index, table_feats

    published = table_feats()
    assert len(published) == 3442
    assert published['Ace Trip']['mastery'] == 'weapon'
    assert published['Advance Warning']['cha'] == 15
    custom = {'Toughness': {'enabled': False, 'effects': {'hp': 7}, 'url': 'https://example.com/feat'}}
    merged = merge_feat_index(custom)
    assert set(published) <= merged.keys()
    for field, value in custom['Toughness'].items():
        assert merged['Toughness'][field] == value
    admin = env.login(env.admin)
    first = admin.get('/administration/catalog?kind=feats')
    assert first.status_code == 200 and '3442 entries' in first.text and 'Page 1 of 35' in first.text
    last = admin.get('/administration/catalog?kind=feats&page=35')
    assert last.status_code == 200 and 'Page 35 of 35' in last.text
    found = admin.get('/administration/catalog', params={'kind': 'feats', 'q': 'Ace Trip'})
    assert found.status_code == 200
    assert '>Ace Trip</a>' in found.text and published['Ace Trip']['url'] in found.text

def test_feat_categories_match_aon_and_support_filtering_and_edits(env):
    from pathkeeper.feats import FEAT_CATEGORIES, table_feats

    source = table_feats()
    assert len(FEAT_CATEGORIES) == 39
    assert set(FEAT_CATEGORIES) - {"General"} == {label for feat in source.values() for label in feat.get("categories", [])}
    assert {"Combat", "Combat Stamina"} <= set(source["Adder Strike"]["categories"])
    assert "Weapon Mastery" in source["Ace Trip"]["categories"]
    admin = env.login(env.admin)
    page = admin.get("/administration/catalog", params={"kind": "feats", "feat_category": "Combat Stamina"})
    assert page.status_code == 200 and "549 entries" in page.text and "Page 1 of 6" in page.text
    assert "feat_category=Combat%20Stamina" in page.text
    assert env.post(admin, "/administration/catalog/feats", feat_form(
        categories_present="1", categories=["Teamwork"],
    )).status_code == 303
    page = admin.get("/administration/catalog", params={"kind": "feats", "feat_category": "Teamwork", "q": "Improved Initiative"})
    assert "1 entries" in page.text and ">Improved Initiative</a>" in page.text


def test_equipment_catalog_covers_source_and_uses_existing_item_editors(env):
    from pathkeeper.equipment_index import equipment_entries, published_equipment

    entries = published_equipment()
    assert len(entries) == 2495
    assert {item['group'] for item in entries.values()} == {'Weapons', 'Armor', 'Special Materials', 'Miscellaneous'}
    assert entries['miscellaneous-bedroll']['cost_text'] == '1 sp'
    assert entries['special-materials-adamantine']['url'].endswith('#:~:text=Adamantine')
    player = env.login(env.player)
    assert player.get('/administration/equipment').status_code == 403
    admin = env.login(env.admin)
    listing = admin.get('/administration/equipment')
    assert listing.status_code == 200 and f'{len(equipment_entries(default_catalog()))} entries' in listing.text
    assert 'aria-label="Equipment groups"' in listing.text
    assert 'href="/administration/equipment" class="active"' in listing.text
    assert '<h1>Equipment</h1>' in listing.text
    assert 'aria-label="Catalog lists"' not in listing.text
    rules = admin.get('/administration/catalog').text.split('aria-label="Catalog lists"', 1)[1].split('</nav>', 1)[0]
    assert all(f'kind={kind}' not in rules for kind in ('equipment', 'weapons', 'armor'))
    legacy = admin.get('/administration/catalog?kind=equipment&q=Bedroll')
    assert legacy.status_code == 303 and legacy.headers['location'] == '/administration/equipment?q=Bedroll'
    for category, name in [('Fungal Grafts', 'Fungal Eyes'), ('Spellbooks', 'Arctic Call'), ('Vehicles', 'Airship')]:
        listing = admin.get('/administration/equipment', params={ 'equipment_group': 'Miscellaneous', 'equipment_category': category, 'q': name,
        })
        assert f'>{name}</a>' in listing.text
    weapons = admin.get('/administration/equipment?equipment_group=Weapons&q=Longsword')
    assert 'href="/administration/catalog/weapons/longsword"' in weapons.text
    assert 'href="/administration/catalog/weapons/new">Add weapon</a>' in weapons.text
    assert '/administration/catalog/equipment/new' not in weapons.text
    armor = admin.get('/administration/equipment?equipment_group=Armor')
    assert 'href="/administration/catalog/armor/new">Add armor or shield</a>' in armor.text
    assert '/administration/catalog/weapons/new' not in armor.text
    for kind, group in [('weapons', 'Weapons'), ('armor', 'Armor')]:
        editor = admin.get(f'/administration/catalog/{kind}/new')
        assert editor.status_code == 200
        assert f'href="/administration/equipment?equipment_group={group}"' in editor.text

    materials = admin.get('/administration/equipment?equipment_group=Special+Materials&q=Adamantine')
    assert '>Adamantine</a>' in materials.text
    assert 'href="/administration/catalog/equipment/new?equipment_group=Special%20Materials">Add special material</a>' in materials.text

    editor = admin.get('/administration/catalog/equipment/miscellaneous-bedroll')
    assert editor.status_code == 200 and 'value="1 sp"' in editor.text
    response = env.post(admin, '/administration/catalog/equipment', {
        'key': 'miscellaneous-bedroll', 'version': 1, 'name': 'Bedroll',
        'group': 'Miscellaneous', 'equipment_categories': 'Adventuring Gear\nCamping',
        'cost_text': '2 sp', 'weight_text': '5 lb.', 'enabled': 'on',
        'url': entries['miscellaneous-bedroll']['url'],
    })
    assert response.status_code == 303
    listing = admin.get('/administration/equipment?equipment_category=Camping')
    assert listing.status_code == 200 and '>Bedroll</a>' in listing.text and '2 sp' in listing.text


def test_equipment_tab_includes_custom_combat_items_and_archived_gear(env):
    from .test_workspace import seed_character

    admin = env.login(env.admin)
    with Session(engine()) as db:
        record = db.get(RuleCatalog, 1)
        if record is None:
            record = RuleCatalog(id=1, data=default_catalog())
            db.add(record)
        data = deepcopy(record.data)
        data['weapons']['custom-sword'] = {**data['weapons']['longsword'], 'name': 'Custom sword', 'url': '', 'enabled': False}
        data['armor']['custom-coat'] = {**data['armor']['leather'], 'name': 'Custom coat', 'url': ''}
        record.data = data
        db.commit()
        version = record.version
    page = admin.get('/administration/equipment?q=Custom&equipment_status=archived')
    assert 'href="/administration/catalog/weapons/custom-sword"' in page.text
    assert '/administration/catalog/armor/custom-coat' not in page.text
    page = admin.get('/administration/equipment?q=Custom&equipment_status=available')
    assert 'href="/administration/catalog/armor/custom-coat"' in page.text
    assert '/administration/catalog/weapons/custom-sword' not in page.text
    response = env.post(admin, '/administration/catalog/equipment', {
        'key': 'miscellaneous-bedroll', 'version': version, 'name': 'Bedroll',
        'group': 'Miscellaneous', 'equipment_categories': 'Adventuring Gear',
        'cost_text': '2 sp', 'weight_text': '5 lb.', 'enabled': 'on',
    })
    assert response.status_code == 303
    character = seed_character(env.player)
    catalog = env.login(env.player).get(f'/characters/{character.id}/equipment').json()['equipment']
    assert catalog['miscellaneous-bedroll']['cost'] == 20
    assert catalog['miscellaneous-bedroll']['weight'] == 5

from html.parser import HTMLParser

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from pathkeeper.character_rules import calculate, defaults
from pathkeeper.database import engine
from pathkeeper.deluxe_sheet import FIELDS, baseline, sheet_values
from pathkeeper.models import AuditEvent, Character, SchemaMigration, User
from pathkeeper.pf1_data import ALIGNMENTS
from .test_character_wizard import fighter
from .test_workspace import seed_campaign, seed_character


class SheetForm(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.active = False
        self.values = {}
        self.names = []
        self.textarea = None
        self.select = None
        self.readonly = set()
        self.options = {}
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'form': self.active = attrs.get('id') == 'deluxe-form'
        if self.active and tag == 'option' and self.select:
            self.options[self.select].append(attrs.get('value',''))
            if 'selected' in attrs: self.values[self.select] = attrs.get('value','')
        if not self.active or tag not in {'input','textarea','select'} or 'name' not in attrs: return
        key = attrs['name']
        self.names.append(key)
        if 'readonly' in attrs: self.readonly.add(key)
        if tag == 'select':
            self.select = key
            self.values[key] = ''
            self.options[key] = []
        elif tag == 'textarea':
            self.textarea = key
            self.values[key] = ''
        elif attrs.get('type') != 'checkbox' or 'checked' in attrs:
            self.values[key] = attrs.get('value','')

    def handle_endtag(self, tag):
        if tag == 'form': self.active = False
        if tag == 'textarea': self.textarea = None
        if tag == 'select': self.select = None

    def handle_data(self, value):
        if self.textarea: self.values[self.textarea] += value


def test_deluxe_editable_fields_round_trip_and_identity_is_readonly(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    page = client.get(f'/characters/{character.id}')
    assert page.status_code == 200
    form = SheetForm(page.text)
    assert set(form.names) == set(FIELDS) | {'csrf','version'}
    assert len(form.names) == len(set(form.names))
    assert {'player','class_name','initiative.total','ac.total','ability.str.mod','skill.climb.total'} <= form.readonly
    assert not {'hp.current','ability.str.score','ability.str.temp_score','skill.climb.ranks','skill.climb.misc','money.gp'} & form.readonly
    assert form.options['alignment'] == ['',*ALIGNMENTS]
    for key,meta in FIELDS.items():
        if key in form.readonly: continue
        form.values[key] = 'CG' if key == 'alignment' else '1' if meta['kind'] == 'checkbox' else '3' if meta['kind'] == 'number' else f'Edited {key}'
    response = env.post(client,f'/characters/{character.id}/play-sheet',form.values)
    assert response.status_code == 303
    saved = SheetForm(client.get(response.headers['location']).text)
    assert all(saved.values[key] == value for key,value in form.values.items() if key not in saved.readonly | {'version'})
    assert saved.values['version'] == '2'
    assert saved.values['ability.str.mod'] == '-4'
    assert saved.values['initiative.total'] == '-1'
    assert saved.values['spell.1.known'] == '1'
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.owner_id == env.player.id and record.campaign_id is None
        assert db.scalar(select(AuditEvent).where(AuditEvent.event == 'character.play_sheet_saved'))
        assert len(record.play_data) > 400


def test_creation_values_seed_sheet_and_overrides_preserve_creation_snapshot(env):
    character = seed_character(env.player)
    data = fighter(defaults(env.player.id))
    computed = calculate(data,{})
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        record.name,record.level,record.class_name,record.ancestry = data['name'],1,'Fighter','Human'
        record.sheet_data = {'input':data,'computed':computed,'rolls':[]}
        db.commit()
    client = env.login(env.player)
    form = SheetForm(client.get(f'/characters/{character.id}').text)
    assert form.values['hp.total'] == str(computed['hp'])
    assert form.values['ability.str.score'] == str(computed['scores']['str'])
    assert form.values['skill.climb.total'] == str(computed['skill_totals']['climb'])
    assert 'Longsword' in form.values['weapon.0.name']
    assert form.values['gear.0.name']
    form.values.update({'hp.current':'2','resistance.0.energy':'10','resistance.0.type':'Fire','spell.1.used.0':'1','notes':'Play notes'})
    assert env.post(client,f'/characters/{character.id}/play-sheet',form.values).status_code == 303
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.sheet_data['computed'] == computed
        assert record.sheet_data['input']['notes'] == 'Play notes'
        assert record.play_data['hp.current'] == '2'
        assert 'hp.total' not in record.play_data
    form = SheetForm(client.get(f'/characters/{character.id}').text)
    form.values.pop('spell.1.used.0')
    form.values['resistance.0.type'] = ''
    assert env.post(client,f'/characters/{character.id}/play-sheet',form.values).status_code == 303
    saved = SheetForm(client.get(f'/characters/{character.id}').text)
    assert 'spell.1.used.0' not in saved.values
    assert saved.values['resistance.0.type'] == ''


@pytest.mark.parametrize('actor,allowed',[('player',True),('gm',True),('admin',True),('player2',False),('gm2',False)])
def test_sheet_uses_existing_character_access_rules(env,actor,allowed):
    campaign = seed_campaign(env.gm,members=[env.player])
    character = seed_character(env.player,campaign)
    client = env.login(getattr(env,actor))
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        values = sheet_values(record,db.get(User,record.owner_id),campaign,db.get(User,campaign.owner_id))
        values.update(version=str(record.version))
    response = env.post(client,f'/characters/{character.id}/play-sheet',{**values,'hp.current':'9'})
    assert response.status_code == (303 if allowed else 404)


def test_sheet_rejects_csrf_stale_invalid_and_incomplete_saves(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    values = SheetForm(client.get(f'/characters/{character.id}').text).values
    path = f'/characters/{character.id}/play-sheet'
    assert env.post(client,path,{**values,'csrf':'wrong'},use_csrf=False).status_code == 403
    assert env.post(client,path,{**values,'version':'99'}).status_code == 409
    for changes in [{'alignment':'invalid'},{'level':'41'},{'hp.current':'NaN'},{'hp.current':'1e9999999'},{'skill.climb.ranks':'-1'},{'ancestry':'x'*101},{'notes':'x'*10001}]:
        response = env.post(client,path,{**values,'homeland':'Preserved entry',**changes})
        assert response.status_code == 422
        assert 'Preserved entry' in response.text and 'Check these fields' in response.text
    assert env.post(client,path,{'version':'1','name':'Incomplete'}).status_code == 422
    assert env.post(client,path,{**values,'owner_id':str(env.player2.id)}).status_code == 422
    assert env.post(client,path,{**values,'level':'3.0','notes':'<script>alert(1)</script>'}).status_code == 303
    html = client.get(f'/characters/{character.id}').text
    assert '<script>alert(1)</script>' not in html and '&lt;script&gt;' in html
    assert env.post(client,path,values).status_code == 409


def test_deluxe_migration_adds_column_idempotently_without_replacing_creation_data(env,isolated_database):
    from pathkeeper.migrations import migrate
    character = seed_character(env.player)
    with isolated_database.begin() as connection:
        connection.execute(text('ALTER TABLE characters DROP COLUMN play_data'))
        for version in range(1,5):
            connection.execute(SchemaMigration.__table__.insert().values(version=version,name='existing'))
    migrate(isolated_database)
    migrate(isolated_database)
    assert 'play_data' in {column['name'] for column in inspect(isolated_database).get_columns('characters')}
    with Session(engine()) as db:
        assert db.get(Character,character.id).name == character.name
        assert db.get(SchemaMigration,5)


def test_locked_identity_ignores_forged_values_and_alignment_choices_persist(env):
    character = seed_character(env.player)
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        record.play_data = {'player':'Obsolete player label','alignment':'Chaotic good'}
        db.commit()
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    form = SheetForm(client.get(path).text)
    assert form.values['player'] == 'Test Player'
    assert form.values['alignment'] == 'CG'
    for alignment in ALIGNMENTS:
        form.values.update(player='Forged player',class_name='Wizard',alignment=alignment)
        assert env.post(client,path+'/play-sheet',form.values).status_code == 303
        form = SheetForm(client.get(path).text)
        assert form.values['player'] == 'Test Player'
        assert form.values['class_name'] == character.class_name
        assert form.values['alignment'] == alignment
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.owner_id == env.player.id
        assert record.class_name == character.class_name
        assert 'player' not in record.play_data


def test_calculated_fields_ignore_forgery_and_follow_editable_inputs(env):
    character = seed_character(env.player)
    data = fighter(defaults(env.player.id))
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        record.class_name,record.level = 'Fighter',1
        record.sheet_data = {'input':data,'computed':calculate(data,{}),'rolls':[]}
        db.commit()
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    form = SheetForm(client.get(path).text)
    assert {'hp.total','bab','save.fortitude.base','skill_points.base'} <= form.readonly
    values = dict(form.values)
    for key in form.readonly: values[key] = '999999'
    values.update({'ability.str.score':'18','ability.dex.temp_score':'16',
                   'initiative.misc':'4','skill.climb.ranks':'2','skill.climb.misc':'1',
                   'skill.perception.ranks':'2','skill.perception.misc':'1',
                   'ac.armor':'4','ac.shield':'2','ac.dex':'3','ac.dodge':'1','ac.misc':'0',
                   'save.reflex.magic':'2','save.reflex.misc':'1','hp.current':'7','ability.con.temp_score':'14',
                   'spell.2.list':'Scorching ray\n\nMirror image'})
    assert env.post(client,path+'/play-sheet',values).status_code == 303
    saved = SheetForm(client.get(path).text)
    assert saved.values['hp.total'] == str(int(form.values['hp.total'])+2)
    assert saved.values['bab'] == form.values['bab']
    assert saved.values['hp.current'] == '7'
    assert saved.values['ability.str.mod'] == '4'
    assert saved.values['ability.dex.temp_mod'] == '3'
    assert saved.values['initiative.total'] == '7'
    assert saved.values['skill.climb.total'] == '10'  # 4 STR + 2 ranks + 3 class + 1 misc
    assert saved.values['skill.perception.total'] == '3'  # no class bonus
    assert saved.values['save.reflex.total'] == '6'
    assert saved.values['ac.total'] == '20'
    assert saved.values['ac.touch'] == '14'
    assert saved.values['ac.flat'] == '16'
    assert saved.values['spell.2.known'] == '2'
    assert '999999' not in [saved.values[key] for key in saved.readonly]


def test_calculations_preserve_manual_progression_and_negative_modifiers(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    form = SheetForm(client.get(path).text)
    assert not {'hp.total','bab','save.will.base','skill_points.base'} & form.readonly
    form.values.update({'ability.dex.score':'7','ability.str.score':'9','size':'Small',
                        'bab':'3','save.will.base':'3','ability.wis.score':'12',
                        'skill_points.base':'2','ability.int.score':'6','skill_points.misc':'1',
                        'ac.armor':'2','ac.dex':'-2','ac.dodge':'1','ac.misc':'0'})
    assert env.post(client,path+'/play-sheet',form.values).status_code == 303
    saved = SheetForm(client.get(path).text)
    assert saved.values['ability.dex.mod'] == '-2'
    assert saved.values['ability.str.mod'] == '-1'
    assert saved.values['skill_points.total'] == '2'  # minimum 1 + misc 1
    assert saved.values['save.will.total'] == '4'
    assert saved.values['cmb.size'] == '-1' and saved.values['ac.size'] == '1'
    assert saved.values['ac.flat'] == '11'  # negative DEX remains, dodge is excluded


def test_existing_dodge_bonus_is_separated_once_and_survives_repeated_saves(env):
    character = seed_character(env.player)
    data = fighter(defaults(env.player.id))
    data['feats'] = [{'name':'Dodge'},{'name':'Toughness'}]
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        record.class_name,record.level = 'Fighter',1
        record.sheet_data = {'input':data,'computed':calculate(data,{}),'rolls':[]}
        record.play_data = {'ac.misc':'3'}  # Dodge + two other points on the old sheet
        db.commit()
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    for _ in range(3):
        form = SheetForm(client.get(path).text)
        assert form.values['ac.dodge'] == '1'
        assert form.values['ac.misc'] in {'2','2.0'}
        assert form.values['ac.total'] == '17'
        assert form.values['ac.flat'] == '16'
        assert env.post(client,path+'/play-sheet',form.values).status_code == 303

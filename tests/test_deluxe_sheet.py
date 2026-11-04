from html.parser import HTMLParser

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from pathkeeper.character_rules import calculate, defaults
from pathkeeper.database import engine
from pathkeeper.deluxe_sheet import FIELDS, baseline, sheet_values
from pathkeeper.models import AuditEvent, Character, SchemaMigration, User
from .test_character_wizard import fighter
from .test_workspace import seed_campaign, seed_character


class SheetForm(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.active = False
        self.values = {}
        self.names = []
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'form': self.active = attrs.get('id') == 'deluxe-form'
        if not self.active or tag not in {'input','textarea'} or 'name' not in attrs: return
        key = attrs['name']
        self.names.append(key)
        if tag == 'textarea':
            self.textarea = key
            self.values[key] = ''
        elif attrs.get('type') != 'checkbox' or 'checked' in attrs:
            self.values[key] = attrs.get('value','')

    def handle_endtag(self, tag):
        if tag == 'form': self.active = False
        if tag == 'textarea': self.textarea = None

    def handle_data(self, value):
        if self.textarea: self.values[self.textarea] += value


def test_every_deluxe_field_is_editable_and_round_trips(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    page = client.get(f'/characters/{character.id}')
    assert page.status_code == 200
    form = SheetForm(page.text)
    assert set(form.names) == set(FIELDS) | {'csrf','version'}
    assert len(form.names) == len(set(form.names))
    for key,meta in FIELDS.items():
        form.values[key] = '1' if meta['kind'] == 'checkbox' else '3' if meta['kind'] == 'number' else f'Edited {key}'
    response = env.post(client,f'/characters/{character.id}/play-sheet',form.values)
    assert response.status_code == 303
    saved = SheetForm(client.get(response.headers['location']).text)
    assert saved.values == {**form.values,'version':'2'}
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.owner_id == env.player.id and record.campaign_id is None
        assert db.scalar(select(AuditEvent).where(AuditEvent.event == 'character.play_sheet_saved'))
        assert len(record.play_data) > 600


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
    for changes in [{'level':'41'},{'hp.current':'NaN'},{'hp.current':'1e9999999'},{'skill.climb.ranks':'-1'},{'ancestry':'x'*101},{'notes':'x'*10001}]:
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

from io import BytesIO

from PIL import Image
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character, SchemaMigration
from pathkeeper.portraits import DEFAULT_HEADER_BACKGROUND
from .test_deluxe_sheet import SheetForm, autosave
from .test_portraits import picture, upload
from .test_workspace import seed_campaign, seed_character


@pytest.mark.parametrize('actor,status',[('player',200),('gm',403),('admin',403),('player2',404),('gm2',404)])
def test_only_owner_can_change_header_background(env,actor,status):
    campaign = seed_campaign(env.gm,members=[env.player])
    character = seed_character(env.player,campaign)
    client = env.login(getattr(env,actor))
    path = f'/characters/{character.id}'
    page = client.get(path)
    if actor in {'player','gm','admin'}:
        assert page.status_code == 200
        assert DEFAULT_HEADER_BACKGROUND in page.text
        assert ('Choose header background' in page.text) == (actor == 'player')
    assert upload(env,client,path+'/header-background').status_code == status
    assert env.post(client,path+'/header-background/remove').status_code == status


def test_custom_background_is_private_independent_and_can_reset_to_default(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    values = SheetForm(client.get(path).text).values
    background = path+'/header-background'
    assert client.get(background).headers['location'] == DEFAULT_HEADER_BACKGROUND
    assert upload(env,client,background,use_csrf=False).status_code == 403
    response = upload(env,client,background,picture(size=(1800,1000)))
    assert response.status_code == 200 and response.json()['custom']
    saved = client.get(response.json()['url'])
    assert saved.status_code == 200 and 'no-store' in saved.headers['cache-control']
    with Image.open(BytesIO(saved.content)) as image:
        assert image.width == 1600 and image.height < 1600
    assert env.login(env.player2).get(background).status_code == 404
    assert upload(env,client,background,b'<svg/>').status_code == 422
    assert client.get(background).content == saved.content
    values['notes'] = 'A text edit alongside the background'
    assert autosave(client,path,values).status_code == 200
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.header_background == saved.content and record.portrait is None
        assert record.notes == values['notes']
    assert env.post(client,background+'/remove',use_csrf=False).status_code == 403
    reset = env.post(client,background+'/remove')
    assert reset.status_code == 200 and not reset.json()['custom']
    assert reset.json()['url'] == DEFAULT_HEADER_BACKGROUND
    assert DEFAULT_HEADER_BACKGROUND in client.get(path).text


def test_header_background_migration_is_additive_and_idempotent(env,isolated_database):
    from pathkeeper.migrations import migrate
    character = seed_character(env.player)
    with isolated_database.begin() as connection:
        connection.execute(text('ALTER TABLE characters DROP COLUMN header_background'))
        for version in range(1,8):
            connection.execute(SchemaMigration.__table__.insert().values(version=version,name='existing'))
    migrate(isolated_database)
    migrate(isolated_database)
    assert 'header_background' in {column['name'] for column in inspect(isolated_database).get_columns('characters')}
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.name == character.name and record.header_background is None
        assert db.get(SchemaMigration,8)

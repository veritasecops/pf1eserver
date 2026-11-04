from io import BytesIO

from PIL import Image
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character, CharacterDraft, SchemaMigration
from pathkeeper.portraits import MAX_UPLOAD
from .test_character_wizard import fighter, finish, save, start
from .test_deluxe_sheet import SheetForm, autosave
from .test_workspace import seed_campaign, seed_character


def picture(color='navy',size=(90,120)):
    output = BytesIO()
    image = Image.new('RGBA',size,color)
    image.save(output,format='PNG')
    return output.getvalue()


def upload(env,client,path,content=None,use_csrf=True):
    return client.post(path,data={'csrf':env.csrf(client)} if use_csrf else {},
                       files={'portrait':('picture.png',content if content is not None else picture(),'image/png')})


@pytest.mark.parametrize('actor,allowed',[('player',True),('gm',True),('admin',True),('player2',False),('gm2',False)])
def test_portraits_follow_character_permissions(env,actor,allowed):
    campaign = seed_campaign(env.gm,members=[env.player])
    character = seed_character(env.player,campaign)
    client = env.login(getattr(env,actor))
    path = f'/characters/{character.id}/portrait'
    response = upload(env,client,path)
    assert response.status_code == (200 if allowed else 404)
    if allowed:
        saved = client.get(response.json()['url'])
        assert saved.status_code == 200 and saved.headers['content-type'] == 'image/jpeg'
        assert 'no-store' in saved.headers['cache-control']
        with Image.open(BytesIO(saved.content)) as image:
            assert image.mode == 'RGB' and image.size == (90,120)
        assert env.post(client,path+'/remove').status_code == 200
        assert client.get(path).status_code == 404


def test_portrait_validation_resizing_and_text_autosave_are_independent(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    values = SheetForm(client.get(path).text).values
    assert upload(env,client,path+'/portrait',use_csrf=False).status_code == 403
    assert upload(env,client,path+'/portrait',b'<svg><script>alert(1)</script></svg>').status_code == 422
    assert upload(env,client,path+'/portrait',b'x'*(MAX_UPLOAD+1)).status_code == 413
    assert upload(env,client,path+'/portrait',picture(size=(5000,5000))).status_code == 422
    response = upload(env,client,path+'/portrait',picture(size=(1200,1600)))
    assert response.status_code == 200
    with Image.open(BytesIO(client.get(response.json()['url']).content)) as image:
        assert image.size == (576,768)
        assert not image.getexif()
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.version == character.version
        before = record.portrait
    values['notes'] = 'Concurrent text edit'
    assert autosave(client,path,values).status_code == 200
    with Session(engine()) as db:
        record = db.get(Character,character.id)
        assert record.notes == 'Concurrent text edit' and record.portrait == before
    assert client.get(path+'/portrait').status_code == 200
    assert env.post(client,path+'/portrait/remove').status_code == 200


def test_draft_portrait_is_private_and_carried_to_completed_character(env):
    client,draft_id,version,data = start(env)
    path = f'/api/character-drafts/{draft_id}/portrait'
    assert upload(env,client,path).status_code == 200
    assert client.get(path).status_code == 200
    for actor in (env.player2,env.admin):
        other = env.login(actor)
        assert other.get(path).status_code == 404
        assert upload(env,other,path).status_code == 404
    saved = save(env,client,draft_id,version,fighter(data))
    assert saved.status_code == 200
    completed = finish(env,client,draft_id,saved.json()['version'])
    assert completed.status_code == 200
    character_path = completed.json()['location']
    assert client.get(character_path+'/portrait').status_code == 200
    assert client.get(path).status_code == 200
    assert upload(env,client,path).status_code == 409
    with Session(engine()) as db:
        assert db.get(CharacterDraft,draft_id).portrait is None
        assert db.get(Character,int(character_path.rsplit('/',1)[1])).portrait


def test_editing_wizard_keeps_new_sheet_portrait_unless_draft_image_changed(env):
    client,draft_id,version,data = start(env)
    saved = save(env,client,draft_id,version,fighter(data))
    completed = finish(env,client,draft_id,saved.json()['version'])
    path = completed.json()['location']
    assert upload(env,client,path+'/portrait').status_code == 200
    assert client.get(path+'/sheet/edit').status_code == 200
    with Session(engine()) as db:
        draft = db.scalar(select(CharacterDraft).where(CharacterDraft.mode == 'edit'))
        editing_id,editing_version = draft.id,draft.version
        assert draft.portrait and not draft.portrait_changed
    assert upload(env,client,path+'/portrait',picture('green')).status_code == 200
    new_image = client.get(path+'/portrait').content
    assert finish(env,client,editing_id,editing_version).status_code == 200
    assert client.get(path+'/portrait').content == new_image
    assert client.get(path+'/sheet/edit').status_code == 200
    with Session(engine()) as db:
        draft = db.scalar(select(CharacterDraft).where(CharacterDraft.mode == 'edit',CharacterDraft.finalized_at.is_(None)))
        editing_id,editing_version = draft.id,draft.version
    assert upload(env,client,f'/api/character-drafts/{editing_id}/portrait',picture('red')).status_code == 200
    assert finish(env,client,editing_id,editing_version).status_code == 200
    assert client.get(path+'/portrait').content != new_image


def test_portrait_migration_adds_columns_idempotently(env,isolated_database):
    from pathkeeper.migrations import migrate
    character = seed_character(env.player)
    with isolated_database.begin() as connection:
        connection.execute(text('ALTER TABLE characters DROP COLUMN portrait'))
        connection.execute(text('ALTER TABLE character_drafts DROP COLUMN portrait, DROP COLUMN portrait_changed'))
        for version in range(1,7):
            connection.execute(SchemaMigration.__table__.insert().values(version=version,name='existing'))
    migrate(isolated_database)
    migrate(isolated_database)
    assert 'portrait' in {column['name'] for column in inspect(isolated_database).get_columns('characters')}
    assert {'portrait','portrait_changed'} <= {column['name'] for column in inspect(isolated_database).get_columns('character_drafts')}
    with Session(engine()) as db:
        assert db.get(Character,character.id).portrait is None
        assert db.get(SchemaMigration,7)

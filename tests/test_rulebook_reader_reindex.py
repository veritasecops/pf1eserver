from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper import rulebooks
from pathkeeper.database import engine
from pathkeeper.models import Rulebook, RulebookIndex
from .test_rulebooks import sample_pdf, upload


def test_reader_reindex_is_admin_only_and_returns_to_current_page(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rulebooks, 'storage_root', lambda: tmp_path)
    admin, gm, player = (env.login(user) for user in (env.admin, env.gm, env.player))
    assert upload(env, admin, 'Reader reindex test', ['admin', 'gm', 'player'], sample_pdf()).status_code == 303
    with Session(engine()) as db:
        key = db.scalar(select(Rulebook.id))
        db.get(RulebookIndex, key).status = 'ready'
        db.commit()
    reader, action = f'/rulebooks/{key}/read?page=2', f'/rulebooks/{key}/reindex'
    page = admin.get(reader)
    assert page.status_code == 200
    assert f'action="{action}"' in page.text
    assert 'name="reader_page" value="2"' in page.text
    assert 'name="force_ocr"' in page.text
    form = {'reader_page': '2', 'force_ocr': 'on'}
    for client in (gm, player):
        assert client.get(reader).status_code == 200
        assert f'action="{action}"' not in client.get(reader).text
        assert env.post(client, action, form).status_code == 403
    assert env.post(admin, action, form, use_csrf=False).status_code == 403
    assert env.post(admin, action, {'reader_page': '//example.com'}).status_code == 422
    with Session(engine()) as db:
        assert db.get(RulebookIndex, key).status == 'ready'
    response = env.post(admin, action, form)
    assert response.status_code == 303 and response.headers['location'] == reader
    with Session(engine()) as db:
        job = db.get(RulebookIndex, key)
        assert job.status == 'queued' and job.force_ocr
        job.status = 'indexing'
        db.commit()
    page = admin.get(reader)
    assert 'disabled>Reindex</button>' in page.text
    assert env.post(admin, action, form).status_code == 409
    with Session(engine()) as db:
        db.get(RulebookIndex, key).status = 'partial'
        db.commit()
    assert 'Retry indexing</button>' in admin.get(reader).text
    response = env.post(admin, action)
    assert response.status_code == 303 and response.headers['location'] == '/rulebooks/upload'

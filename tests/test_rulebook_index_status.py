from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Rulebook, RulebookIndex


def test_library_progress_is_visible_until_ready_and_status_api_enforces_roles(env):
    shared, admin_only, legacy = '1' * 32, '2' * 32, '3' * 32
    with Session(engine()) as db:
        db.add_all([
            Rulebook(id=shared, title='Shared progress', access_mask=7, category='core'),
            Rulebook(id=admin_only, title='Private progress', access_mask=4, category='core'),
            Rulebook(id=legacy, title='Awaiting index', access_mask=7, category='core'),
        ])
        db.flush()
        db.add_all([
            RulebookIndex(book_id=shared, generation='a' * 32, status='indexing', completed_pages=12, total_pages=100),
            RulebookIndex(book_id=admin_only, generation='b' * 32, status='queued'),
        ])
        db.commit()
    query = [('book', shared), ('book', admin_only), ('book', legacy)]
    assert env.client().get('/rulebooks/index-status', params=query).status_code == 303
    for user in (env.admin, env.gm, env.player):
        client = env.login(user)
        page = client.get('/rulebooks')
        assert 'Search index · Indexing · 12 / 100 pages' in page.text
        assert 'Search index · Queued' in page.text
        assert '/static/rulebook-index-status.js?v=1' in page.text
        response = client.get('/rulebooks/index-status', params=query)
        assert response.status_code == 200
        assert response.json()[shared] == {'status': 'indexing', 'text': 'Search index · Indexing · 12 / 100 pages'}
        assert (admin_only in response.json()) == (user.role == 'admin')
        assert response.json()[legacy]['status'] == 'queued'
    admin = env.login(env.admin)
    with Session(engine()) as db:
        db.get(RulebookIndex, shared).status = 'ready'
        db.get(RulebookIndex, admin_only).status = 'partial'
        db.get(RulebookIndex, admin_only).failed_pages = 2
        db.commit()
    page = admin.get('/rulebooks')
    assert f'data-rulebook-index="{shared}" data-index-active="false" role="status" hidden></p>' in page.text
    assert 'Search index · Partial · 2 incomplete' in page.text
    assert 'Search index · Ready' not in page.text
    assert admin.get('/rulebooks/index-status', params=query).json()[shared]['status'] == 'ready'
    assert admin.get('/rulebooks/index-status', params={'book': '../private'}).status_code == 422
    assert admin.get('/rulebooks/index-status', params=[('book', shared)] * 101).status_code == 422
    with Session(engine()) as db:
        db.get(Rulebook, shared).access_mask = 4
        db.commit()
    assert shared not in env.login(env.player).get('/rulebooks/index-status', params=query).json()

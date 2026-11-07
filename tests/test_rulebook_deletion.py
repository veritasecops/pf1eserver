from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper import rulebook_indexer as indexer, rulebooks
from pathkeeper.database import engine
from pathkeeper.models import Rulebook, RulebookDeletion, RulebookIndex, RulebookPage, utcnow
from .test_rulebook_search import mixed_pdf
from .test_rulebooks import upload


def create_book(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rulebooks, "storage_root", lambda: tmp_path / "rulebooks")
    monkeypatch.setattr(indexer, "settings", lambda: SimpleNamespace(storage=tmp_path))
    admin = env.login(env.admin)
    assert upload(env, admin, "Delete handbook", ["admin", "player"], mixed_pdf()).status_code == 303
    with Session(engine()) as db:
        key = db.scalar(select(Rulebook.id))
    return admin, key


def test_admin_deletes_files_index_jobs_and_search_results(env, monkeypatch, tmp_path):
    admin, key = create_book(env, monkeypatch, tmp_path)
    monkeypatch.setattr(indexer, "extract_page", lambda *args: ("deletionsearchtoken", "native", ""))
    assert indexer.process_one()
    assert "matching pages" in admin.get("/rulebooks/search", params={"q": "deletionsearchtoken"}).text
    assert f'aria-label="Delete Delete handbook"' in admin.get("/rulebooks").text
    path = f"/rulebooks/{key}/delete"
    player = env.login(env.player)
    assert "Delete PDF" not in player.get("/rulebooks").text
    assert player.get(path).status_code == 403
    assert env.post(player, path, {"confirm": "delete"}).status_code == 403
    assert env.post(admin, path, {"confirm": "delete"}, use_csrf=False).status_code == 403
    assert env.post(admin, path).status_code == 422
    assert admin.get(path).status_code == 200
    deleted = env.post(admin, path, {"confirm": "delete"})
    assert deleted.status_code == 303
    assert not (tmp_path / "rulebooks" / key).exists()
    with Session(engine()) as db:
        assert db.get(Rulebook, key) is None
        assert db.get(RulebookIndex, key) is None
        assert db.get(RulebookDeletion, key) is None
        assert db.scalar(select(RulebookPage)) is None
    for suffix in ("read", "cover", "pdf", "pages/1"):
        assert player.get(f"/rulebooks/{key}/{suffix}").status_code == 404
    assert "0 matching pages" in player.get("/rulebooks/search", params={"q": "deletionsearchtoken"}).text
    assert env.post(admin, path, {"confirm": "delete"}).status_code == 404
    assert not indexer.process_one()


def test_deletion_during_extraction_cannot_recreate_index(env, monkeypatch, tmp_path):
    admin, key = create_book(env, monkeypatch, tmp_path)
    deleted = []
    def extract(pdf, page, force):
        if page == 1:
            deleted.append(env.post(admin, f"/rulebooks/{key}/delete", {"confirm": "delete"}).status_code)
        return "Worker finished after deletion", "native", ""
    monkeypatch.setattr(indexer, "extract_page", extract)
    assert indexer.process_one()
    assert deleted == [303]
    with Session(engine()) as db:
        assert db.get(Rulebook, key) is None and db.get(RulebookIndex, key) is None
        assert db.scalar(select(RulebookPage)) is None
    assert not (tmp_path / "rulebooks" / key).exists()


def test_file_cleanup_failure_is_durable_and_worker_retries(env, monkeypatch, tmp_path):
    admin, key = create_book(env, monkeypatch, tmp_path)
    with monkeypatch.context() as patch:
        def fail_cleanup(*args, **kwargs):
            raise PermissionError("Temporary filesystem failure")
        patch.setattr(indexer.shutil, "rmtree", fail_cleanup)
        deleted = env.post(admin, f"/rulebooks/{key}/delete", {"confirm": "delete"})
        assert deleted.status_code == 303
    assert (tmp_path / "rulebooks" / key / "book.pdf").is_file()
    with Session(engine()) as db:
        assert db.get(Rulebook, key) is None
        deletion = db.get(RulebookDeletion, key)
        assert deletion is not None
        deletion.retry_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert indexer.cleanup_one()
    assert not (tmp_path / "rulebooks" / key).exists()
    with Session(engine()) as db:
        assert db.get(RulebookDeletion, key) is None


def test_failed_database_commit_keeps_source_files_and_rulebook(env, monkeypatch, tmp_path):
    admin, key = create_book(env, monkeypatch, tmp_path)
    def fail_commit(db):
        raise HTTPException(409, "Synthetic transaction failure")
    monkeypatch.setattr(rulebooks, "commit", fail_commit)
    assert env.post(admin, f"/rulebooks/{key}/delete", {"confirm": "delete"}).status_code == 409
    assert (tmp_path / "rulebooks" / key / "book.pdf").is_file()
    with Session(engine()) as db:
        assert db.get(Rulebook, key) is not None and db.get(RulebookIndex, key) is not None
        assert db.get(RulebookDeletion, key) is None

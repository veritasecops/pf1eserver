from io import BytesIO
from os import urandom

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper import rulebooks
from pathkeeper.database import engine
from pathkeeper.models import Rulebook


def sample_pdf():
    output = BytesIO()
    cover = Image.new("RGB", (240, 320), (180, 50, 40))
    second_page = Image.frombytes("RGB", (900, 900), urandom(900 * 900 * 3))
    cover.save(output, format="PDF", save_all=True, append_images=[second_page])
    return output.getvalue()


def upload(env, client, title, role, data, filename="rulebook.pdf", csrf=True):
    return client.post(
        "/rulebooks/upload",
        data={"csrf": env.csrf(client) if csrf else "", "title": title, "access_role": role},
        files={"pdf": (filename, data, "application/pdf")},
    )


def test_rulebook_upload_and_role_scoped_library_and_files(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rulebooks, "storage_root", lambda: tmp_path)
    clients = {role: env.login(user) for role, user in
               (("admin", env.admin), ("gm", env.gm), ("player", env.player))}
    assert env.client().get("/rulebooks").headers["location"] == "/login"
    for role in ("gm", "player"):
        assert clients[role].get("/rulebooks/upload").status_code == 403
        assert upload(env, clients[role], "Forbidden", role, b"%PDF-").status_code == 403
        assert "Upload PDF" not in clients[role].get("/rulebooks").text

    admin = clients["admin"]
    assert "Upload PDF" in admin.get("/rulebooks").text
    data = sample_pdf()
    assert len(data) > 256 * 1024
    for role in clients:
        result = upload(env, admin, f"Book for {role}", role, data)
        assert result.status_code == 303, result.text

    with Session(engine()) as db:
        ids = dict(db.execute(select(Rulebook.access_role, Rulebook.id)).all())
    for role, client in clients.items():
        page = client.get("/rulebooks")
        assert page.status_code == 200
        for audience, key in ids.items():
            pdf_path, cover_path = f"/rulebooks/{key}/pdf", f"/rulebooks/{key}/cover"
            if audience != role:
                assert key not in page.text and f"Book for {audience}" not in page.text
                assert client.get(pdf_path, headers={"Range": "bytes=0-4"}).status_code == 404
                assert client.head(cover_path).status_code == 404
                continue
            assert pdf_path in page.text and cover_path in page.text and f"Book for {audience}" in page.text
            pdf = client.get(pdf_path)
            assert pdf.status_code == 200 and pdf.content == data
            assert pdf.headers["content-type"] == "application/pdf"
            assert pdf.headers["content-disposition"].startswith("inline")
            assert pdf.headers["cache-control"] == "no-store"
            part = client.get(pdf_path, headers={"Range": "bytes=0-4"})
            assert part.status_code == 206 and part.content == b"%PDF-"
            cover = client.get(cover_path)
            assert cover.status_code == 200 and cover.headers["content-type"] == "image/png"
            with Image.open(BytesIO(cover.content)) as image:
                assert max(image.size) == 420
                red, green, blue = image.getpixel((image.width // 2, image.height // 2))
                assert red > green + 80 and red > blue + 80


def test_invalid_rulebook_uploads_leave_no_files_or_records(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rulebooks, "storage_root", lambda: tmp_path)
    admin = env.login(env.admin)
    assert upload(env, admin, "Invalid role", "anyone", b"%PDF-").status_code == 422
    assert upload(env, admin, "Invalid type", "player", b"<html>").status_code == 422
    assert upload(env, admin, "Broken PDF", "player", b"%PDF-1.7\ninvalid").status_code == 422
    assert upload(env, admin, "Invalid extension", "gm", b"%PDF-", filename="bad.html").status_code == 422
    assert upload(env, admin, "Invalid CSRF", "admin", b"%PDF-", csrf=False).status_code == 403
    monkeypatch.setattr(rulebooks, "MAX_PDF", 10)
    assert upload(env, admin, "Oversized PDF", "admin", b"%PDF-" + b"x" * 20).status_code == 413
    assert not list(tmp_path.iterdir())
    with Session(engine()) as db:
        assert db.scalar(select(Rulebook)) is None

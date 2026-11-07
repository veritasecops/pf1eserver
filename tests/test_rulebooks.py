from io import BytesIO
from os import urandom

from PIL import Image
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from pathkeeper import rulebooks
from pathkeeper.database import engine
from pathkeeper.migrations import migrate
from pathkeeper.models import RULEBOOK_ROLE_BITS, Rulebook


def sample_pdf():
    output = BytesIO()
    cover = Image.new("RGB", (240, 320), (180, 50, 40))
    second_page = Image.frombytes("RGB", (900, 900), urandom(900 * 900 * 3))
    cover.save(output, format="PDF", save_all=True, append_images=[second_page])
    return output.getvalue()


def upload(env, client, title, role, data, filename="rulebook.pdf", csrf=True, category="core", return_to=""):
    return client.post(
        "/rulebooks/upload",
        data={"csrf": env.csrf(client) if csrf else "", "title": title, "access_role": role,
              "category": category, "return_to": return_to},
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
    admin_library = admin.get("/rulebooks").text
    assert 'data-open-dialog="rulebook-upload-dialog"' in admin_library
    assert 'data-rulebook-drop' in admin_library and 'name="return_to" value="library"' in admin_library
    data = sample_pdf()
    assert len(data) > 256 * 1024
    for role in clients:
        result = upload(env, admin, f"Book for {role}", role, data)
        assert result.status_code == 303, result.text
    assert upload(env, admin, "Shared book", ["admin", "player"], data, category="expanded").status_code == 303
    modal_upload = upload(env, admin, "All roles book", list(clients), data, return_to="library")
    assert modal_upload.status_code == 303 and modal_upload.headers["location"] == "/rulebooks"

    with Session(engine()) as db:
        books = db.scalars(select(Rulebook)).all()
    assert {book.title: book.access_mask for book in books} == {
        **{f"Book for {role}": bit for role, bit in RULEBOOK_ROLE_BITS.items()},
        "Shared book": RULEBOOK_ROLE_BITS["admin"] | RULEBOOK_ROLE_BITS["player"],
        "All roles book": sum(RULEBOOK_ROLE_BITS.values()),
    }
    for role, client in clients.items():
        page = client.get("/rulebooks")
        assert page.status_code == 200
        for book in books:
            key = book.id
            pdf_path, cover_path = f"/rulebooks/{key}/pdf", f"/rulebooks/{key}/cover"
            reader_path, image_path = f"/rulebooks/{key}/read", f"/rulebooks/{key}/pages/1"
            if not book.access_mask & RULEBOOK_ROLE_BITS[role]:
                assert key not in page.text and book.title not in page.text
                assert client.get(pdf_path, headers={"Range": "bytes=0-4"}).status_code == 404
                assert client.head(cover_path).status_code == 404
                assert client.get(reader_path).status_code == 404
                assert client.get(image_path).status_code == 404
                continue
            assert reader_path in page.text and cover_path in page.text and book.title in page.text
            assert pdf_path not in page.text
            pdf = client.get(pdf_path)
            assert pdf.status_code == 303 and pdf.headers["location"] == reader_path
            assert not pdf.content.startswith(b"%PDF-")
            assert pdf.headers["cache-control"] == "no-store"
            part = client.get(pdf_path, headers={"Range": "bytes=0-4"})
            assert part.status_code == 303 and not part.content.startswith(b"%PDF-")
            reader = client.get(reader_path)
            assert reader.status_code == 200 and image_path in reader.text
            assert 'of 2' in reader.text and '?page=2' in reader.text
            image_response = client.get(image_path)
            assert image_response.status_code == 200 and image_response.headers["content-type"] == "image/png"
            assert image_response.headers["cache-control"] == "no-store"
            assert client.get(reader_path, params={"page": 3}).status_code == 404
            assert client.get(f"/rulebooks/{key}/pages/0").status_code == 404
            assert client.get(f"/rulebooks/{key}/pages/3").status_code == 404
            cover = client.get(cover_path)
            assert cover.status_code == 200 and cover.headers["content-type"] == "image/png"
            with Image.open(BytesIO(cover.content)) as image:
                assert max(image.size) == 420
                red, green, blue = image.getpixel((image.width // 2, image.height // 2))
                assert red > green + 80 and red > blue + 80

    shared = next(book for book in books if book.title == "Shared book")
    second_page = admin.get(f"/rulebooks/{shared.id}/pages/2")
    assert second_page.status_code == 200 and second_page.content.startswith(b"\x89PNG")
    path = f"/rulebooks/{shared.id}/access"
    filters = {"category": "expanded"}
    assert "Shared book" in admin.get("/rulebooks", params=filters).text
    assert "Shared book" not in clients["gm"].get("/rulebooks", params=filters).text
    assert "Book for admin" not in admin.get("/rulebooks", params=filters).text
    change = {"previous_mask": shared.access_mask, "access_role": ["gm", "player"],
              "previous_category": "expanded", "category": "third-party"}
    assert "Shared book" in admin.get("/rulebooks/upload").text
    assert env.post(clients["player"], path, change).status_code == 403
    assert env.post(admin, path, {"previous_mask": shared.access_mask, "previous_category": "expanded"}).status_code == 422
    assert env.post(admin, path, change).status_code == 303
    assert env.post(admin, path, change).status_code == 409
    assert admin.get(f"/rulebooks/{shared.id}/pdf").status_code == 404
    assert clients["gm"].get(f"/rulebooks/{shared.id}/cover").status_code == 200
    assert "Shared book" not in clients["gm"].get("/rulebooks", params=filters).text
    assert "Shared book" in clients["gm"].get("/rulebooks", params={"category": "third-party"}).text


def test_invalid_rulebook_uploads_leave_no_files_or_records(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rulebooks, "storage_root", lambda: tmp_path)
    admin = env.login(env.admin)
    assert rulebooks.MAX_PDF == 500 * 1024 * 1024
    assert rulebooks.MAX_REQUEST == rulebooks.MAX_PDF + 64 * 1024
    assert 'Up to 500 MB.' in admin.get('/rulebooks/upload').text
    assert admin.post('/rulebooks/upload', content=b'', headers={
        'content-length': str(rulebooks.MAX_REQUEST + 1),
    }).status_code == 413
    assert upload(env, admin, "No category", "admin", b"%PDF-", category="").status_code == 422
    assert upload(env, admin, "Invalid category", "admin", b"%PDF-", category="unknown").status_code == 422
    assert upload(env, admin, "No role", [], b"%PDF-").status_code == 422
    assert upload(env, admin, "Invalid role", "anyone", b"%PDF-").status_code == 422
    assert upload(env, admin, "Invalid type", "player", b"<html>").status_code == 422
    invalid_modal = upload(env, admin, "Broken PDF", "player", b"%PDF-1.7\ninvalid", return_to="library")
    assert invalid_modal.status_code == 422 and 'name="return_to" value="library"' in invalid_modal.text
    assert 'name="title" value="Broken PDF"' in invalid_modal.text
    assert upload(env, admin, "Invalid extension", "gm", b"%PDF-", filename="bad.html").status_code == 422
    assert upload(env, admin, "Invalid CSRF", "admin", b"%PDF-", csrf=False).status_code == 403
    monkeypatch.setattr(rulebooks, "MAX_PDF", 10)
    assert upload(env, admin, "Oversized PDF", "admin", b"%PDF-" + b"x" * 20).status_code == 413
    assert not list(tmp_path.iterdir())
    with Session(engine()) as db:
        assert db.scalar(select(Rulebook)) is None


def test_migration_preserves_each_existing_rulebook_role(isolated_database):
    with isolated_database.begin() as connection:
        connection.execute(text("ALTER TABLE rulebooks DROP COLUMN access_mask, DROP COLUMN category, ADD COLUMN access_role VARCHAR(10) NOT NULL, "
                                "ADD INDEX ix_rulebooks_access_role (access_role)"))
        connection.execute(text("INSERT INTO rulebooks (id, title, access_role) VALUES (:id, :role, :role)"),
                           [{"id": str(index), "role": role} for index, role in enumerate(RULEBOOK_ROLE_BITS)])
    migrate(isolated_database)
    migrate(isolated_database)
    with isolated_database.connect() as connection:
        assert dict(connection.execute(select(Rulebook.title, Rulebook.access_mask)).all()) == RULEBOOK_ROLE_BITS
        assert connection.scalars(select(Rulebook.category)).all() == [None, None, None]
    assert "access_role" not in {column["name"] for column in inspect(isolated_database).get_columns("rulebooks")}

from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper import rulebook_indexer as indexer, rulebooks
from pathkeeper.database import engine
from pathkeeper.models import Rulebook, RulebookIndex, RulebookPage, utcnow
from pathkeeper.rulebook_search import excerpt
from .test_rulebooks import upload


def mixed_pdf():
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 54)
    draw.text((100, 200), "UNIQUE SCANNED WIZARD", fill="black", font=font)
    jpeg = BytesIO()
    image.save(jpeg, format="JPEG")
    native = b"BT /F1 18 Tf 72 700 Td (AC 15 and DR 5. Will saves matter. Spell resistance protects.) Tj ET"
    scanned = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    def stream(data, fields=b""):
        return b"<< /Length " + str(len(data)).encode() + b" " + fields + b" >>\nstream\n" + data + b"\nendstream"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 2 /Kids [3 0 R 6 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream(native),
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 7 0 R >> >> /Contents 8 0 R >>",
        stream(jpeg.getvalue(), b"/Type /XObject /Subtype /Image /Width 1200 /Height 1600 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode"),
        stream(scanned),
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 9\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return pdf + f"trailer\n<< /Size 9 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_native_and_ocr_search_are_role_filtered_and_reindex_publishes_atomically(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rulebooks, "storage_root", lambda: tmp_path / "rulebooks")
    monkeypatch.setattr(indexer, "settings", lambda: SimpleNamespace(storage=tmp_path))
    admin, player, gm = env.login(env.admin), env.login(env.player), env.login(env.gm)
    made = upload(env, admin, "Searchable handbook", ["player"], mixed_pdf())
    assert made.status_code == 303, made.text
    with Session(engine()) as db:
        book = db.scalar(select(Rulebook))
        key = book.id
        assert db.get(RulebookIndex, key).status == "queued"
    assert indexer.process_one()
    with Session(engine()) as db:
        job = db.get(RulebookIndex, key)
        assert (job.status, job.completed_pages, job.total_pages, job.failed_pages) == ("ready", 2, 2, 0)
        assert len(job.fingerprint) == 64
        old_generation = job.active_generation
        pages = db.scalars(select(RulebookPage).order_by(RulebookPage.page)).all()
        assert [page.method for page in pages] == ["native", "ocr"]
        assert "SCANNED" in pages[1].body
    for term in ("AC", "DR", "Will", '"spell resistance"'):
        result = player.get("/rulebooks/search", params={"q": term})
        assert result.status_code == 200, result.text
        assert "1 matching page" in result.text and f"/rulebooks/{key}/read?page=1" in result.text
        assert "<mark>" in result.text
    ocr = player.get("/rulebooks/search", params={"q": "SCANNED"})
    assert "1 matching page" in ocr.text and f"/rulebooks/{key}/read?page=2" in ocr.text
    hidden = gm.get("/rulebooks/search", params={"q": "SCANNED"})
    assert "0 matching pages" in hidden.text and key not in hidden.text and "Searchable handbook" not in hidden.text
    assert gm.get("/rulebooks/search", params={"q": "SCANNED", "book": key}).status_code == 404
    assert "0 matching pages" in player.get("/rulebooks/search", params={"q": "AC", "category": "expanded"}).text
    assert "matching page" in player.get("/rulebooks", params={"q": "AC"}).text
    assert env.post(player, f"/rulebooks/{key}/reindex").status_code == 403

    queued = env.post(admin, f"/rulebooks/{key}/reindex")
    assert queued.status_code == 303
    with Session(engine()) as db:
        assert db.get(RulebookIndex, key).active_generation == old_generation
    assert "1 matching page" in player.get("/rulebooks/search", params={"q": "SCANNED"}).text
    monkeypatch.setattr(indexer, "extract_page", lambda pdf, page, force: (
        ("Updated rulebook text", "native", "") if page == 1 else ("", "failed", "OCR page timed out.")))
    assert indexer.process_one()
    with Session(engine()) as db:
        job = db.get(RulebookIndex, key)
        assert job.status == "partial" and job.failed_pages == 1
        assert job.active_generation != old_generation
        assert len(db.scalars(select(RulebookPage)).all()) == 2
    assert "0 matching pages" in player.get("/rulebooks/search", params={"q": "SCANNED"}).text
    assert "1 matching page" in player.get("/rulebooks/search", params={"q": "Updated"}).text
    assert env.post(admin, f"/rulebooks/{key}/access", {
        "previous_mask": 1, "previous_category": "core", "category": "core", "access_role": ["gm"],
    }).status_code == 303
    assert "0 matching pages" in player.get("/rulebooks/search", params={"q": "Updated"}).text
    assert "1 matching page" in gm.get("/rulebooks/search", params={"q": "Updated"}).text


def test_indexer_resumes_expired_lease_without_duplicate_pages(env, monkeypatch, tmp_path):
    monkeypatch.setattr(indexer, "settings", lambda: SimpleNamespace(storage=tmp_path))
    key = "b" * 32
    directory = tmp_path / "rulebooks" / key
    directory.mkdir(parents=True)
    (directory / "book.pdf").write_bytes(mixed_pdf())
    with Session(engine()) as db:
        db.add(Rulebook(id=key, title="Resume", access_mask=1))
        indexer.enqueue(db, key)
        db.commit()
    claimed = indexer.claim()
    with Session(engine()) as db:
        job = db.get(RulebookIndex, key)
        job.lease_until = utcnow() - timedelta(minutes=1)
        job.completed_pages = 1
        db.add(RulebookPage(book_id=key, generation=job.generation, page=1,
                            body="Preserved progress", search_text="Preserved progress", method="native"))
        db.commit()
    calls = []
    def extract(pdf, page, force):
        calls.append(page)
        return "Resumed page", "ocr", ""
    monkeypatch.setattr(indexer, "extract_page", extract)
    assert indexer.process_one()
    assert calls == [2]
    with Session(engine()) as db:
        job = db.get(RulebookIndex, key)
        assert job.status == "ready" and job.attempts == 2 and job.completed_pages == 2
        assert len(db.scalars(select(RulebookPage)).all()) == 2


def test_search_excerpt_escapes_document_markup():
    snippet = str(excerpt("<script>alert(1)</script> Spell resistance", ["Spell resistance"]))
    assert "<script>" not in snippet and "&lt;script&gt;" in snippet
    assert "<mark>Spell resistance</mark>" in snippet


def test_missing_pdf_retries_are_bounded_and_admin_can_retry(env, monkeypatch, tmp_path):
    monkeypatch.setattr(indexer, "settings", lambda: SimpleNamespace(storage=tmp_path))
    key = "c" * 32
    with Session(engine()) as db:
        db.add(Rulebook(id=key, title="Missing source", access_mask=1))
        indexer.enqueue(db, key)
        db.commit()
    for attempt in range(1, 4):
        assert indexer.process_one()
        with Session(engine()) as db:
            job = db.get(RulebookIndex, key)
            assert job.attempts == attempt
            assert job.status == ("failed" if attempt == 3 else "queued")
            assert job.active_generation is None
            assert job.lease_token is None
            job.retry_at = utcnow() - timedelta(seconds=1)
            db.commit()
    assert not indexer.process_one()
    admin = env.login(env.admin)
    assert env.post(admin, f"/rulebooks/{key}/reindex", {"force_ocr": "on"}).status_code == 303
    with Session(engine()) as db:
        job = db.get(RulebookIndex, key)
        assert job.status == "queued" and job.attempts == 0 and job.force_ocr

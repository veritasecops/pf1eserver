from types import SimpleNamespace

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont
import pytest

from pathkeeper import rulebooks


@pytest.mark.parametrize('left_color', ['white', '#be4030'])
def test_cover_uses_right_front_cover_not_blank_or_back_page(tmp_path, left_color):
    spread = Image.new('RGB', (640, 420), left_color)
    ImageDraw.Draw(spread).rectangle((320, 0, 639, 419), fill='#2064dc')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 30)
    ImageDraw.Draw(spread).text((325, 15), 'PATHFINDER', fill='white', font=font)
    pdf = tmp_path / 'book.pdf'
    spread.save(pdf, format='PDF', save_all=True, append_images=[Image.new('RGB', (320, 420), 'green')])
    original = pdf.read_bytes()
    rulebooks.render_cover(pdf, tmp_path)
    with Image.open(tmp_path / 'cover.png') as cover:
        assert cover.height == 420 and cover.width == 320
        r, g, b = cover.getpixel((cover.width // 2, cover.height // 2))
        assert b > r + 100 and b > g + 70
        # The front-cover title must survive the crop.
        assert any(min(cover.getpixel((x, y))) > 220 for x in range(10, 300) for y in range(15, 50))
    assert pdf.read_bytes() == original


def test_portrait_cover_keeps_the_whole_page(tmp_path):
    image = Image.new('RGB', (320, 420), '#be4030')
    ImageDraw.Draw(image).rectangle((160, 0, 319, 419), fill='#2064dc')
    image.save(tmp_path / 'book.pdf', format='PDF')
    rulebooks.render_cover(tmp_path / 'book.pdf', tmp_path)
    with Image.open(tmp_path / 'cover.png') as cover:
        assert cover.size == (320, 420)
        left, right = cover.getpixel((40, 200)), cover.getpixel((280, 200))
        assert left[0] > left[2] + 100
        assert right[2] > right[0] + 100


def test_wraparound_cover_excludes_the_spine(tmp_path):
    wrap = Image.new('RGB', (720, 440), 'red')
    draw = ImageDraw.Draw(wrap)
    draw.rectangle((340, 0, 379, 439), fill='green')
    draw.rectangle((380, 0, 719, 439), fill='#2064dc')
    wrap.save(tmp_path / 'book.pdf', format='PDF')
    rulebooks.render_cover(tmp_path / 'book.pdf', tmp_path)
    with Image.open(tmp_path / 'cover.png') as cover:
        assert cover.height == 420
        for x in (3, cover.width // 2, cover.width - 4):
            r, g, b = cover.getpixel((x, 200))
            assert b > r + 100 and b > g + 70


def test_failed_cover_refresh_preserves_existing_thumbnail(monkeypatch, tmp_path):
    original = b'existing cover'
    (tmp_path / 'cover.png').write_bytes(original)
    monkeypatch.setattr(rulebooks, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(HTTPException) as error:
        rulebooks.render_cover(tmp_path / 'book.pdf', tmp_path)
    assert error.value.status_code == 422
    assert (tmp_path / 'cover.png').read_bytes() == original
    assert not list(tmp_path.glob('.cover-*'))


def test_bulk_refresh_backs_up_covers_without_changing_pdf_or_records(env, monkeypatch, tmp_path):
    from sqlalchemy.orm import Session
    from pathkeeper.database import engine
    from pathkeeper.manage import refresh_rulebook_covers
    from pathkeeper.models import Rulebook

    root = tmp_path / 'rulebooks'
    key = 'f' * 32
    directory = root / key
    directory.mkdir(parents=True)
    Image.new('RGB', (320, 420), '#2064dc').save(directory / 'book.pdf', format='PDF')
    pdf = (directory / 'book.pdf').read_bytes()
    Image.new('RGB', (100, 100), 'red').save(directory / 'cover.png')
    previous = (directory / 'cover.png').read_bytes()
    monkeypatch.setattr(rulebooks, 'storage_root', lambda: root)
    with Session(engine()) as db:
        db.add(Rulebook(id=key, title='Cover refresh test', access_mask=4, category='core'))
        db.commit()
    refresh_rulebook_covers(tmp_path / 'backups')
    assert (directory / 'book.pdf').read_bytes() == pdf
    assert (directory / 'cover.png').read_bytes() != previous
    saved, = (tmp_path / 'backups').glob('covers-*/*.png')
    assert saved.read_bytes() == previous
    with Session(engine()) as db:
        book = db.get(Rulebook, key)
        assert (book.title, book.access_mask, book.category) == ('Cover refresh test', 4, 'core')

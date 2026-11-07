"""Private PDF storage and role-scoped rulebook browsing."""
from functools import lru_cache
import logging
from pathlib import Path
import re
import shutil
from subprocess import DEVNULL, PIPE, run, TimeoutExpired
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .config import settings
from .database import get_db
from .models import RULEBOOK_ROLE_BITS, Rulebook
from .security import ROLES, administrator, audit, authenticated, context, field, integer, read_form, verify_csrf
from .ui import redirect, render

router = APIRouter(prefix="/rulebooks")
UPLOAD_PATH = "/rulebooks/upload"
MAX_PDF = 250 * 1024 * 1024
MAX_REQUEST = MAX_PDF + 64 * 1024
PDF_ERROR = "Choose a readable PDF with at least one page and no password protection."
CATEGORIES = {"core": "Core", "expanded": "Expanded", "alternate": "Alternate", "third-party": "3rd Party"}


class RequestTooLarge(MultiPartException):
    pass


async def bounded_upload(request):
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_REQUEST:
            raise RequestTooLarge("Upload a PDF of 250 MB or smaller.")
        yield chunk


def storage_root():
    return settings().storage / "rulebooks"


def save_pdf(source, destination):
    if source.read(5) != b"%PDF-":
        raise HTTPException(422, PDF_ERROR)
    source.seek(0)
    pdf = destination / "book.pdf"
    remaining = MAX_PDF
    with pdf.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            remaining -= len(chunk)
            if remaining < 0:
                raise HTTPException(413, "Upload a PDF of 250 MB or smaller.")
            output.write(chunk)
    try:
        rendered = run(
            ["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-scale-to", "420", "-png",
             str(pdf), str(destination / "cover")],
            stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, timeout=25,
        )
    except FileNotFoundError as error:
        raise HTTPException(503, "PDF cover rendering is unavailable.") from error
    except TimeoutExpired as error:
        raise HTTPException(422, "The first PDF page took too long to render.") from error
    if rendered.returncode or not (destination / "cover.png").is_file():
        raise HTTPException(422, PDF_ERROR)


def selected_access(roles):
    if not roles or roles.difference(RULEBOOK_ROLE_BITS):
        raise HTTPException(422, "Choose one or more access roles from the list.")
    return sum(RULEBOOK_ROLE_BITS[role] for role in roles)


def roles_for(mask):
    return [role for role, bit in RULEBOOK_ROLE_BITS.items() if mask & bit]


def selected_category(form, *, required):
    category = field(form, "category", 16, required=required)
    if category and category not in CATEGORIES:
        raise HTTPException(422, "Choose a category from the list.")
    return category or None


@router.get("")
async def library(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    user = authenticated(ctx)
    category = request.query_params.get("category", "")
    query = select(Rulebook).where(Rulebook.access_mask.bitwise_and(RULEBOOK_ROLE_BITS[user.role]) != 0)
    if category in CATEGORIES:
        query = query.where(Rulebook.category == category)
    books = db.scalars(query.order_by(Rulebook.title, Rulebook.id)).all()
    return render(ctx, "rulebooks.html", title="Rulebook library", books=books,
                  role_label=ROLES[user.role], can_upload=user.role == "admin",
                  categories=CATEGORIES, access_roles=ROLES, category=category if category in CATEGORIES else "")


def upload_page(ctx, title="", roles=(), category=None, error="", status=200, return_to_library=False):
    books = ctx.db.scalars(select(Rulebook).order_by(Rulebook.title, Rulebook.id))
    response = render(ctx, "rulebook_upload.html", title="Upload rulebook", book_title=title,
                      selected_roles=roles, access_roles=ROLES, categories=CATEGORIES, upload_category=category,
                      error=error, return_to_library=return_to_library,
                      managed_books=[(book, roles_for(book.access_mask)) for book in books])
    response.status_code = status
    return response


@router.get("/upload")
async def upload_form(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return upload_page(ctx)


@router.post("/upload")
async def upload_book(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    actor = administrator(ctx)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
        return upload_page(ctx, error="Choose a PDF file to upload.", status=422)
    try:
        form = await MultiPartParser(request.headers, bounded_upload(request), max_files=1, max_fields=4 + len(ROLES),
                                     max_part_size=4096).parse()
    except RequestTooLarge as error:
        return upload_page(ctx, error=error.message, status=413)
    except MultiPartException:
        return upload_page(ctx, error="The upload form could not be read.", status=422)

    title = ""
    roles = set()
    category = None
    try:
        verify_csrf(ctx, form)
        return_to_library = form.get("return_to") == "library"
        try:
            title = field(form, "title")
            roles = set(form.getlist("access_role"))
            access_mask = selected_access(roles)
            category = selected_category(form, required=True)
            upload = form.get("pdf")
            if not isinstance(upload, UploadFile) or not (upload.filename or "").lower().endswith(".pdf"):
                raise HTTPException(422, "Choose a PDF file.")
            if upload.size is not None and upload.size > MAX_PDF:
                raise HTTPException(413, "Upload a PDF of 250 MB or smaller.")

            root = storage_root()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            key = uuid4().hex
            destination = root / key
            with TemporaryDirectory(prefix=".upload-", dir=root) as temporary:
                stage = Path(temporary)
                await run_in_threadpool(save_pdf, upload.file, stage)
                stage.rename(destination)
                try:
                    db.add(Rulebook(id=key, title=title, access_mask=access_mask, category=category))
                    labels = ", ".join(ROLES[role] for role in roles_for(access_mask))
                    audit(db, actor, "rulebook.uploaded", f"Uploaded rulebook {key} for {labels}.")
                    return redirect(ctx, "/rulebooks" if return_to_library else "/rulebooks/upload", "Rulebook uploaded.")
                except Exception:
                    try:
                        shutil.rmtree(destination)
                    except OSError:
                        logging.getLogger(__name__).exception("Could not remove failed rulebook upload %s", key)
                    raise
        except HTTPException as error:
            return upload_page(ctx, title=title, roles=roles, category=category, error=error.detail,
                               status=error.status_code, return_to_library=return_to_library)
    finally:
        await form.close()


def get_book(db, key, *, lock=False):
    book = db.get(Rulebook, key, with_for_update=lock) if re.fullmatch(r"[a-f0-9]{32}", key) else None
    if book is None:
        raise HTTPException(404, "Rulebook not found.")
    return book


@router.post("/{key}/access")
async def update_access(key: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    actor = administrator(ctx)
    form = await read_form(ctx, max_fields=4 + len(ROLES))
    book = get_book(db, key, lock=True)
    if (integer(form, "previous_mask", 1, sum(RULEBOOK_ROLE_BITS.values())) != book.access_mask
            or (form.get("previous_category") or None) != book.category):
        raise HTTPException(409, "Rulebook settings changed in another window. Reload before saving.")
    book.access_mask = selected_access(set(form.getlist("access_role")))
    book.category = selected_category(form, required=False)
    labels = ", ".join(ROLES[role] for role in roles_for(book.access_mask))
    audit(db, actor, "rulebook.settings_updated",
          f"Updated rulebook {key} for {labels}. Category {CATEGORIES.get(book.category, 'Uncategorized')}.")
    return redirect(ctx, "/rulebooks/upload", "Rulebook settings updated.")


def visible_book(request, db, key):
    ctx = context(request, db)
    user = authenticated(ctx)
    book = get_book(db, key)
    if not book.access_mask & RULEBOOK_ROLE_BITS[user.role]:
        raise HTTPException(404, "Rulebook not found.")
    return book


def book_file(key, name):
    path = storage_root() / key / name
    if not path.is_file():
        raise HTTPException(404, "Rulebook file not found.")
    return path


@router.api_route("/{key}/cover", methods=["GET", "HEAD"])
async def cover(key: str, request: Request, db: Session = Depends(get_db)):
    book = visible_book(request, db, key)
    return FileResponse(book_file(book.id, "cover.png"), media_type="image/png")


@router.api_route("/{key}/pdf", methods=["GET", "HEAD"])
async def legacy_pdf_link(key: str, request: Request, db: Session = Depends(get_db)):
    book = visible_book(request, db, key)
    return RedirectResponse(f"/rulebooks/{book.id}/read", status_code=303)


def pdf_output(*args):
    try:
        result = run(args, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, timeout=25)
    except (FileNotFoundError, TimeoutExpired) as error:
        raise HTTPException(503, "The rulebook reader could not render this document.") from error
    if result.returncode:
        raise HTTPException(422, "This rulebook could not be opened.")
    return result.stdout


@lru_cache(maxsize=128)
def page_count(pdf):
    match = re.search(rb"^Pages:\s*([1-9][0-9]*)\s*$", pdf_output("pdfinfo", str(pdf)), re.MULTILINE)
    if not match:
        raise HTTPException(422, "This rulebook has no readable pages.")
    return int(match[1])


async def reader_page(book, page):
    pdf = book_file(book.id, "book.pdf")
    pages = await run_in_threadpool(page_count, pdf)
    if not 1 <= page <= pages:
        raise HTTPException(404, "Rulebook page not found.")
    return pdf, pages


@router.get("/{key}/read")
async def read_book(key: str, request: Request, page: int = 1, db: Session = Depends(get_db)):
    book = visible_book(request, db, key)
    _, pages = await reader_page(book, page)
    return render(context(request, db), "rulebook_reader.html", title=book.title, book=book, page=page, pages=pages)


@router.get("/{key}/pages/{page}")
async def read_page(key: str, page: int, request: Request, db: Session = Depends(get_db)):
    book = visible_book(request, db, key)
    pdf, _ = await reader_page(book, page)
    png = await run_in_threadpool(pdf_output, "pdftoppm", "-f", str(page), "-l", str(page),
                                  "-singlefile", "-scale-to", "1800", "-png", str(pdf))
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "This rulebook page could not be rendered.")
    return Response(png, media_type="image/png")

"""Private PDF storage and role-scoped rulebook browsing."""
import logging
from pathlib import Path
import re
import shutil
from subprocess import DEVNULL, run, TimeoutExpired
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .config import settings
from .database import get_db
from .models import Rulebook
from .security import ROLES, administrator, audit, authenticated, context, field, verify_csrf
from .ui import redirect, render

router = APIRouter(prefix="/rulebooks")
UPLOAD_PATH = "/rulebooks/upload"
MAX_PDF = 50 * 1024 * 1024
MAX_REQUEST = MAX_PDF + 64 * 1024
PDF_ERROR = "Choose a readable PDF with at least one page and no password protection."


class RequestTooLarge(MultiPartException):
    pass


async def bounded_upload(request):
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_REQUEST:
            raise RequestTooLarge("Upload a PDF of 50 MB or smaller.")
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
                raise HTTPException(413, "Upload a PDF of 50 MB or smaller.")
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


@router.get("")
async def library(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    user = authenticated(ctx)
    books = db.scalars(select(Rulebook).where(Rulebook.access_role == user.role)
                       .order_by(Rulebook.title, Rulebook.id)).all()
    return render(ctx, "rulebooks.html", title="Rulebook library", books=books,
                  role_label=ROLES[user.role], can_upload=user.role == "admin")


def upload_page(ctx, title="", access_role="", error="", status=200):
    response = render(ctx, "rulebook_upload.html", title="Upload rulebook", book_title=title,
                      access_role=access_role, access_roles=ROLES, error=error)
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
        form = await MultiPartParser(request.headers, bounded_upload(request), max_files=1, max_fields=3,
                                     max_part_size=4096).parse()
    except RequestTooLarge as error:
        return upload_page(ctx, error=error.message, status=413)
    except MultiPartException:
        return upload_page(ctx, error="The upload form could not be read.", status=422)

    title = access_role = ""
    try:
        verify_csrf(ctx, form)
        try:
            title = field(form, "title")
            access_role = field(form, "access_role", 10)
            if access_role not in ROLES:
                raise HTTPException(422, "Choose an access role from the list.")
            upload = form.get("pdf")
            if not isinstance(upload, UploadFile) or not (upload.filename or "").lower().endswith(".pdf"):
                raise HTTPException(422, "Choose a PDF file.")
            if upload.size is not None and upload.size > MAX_PDF:
                raise HTTPException(413, "Upload a PDF of 50 MB or smaller.")

            root = storage_root()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            key = uuid4().hex
            destination = root / key
            with TemporaryDirectory(prefix=".upload-", dir=root) as temporary:
                stage = Path(temporary)
                await run_in_threadpool(save_pdf, upload.file, stage)
                stage.rename(destination)
                try:
                    db.add(Rulebook(id=key, title=title, access_role=access_role))
                    audit(db, actor, "rulebook.uploaded", f"Uploaded rulebook {key} for {ROLES[access_role]}.")
                    return redirect(ctx, "/rulebooks/upload", f"Rulebook uploaded for {ROLES[access_role]} access.")
                except Exception:
                    try:
                        shutil.rmtree(destination)
                    except OSError:
                        logging.getLogger(__name__).exception("Could not remove failed rulebook upload %s", key)
                    raise
        except HTTPException as error:
            return upload_page(ctx, title, access_role, error.detail, error.status_code)
    finally:
        await form.close()


def visible_book(request, db, key):
    ctx = context(request, db)
    user = authenticated(ctx)
    book = db.get(Rulebook, key) if re.fullmatch(r"[a-f0-9]{32}", key) else None
    if not book or book.access_role != user.role:
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
async def pdf(key: str, request: Request, db: Session = Depends(get_db)):
    book = visible_book(request, db, key)
    return FileResponse(book_file(book.id, "book.pdf"), media_type="application/pdf",
                        filename=f"{book.title}.pdf", content_disposition_type="inline")

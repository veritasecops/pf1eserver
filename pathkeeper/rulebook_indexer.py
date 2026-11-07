"""Durable page indexing with bounded native extraction and English OCR."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
import logging
import os
from pathlib import Path
import re
import signal
from subprocess import DEVNULL, PIPE, run, TimeoutExpired
from tempfile import TemporaryDirectory
import threading
import unicodedata
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from .config import settings
from .database import engine
from .models import Rulebook, RulebookIndex, RulebookPage, utcnow

PIPELINE_VERSION = 1
LEASE = timedelta(minutes=5)
MAX_TEXT = 1024 * 1024
STATUS_LABELS = {
    "queued": "Queued", "indexing": "Indexing", "ready": "Ready",
    "partial": "Partial", "failed": "Failed",
}


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\x00", "").replace("\u00ad", "")
    return re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", text)


def enqueue(db, book_id, force_ocr=False):
    job = db.get(RulebookIndex, book_id, with_for_update=True)
    if job and job.status in {"queued", "indexing"}:
        if job.status == "queued":
            job.force_ocr = job.force_ocr or force_ocr
        return False
    if job is None:
        job = RulebookIndex(book_id=book_id)
        db.add(job)
    else:
        db.execute(delete(RulebookPage).where(
            RulebookPage.book_id == book_id,
            RulebookPage.generation != (job.active_generation or ""),
        ))
    job.generation = uuid4().hex
    job.status, job.force_ocr = "queued", force_ocr
    job.completed_pages = job.total_pages = job.failed_pages = job.attempts = 0
    job.retry_at, job.error = utcnow(), ""
    job.lease_until = job.lease_token = None
    job.fingerprint = None
    job.pipeline_version = PIPELINE_VERSION
    return True


def tool(*args, timeout=60):
    try:
        result = run(args, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, timeout=timeout,
                     env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    except TimeoutExpired as error:
        raise ValueError(f"{Path(args[0]).name} exceeded its processing time limit.") from error
    except FileNotFoundError as error:
        raise ValueError(f"{Path(args[0]).name} is unavailable.") from error
    if result.returncode:
        raise ValueError(f"{Path(args[0]).name} could not process the page.")
    if len(result.stdout) > MAX_TEXT:
        raise ValueError("Extracted text exceeded the page size limit.")
    return result.stdout.decode("utf-8", errors="replace")


def extract_page(pdf, page, force_ocr):
    native = ""
    try:
        native = normalize(tool("pdftotext", "-f", str(page), "-l", str(page), "-enc", "UTF-8", str(pdf), "-"))
        if not force_ocr and sum(char.isalpha() for char in native) >= 20:
            return native, "native", ""
        with TemporaryDirectory(prefix="pathkeeper-ocr-") as temporary:
            image = Path(temporary) / "page"
            tool("pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-r", "300",
                 "-scale-to", "3300", "-png", str(pdf), str(image))
            text = normalize(tool("tesseract", str(image) + ".png", "stdout", "-l", "eng", "--psm", "3", timeout=120))
            return text, "ocr" if text.strip() else "blank", ""
    except ValueError as error:
        return native, "failed", str(error)


def claim():
    now = utcnow()
    with Session(engine(), expire_on_commit=False) as db:
        db.execute(update(RulebookIndex).where(
            RulebookIndex.status == "indexing", RulebookIndex.lease_until < now,
            RulebookIndex.attempts >= 3,
        ).values(status="failed", error="Indexing was interrupted repeatedly. Retry from Manage rulebooks.",
                 lease_token=None, lease_until=None))
        job = db.scalar(select(RulebookIndex).where(
            RulebookIndex.attempts < 3,
            or_((RulebookIndex.status == "queued") & (RulebookIndex.retry_at <= now),
                (RulebookIndex.status == "indexing") & (RulebookIndex.lease_until < now)),
        ).order_by(RulebookIndex.retry_at, RulebookIndex.book_id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            db.commit()
            return None
        job.status, job.lease_token, job.lease_until = "indexing", uuid4().hex, now + LEASE
        job.attempts += 1
        db.commit()
        return job


def owned_job(db, claimed):
    job = db.get(RulebookIndex, claimed.book_id, with_for_update=True)
    if not job or job.generation != claimed.generation or job.lease_token != claimed.lease_token:
        raise InterruptedError("The indexing lease changed.")
    job.lease_until = utcnow() + LEASE
    return job


def process_one(stopped=None):
    claimed = claim()
    if claimed is None:
        return False
    stopped = stopped or threading.Event()
    try:
        pdf = settings().storage / "rulebooks" / claimed.book_id / "book.pdf"
        digest = sha256()
        with pdf.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint = digest.hexdigest()
        info = tool("pdfinfo", str(pdf))
        match = re.search(r"^Pages:\s*([1-9][0-9]*)\s*$", info, re.MULTILINE)
        if not match or int(match[1]) > 10000:
            raise ValueError("The PDF must have between 1 and 10,000 readable pages.")
        count = int(match[1])
        with Session(engine()) as db:
            job = owned_job(db, claimed)
            if job.fingerprint and job.fingerprint != fingerprint:
                raise ValueError("The stored PDF changed. Reindex this rulebook.")
            job.fingerprint, job.total_pages = fingerprint, count
            existing = set(db.scalars(select(RulebookPage.page).where(
                RulebookPage.book_id == job.book_id, RulebookPage.generation == job.generation)))
            db.commit()
        pending = [page for page in range(1, count + 1) if page not in existing]
        with ThreadPoolExecutor(max_workers=2) as pool:
            for start in range(0, len(pending), 2):
                if stopped.is_set():
                    raise InterruptedError("The indexing worker is stopping.")
                batch = pending[start:start + 2]
                results = pool.map(lambda page: extract_page(pdf, page, claimed.force_ocr), batch)
                for page, (body, method, error) in zip(batch, results):
                    with Session(engine()) as db:
                        job = owned_job(db, claimed)
                        db.add(RulebookPage(book_id=job.book_id, generation=job.generation, page=page,
                                            body=body, search_text=" ".join(body.split()), method=method, error=error))
                        job.completed_pages += 1
                        job.failed_pages += int(bool(error))
                        db.commit()
        with Session(engine()) as db:
            job = owned_job(db, claimed)
            if job.completed_pages != count:
                raise ValueError("The page index is incomplete. Retry indexing.")
            job.active_generation = job.generation
            job.status = "partial" if job.failed_pages else "ready"
            job.error = f"{job.failed_pages} pages could not be fully extracted. Reindex to retry." if job.failed_pages else ""
            job.indexed_at = utcnow()
            job.lease_until = job.lease_token = None
            db.execute(delete(RulebookPage).where(RulebookPage.book_id == job.book_id,
                                                 RulebookPage.generation != job.active_generation))
            db.commit()
    except (OSError, ValueError, InterruptedError) as error:
        with Session(engine()) as db:
            try:
                job = owned_job(db, claimed)
            except InterruptedError:
                return True
            job.status = "queued" if job.attempts < 3 else "failed"
            if stopped.is_set():
                job.status = "queued"
                job.attempts -= 1
            job.retry_at = utcnow() + timedelta(seconds=30 * job.attempts)
            job.error = str(error)[:300] if not isinstance(error, OSError) else "The stored PDF could not be read."
            job.lease_until = job.lease_token = None
            db.commit()
    return True


def backfill():
    with Session(engine()) as db:
        for book_id in db.scalars(select(Rulebook.id).with_for_update()):
            job = db.get(RulebookIndex, book_id)
            if job is None or job.pipeline_version != PIPELINE_VERSION:
                enqueue(db, book_id)
        db.commit()


def main():
    stopped = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stopped.set())
    backfill()
    while not stopped.is_set():
        try:
            if not process_one(stopped):
                stopped.wait(2)
        except Exception:
            logging.getLogger(__name__).exception("Rulebook indexing worker failed.")
            stopped.wait(5)


if __name__ == "__main__":
    main()

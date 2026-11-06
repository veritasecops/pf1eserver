import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import backpack, equipment_disposal, character_weapons, character_dice
from . import account_email, administration, catalog_admin, auth, character_wizard, email_admin, portraits, workspace
from .config import ROOT, settings
from .database import engine
from .security import COOKIE, RedirectTo, context
from .ui import templates

app = FastAPI(title="Pathkeeper", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def response_security(request, call_next):
    try:
        if int(request.headers.get("content-length", "0")) > 256 * 1024:
            return JSONResponse({"detail": "This request is too large."}, 413)
    except ValueError:
        return JSONResponse({"detail": "Invalid request length."}, 400)
    response = await call_next(request)
    if getattr(request.state, "clear_cookie", False):
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=settings().secure_cookies)
    elif getattr(request.state, "issue_cookie", None):
        response.set_cookie(COOKIE, request.state.issue_cookie, max_age=request.state.cookie_lifetime,
                            path="/", httponly=True, samesite="lax", secure=settings().secure_cookies)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer" if request.url.path.startswith(("/reset-password/", "/verify-email/", "/join/")) else "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RedirectTo)
async def handle_redirect(request, error):
    return RedirectResponse(error.path, 303)


@app.exception_handler(HTTPException)
async def handle_http_error(request, error):
    if request.url.path.startswith("/api/") or request.url.path.startswith("/characters/") and request.url.path.endswith("/weapons"):
        return JSONResponse({"detail": error.detail}, error.status_code)
    ctx = getattr(request.state, "context", None)
    if not ctx:
        return JSONResponse({"detail": error.detail}, error.status_code)
    ctx.db.rollback()
    return templates.TemplateResponse(request=request, name="error.html", context={
        "user": None, "csrf": "", "flash": None, "limited": False,
        "path": request.url.path, "title": "Request could not be completed",
        "status": error.status_code, "detail": error.detail}, status_code=error.status_code)


@app.exception_handler(Exception)
async def handle_unexpected(request, error):
    logging.getLogger("pathkeeper").exception("Unhandled application error", exc_info=error)
    return JSONResponse({"detail": "The server could not complete this request. An administrator can check the service log."}, 500)


@app.get("/api/health")
@app.get("/health")
def health():
    with Session(engine()) as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "application": "Pathkeeper", "version": "0.2.0", "database": "MariaDB", "server": "Uvicorn"}


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.include_router(auth.router)
app.include_router(account_email.router)
app.include_router(administration.router)
app.include_router(catalog_admin.router)
app.include_router(catalog_admin.equipment_router)
app.include_router(email_admin.router)
app.include_router(character_wizard.router)
app.include_router(character_weapons.router)
app.include_router(equipment_disposal.router)
app.include_router(backpack.router)
app.include_router(character_dice.router)
app.include_router(workspace.router)
app.include_router(portraits.router)

# Public documentation never queries the user store.
from .help import router as help_router
app.include_router(help_router)

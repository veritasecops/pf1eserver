import hmac
import io
import re
import time
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .database import commit, get_db
from .models import RecoveryCode, User, utcnow
from .notifications import account_email, email_ready, invalidate_tokens, password_notice
from .security import (DUMMY_HASH, PASSWORDS, audit, authenticated, context, decrypt, email_field,
                       encrypt, field, hash_password, make_recovery_codes, password_ok,
                       read_form, reauthenticate, request_ip, revoke_sessions, rotate,
                       throttle, verify_factor)
from .ui import redirect, render

router = APIRouter()


def safe_next(path):
    return path if re.fullmatch(r"/join/[A-Za-z0-9_-]{20,100}", path or "") else "/"


@router.get("/signup")
async def signup_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    if ctx.user:
        return redirect(ctx, "/")
    ctx.session.next_path = safe_next(request.query_params.get("next", ctx.session.next_path))
    commit(db)
    return render(ctx, "signup.html", title="Create a Player account")


@router.post("/signup")
async def signup(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    if ctx.user:
        return redirect(ctx, "/")
    form = await read_form(ctx)
    throttle("signup-ip", request_ip(request), 10, 15)

    def failure(message, status=422):
        response = render(ctx, "signup.html", title="Create a Player account", error=message,
                          name=str(form.get("name", ""))[:100], email=str(form.get("email", ""))[:190])
        response.status_code = status
        return response

    try:
        name = field(form, "name", 100)
        email = email_field(form)
        password = str(form.get("password", ""))
        if password != form.get("confirm_password"):
            return failure("The passwords do not match.")
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            return failure("An account already uses this email. Sign in or contact an Admin for recovery.", 409)
        encoded = await run_in_threadpool(hash_password, password)
    except HTTPException as error:
        return failure(error.detail, error.status_code)
    # Public fields cannot choose roles, disabled state, or security requirements.
    account = User(name=name, email=email, password_hash=encoded, role="player", active=True,
                   must_change_password=False, totp_required=False, last_login=utcnow(),
                   email_verification_required=email_ready(db))
    try:
        db.add(account)
        db.flush()
        rotate(ctx, account)
        audit(db, account, "user.signed_up", "Created a Player account through public sign-up.")
        account_email(db, account)
        commit(db)
    except IntegrityError:
        db.rollback()
        return failure("An account already uses this email. Sign in or contact an Admin for recovery.", 409)
    return redirect(ctx, ctx.session.next_path, "Your Player account is ready. Welcome to Pathkeeper.")


@router.get("/login")
async def login_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    if ctx.user and ctx.session.phase == "authenticated":
        return redirect(ctx, "/")
    if ctx.session.phase == "mfa":
        return redirect(ctx, "/login/totp")
    ctx.session.next_path = safe_next(request.query_params.get("next", ctx.session.next_path))
    commit(db)
    return render(ctx, "login.html", title="Welcome back")


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    email = field(form, "email", 190).lower()
    throttle("login-ip", request_ip(request), 30)
    throttle("login-account", email, 10)
    account = db.scalar(select(User).where(User.email == email))
    verified = await run_in_threadpool(password_ok, str(form.get("password", "")), account.password_hash if account else DUMMY_HASH)
    if not account or not verified or not account.active:
        audit(db, None, "login.failed", "An unsuccessful sign-in attempt was recorded.")
        commit(db)
        return render(ctx, "login.html", title="Welcome back", error="Email or password is incorrect.", email=email)
    if PASSWORDS.check_needs_rehash(account.password_hash):
        account.password_hash = await run_in_threadpool(hash_password, str(form.get("password", "")))
    rotate(ctx, account, "mfa" if account.totp_enabled else "authenticated")
    if account.totp_enabled:
        return redirect(ctx, "/login/totp")
    account.last_login = utcnow()
    audit(db, account, "login.password", "Signed in with a password; enrollment requirements are enforced separately.")
    return redirect(ctx, ctx.session.next_path)


@router.get("/login/totp")
async def totp_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    if ctx.session.phase != "mfa" or not ctx.user:
        return redirect(ctx, "/login")
    return render(ctx, "totp_login.html", title="Verify your sign-in")


@router.post("/login/totp")
async def totp_login(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    if ctx.session.phase != "mfa" or not ctx.user:
        return redirect(ctx, "/login")
    throttle("login-mfa", str(ctx.user.id), 8, 5)
    account = db.scalar(select(User).where(User.id == ctx.user.id).with_for_update().execution_options(populate_existing=True))
    if not account or not account.active or not verify_factor(db, account, field(form, "code", 100)):
        db.rollback()
        return render(ctx, "totp_login.html", title="Verify your sign-in", error="That code is invalid or has already been used. Try a fresh code or an unused recovery code.")
    rotate(ctx, account, mfa=True)
    account.last_login = utcnow()
    audit(db, account, "login.mfa", "Completed two-factor sign-in.")
    return redirect(ctx, ctx.session.next_path)


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    await read_form(ctx)
    if ctx.user:
        audit(db, ctx.user, "logout", "Signed out.")
    rotate(ctx, phase="anonymous")
    return redirect(ctx, "/login")


@router.get("/account")
async def account_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx)
    return render(ctx, "account.html", title="My profile", zones=sorted(available_timezones()))


@router.post("/account")
async def account_update(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    form = await read_form(ctx)
    email = email_field(form)
    email_changed = email != account.email
    if email_changed:
        await reauthenticate(ctx, form)
        revoke_sessions(db, account.id, ctx.session.token_hash)
    account.name = field(form, "name", 100)
    account.email = email
    account.bio = field(form, "bio", 2000, False)
    zone = field(form, "timezone", 80)
    try:
        ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Choose a valid time zone.") from None
    account.timezone = zone
    if email_changed:
        account.email_verified_at = None
        account.email_verification_required = email_ready(db)
        invalidate_tokens(db, account.id)
        account_email(db, account)
    audit(db, account, "profile.updated", "Updated their profile.")
    return redirect(ctx, "/account", "Your profile has been saved.")


@router.get("/account/password")
async def password_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx, allow_setup=True)
    return render(ctx, "password.html", title="Change password")


@router.post("/account/password")
async def password_update(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx, allow_setup=True)
    form = await read_form(ctx)
    account = await reauthenticate(ctx, form)
    if form.get("new_password") != form.get("confirm_password"):
        raise HTTPException(422, "The new passwords do not match.")
    account.password_hash = await run_in_threadpool(hash_password, str(form.get("new_password", "")))
    account.must_change_password = False
    invalidate_tokens(db, account.id, ("reset", "setup"))
    revoke_sessions(db, account.id, ctx.session.token_hash)
    rotate(ctx, account, mfa=ctx.session.mfa_verified)
    audit(db, account, "password.changed", "Changed their password and revoked other sessions.")
    password_notice(db, account)
    return redirect(ctx, ctx.session.next_path, "Password changed. Other devices have been signed out.")


@router.get("/account/security")
async def security_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx, allow_setup=True)
    if account.must_change_password:
        return redirect(ctx, "/account/password")
    pending = bool(account.pending_totp and account.pending_totp_at and account.pending_totp_at > utcnow() - timedelta(minutes=10))
    count = db.scalar(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.user_id == account.id))
    return render(ctx, "security.html", title="Account security", pending=pending,
                  manual_secret=decrypt(account.pending_totp) if pending else "", recovery_count=count)


@router.post("/account/security/setup")
async def setup_totp(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx, allow_setup=True)
    if account.must_change_password:
        return redirect(ctx, "/account/password")
    form = await read_form(ctx)
    if account.totp_enabled:
        raise HTTPException(409, "Two-factor authentication is already enabled.")
    await reauthenticate(ctx, form)
    account.pending_totp = encrypt(pyotp.random_base32())
    account.pending_totp_at = utcnow()
    return redirect(ctx, "/account/security")


@router.get("/account/security/qr.svg")
async def totp_qr(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx, allow_setup=True)
    if account.must_change_password or not account.pending_totp or not account.pending_totp_at or account.pending_totp_at <= utcnow() - timedelta(minutes=10):
        raise HTTPException(404, "Start authenticator setup again.")
    uri = pyotp.TOTP(decrypt(account.pending_totp)).provisioning_uri(account.email, issuer_name="Pathkeeper")
    output = io.BytesIO()
    segno.make(uri).save(output, kind="svg", scale=5, border=2)
    return Response(output.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.post("/account/security/enable")
async def enable_totp(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx, allow_setup=True)
    form = await read_form(ctx)
    if ctx.user.must_change_password:
        return redirect(ctx, "/account/password")
    throttle("enroll", str(ctx.user.id), 8, 5)
    account = db.scalar(select(User).where(User.id == ctx.user.id).with_for_update().execution_options(populate_existing=True))
    if account.totp_enabled or not account.pending_totp or not account.pending_totp_at or account.pending_totp_at <= utcnow() - timedelta(minutes=10):
        raise HTTPException(409, "Start authenticator setup again.")
    code = field(form, "code", 6)
    totp = pyotp.TOTP(decrypt(account.pending_totp))
    now_counter = int(time.time()) // 30
    matched = next((counter for counter in (now_counter, now_counter - 1, now_counter + 1)
                    if re.fullmatch(r"[0-9]{6}", code) and hmac.compare_digest(totp.at(counter * 30), code)), None)
    if matched is None:
        raise HTTPException(422, "The authenticator code is incorrect. Check your device's clock and try again.")
    account.totp_secret = account.pending_totp
    account.pending_totp = None
    account.pending_totp_at = None
    account.totp_enabled = True
    account.last_totp_counter = matched
    codes = make_recovery_codes(db, account.id)
    revoke_sessions(db, account.id, ctx.session.token_hash)
    rotate(ctx, account, mfa=True)
    audit(db, account, "mfa.enabled", "Enabled authenticator two-factor authentication.")
    commit(db)
    return render(ctx, "recovery_codes.html", title="Save your recovery codes", codes=codes)


@router.post("/account/security/recovery")
async def replace_recovery(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx)
    form = await read_form(ctx)
    account = await reauthenticate(ctx, form)
    if not account.totp_enabled:
        raise HTTPException(409, "Enable two-factor authentication first.")
    codes = make_recovery_codes(db, account.id)
    audit(db, account, "mfa.recovery_replaced", "Replaced all recovery codes.")
    commit(db)
    return render(ctx, "recovery_codes.html", title="Save your recovery codes", codes=codes)


@router.post("/account/security/disable")
async def disable_totp(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx)
    form = await read_form(ctx)
    account = await reauthenticate(ctx, form)
    if account.totp_required or account.role == "admin":
        raise HTTPException(403, "Two-factor authentication is required for this account. An Admin can reset a lost authenticator.")
    account.totp_enabled = False
    account.totp_secret = None
    account.pending_totp = None
    account.pending_totp_at = None
    account.last_totp_counter = -1
    db.query(RecoveryCode).filter(RecoveryCode.user_id == account.id).delete()
    revoke_sessions(db, account.id, ctx.session.token_hash)
    rotate(ctx, account, mfa=False)
    audit(db, account, "mfa.disabled", "Disabled two-factor authentication.")
    return redirect(ctx, "/account/security", "Two-factor authentication has been disabled.")

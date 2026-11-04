import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .database import commit, get_db
from .models import AccountToken, User, utcnow
from .notifications import account_email, email_ready, invalidate_tokens, password_notice
from .security import (audit, authenticated, context, digest, email_field, hash_password, read_form,
                       request_ip, revoke_sessions, rotate, throttle, verify_factor)
from .ui import redirect, render

router = APIRouter()
GENERIC_RESET = "If an active account matches that email, a password reset link will be sent. Check your inbox and spam folder."


def public_page(ctx, name, **values):
    return render(ctx, name, user=None, limited=False, **values)


def action_token(db, raw, purposes, lock=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
        raise HTTPException(404, "This account link is invalid, expired, or already used. Request a new email.")
    record = db.get(AccountToken, digest(raw))
    if not record or record.purpose not in purposes:
        raise HTTPException(404, "This account link is invalid, expired, or already used. Request a new email.")
    # Always lock User before AccountToken, matching issuance and factor checks.
    query = select(User).where(User.id == record.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    user = db.scalar(query)
    if lock:
        record = db.scalar(select(AccountToken).where(AccountToken.token_hash == record.token_hash)
                           .with_for_update().execution_options(populate_existing=True))
    if (not record or record.used_at or record.expires_at <= utcnow() or not user or not user.active
            or user.email != record.email or record.purpose not in purposes
            or record.purpose in {"reset", "setup"} and record.password_digest != digest(user.password_hash)):
        raise HTTPException(404, "This account link is invalid, expired, or already used. Request a new email.")
    return record, user


@router.get("/forgot-password")
async def forgot_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    return public_page(ctx, "forgot_password.html", title="Forgot password")


@router.post("/forgot-password")
async def forgot_password(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    throttle("reset-ip", request_ip(request), 10, 15)
    email = email_field(form)
    throttle("reset-email", email, 3, 60)
    user = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
    if user and email_ready(db):
        account_email(db, user, "reset")
    commit(db)
    return public_page(ctx, "forgot_password.html", title="Check your email", notice=GENERIC_RESET)


@router.get("/reset-password/{token}")
async def reset_page(token: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    throttle("reset-link-ip", request_ip(request), 60, 15)
    _, account = action_token(db, token, {"reset", "setup"})
    return public_page(ctx, "reset_password.html", title="Choose a new password", token=token, needs_mfa=account.totp_enabled)


@router.post("/reset-password/{token}")
async def reset_password(token: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    throttle("reset-link-ip", request_ip(request), 60, 15)
    if form.get("new_password") != form.get("confirm_password"):
        raise HTTPException(422, "The new passwords do not match.")
    encoded = await run_in_threadpool(hash_password, str(form.get("new_password", "")))
    record, account = action_token(db, token, {"reset", "setup"}, lock=True)
    if account.totp_enabled:
        throttle("reset-factor", str(account.id), 8, 5)
        if not verify_factor(db, account, str(form.get("code", ""))):
            raise HTTPException(403, "Enter a fresh authenticator code or an unused recovery code.")
    record.used_at = utcnow()
    account.password_hash, account.must_change_password = encoded, False
    account.email_verified_at, account.email_verification_required = utcnow(), False
    invalidate_tokens(db, account.id)
    # Never authenticate through recovery; normal login and MFA still apply.
    if ctx.user and ctx.user.id == account.id:
        rotate(ctx, phase="anonymous")
    revoke_sessions(db, account.id)
    audit(db, account, "password.recovered", "Reset their password through a single-use email link; existing two-factor settings remain in place.")
    password_notice(db, account)
    commit(db)
    return public_page(ctx, "account_link_done.html", title="Password changed", message="Your password has been changed. Sign in with your new password and your authenticator if enabled.")


@router.get("/account/verify-email")
async def verification_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx, allow_setup=True)
    return render(ctx, "verify_email_request.html", title="Verify your email", verified=bool(account.email_verified_at), delivery_ready=email_ready(db))


@router.post("/account/verify-email")
async def resend_verification(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx, allow_setup=True)
    await read_form(ctx)
    throttle("verify-resend", str(account.id), 3, 15)
    if account.email_verified_at:
        return redirect(ctx, "/account/verify-email", "Your email address is already verified.")
    if not email_ready(db):
        raise HTTPException(503, "Email delivery is unavailable. Contact an Admin for help with account access.")
    account_email(db, account)
    return redirect(ctx, "/account/verify-email", "A new verification email has been queued. Earlier verification links no longer work.")


@router.get("/verify-email/{token}")
async def verify_page(token: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    throttle("verify-link-ip", request_ip(request), 60, 15)
    action_token(db, token, {"verify"})
    return public_page(ctx, "verify_email_confirm.html", title="Confirm your email", token=token)


@router.post("/verify-email/{token}")
async def verify_email(token: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    await read_form(ctx)
    throttle("verify-link-ip", request_ip(request), 60, 15)
    record, account = action_token(db, token, {"verify"}, lock=True)
    record.used_at = utcnow()
    account.email_verified_at, account.email_verification_required = utcnow(), False
    invalidate_tokens(db, account.id, ("verify",))
    audit(db, account, "email.verified", "Confirmed ownership of their current email address.")
    commit(db)
    destination = ctx.session.next_path if ctx.user and ctx.user.id == account.id and ctx.session.phase == "authenticated" else "/login"
    return public_page(ctx, "account_link_done.html", title="Email verified", message="Your email address is verified. Continue to your workspace, or sign in on this device.", continue_path=destination)

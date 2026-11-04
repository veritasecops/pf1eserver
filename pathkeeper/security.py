import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .config import settings
from .database import commit, engine
from .models import AuditEvent, Campaign, Character, Guard, Membership, RateLimit, RecoveryCode, User, WebSession, utcnow

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(24))
ROLES = {"player": "Player", "gm": "Game Master", "admin": "Admin"}
COOKIE = "pathkeeper_session"


class RedirectTo(Exception):
    def __init__(self, path="/login"):
        self.path = path


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_ok(password: str, encoded: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def hash_password(value: str) -> str:
    if not 12 <= len(value) <= 128:
        raise HTTPException(422, "Use a password between 12 and 128 characters.")
    return PASSWORDS.hash(value)


def cipher():
    return Fernet(settings().encryption_key.encode())


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return cipher().decrypt(value.encode()).decode()


@dataclass
class Context:
    request: Request
    db: Session
    session: WebSession
    user: User | None


def new_session(request, db, user=None, phase="anonymous", mfa=False, next_path="/"):
    token = secrets.token_urlsafe(32)
    lifetime = 300 if phase == "mfa" else settings().session_hours * 3600 if user else 3600
    record = WebSession(token_hash=digest(token), user_id=user.id if user else None,
                        csrf=secrets.token_urlsafe(32), phase=phase, mfa_verified=mfa,
                        expires_at=utcnow() + timedelta(seconds=lifetime), next_path=next_path)
    db.add(record)
    db.flush()
    request.state.issue_cookie = token
    request.state.cookie_lifetime = lifetime
    return record


def context(request: Request, db: Session) -> Context:
    if hasattr(request.state, "context"):
        return request.state.context
    raw = request.cookies.get(COOKIE, "")
    record = db.get(WebSession, digest(raw)) if raw else None
    now = utcnow()
    if record and (record.expires_at <= now or record.last_seen < now - timedelta(minutes=settings().idle_minutes)):
        db.delete(record)
        record = None
    account = db.get(User, record.user_id) if record and record.user_id else None
    if record and record.user_id and (not account or not account.active):
        db.delete(record)
        record = None
        account = None
    if not record:
        db.execute(delete(WebSession).where(WebSession.expires_at < now))
        record = new_session(request, db)
        commit(db)
    elif record.last_seen < now - timedelta(minutes=2):
        record.last_seen = now
        commit(db)
    result = Context(request, db, record, account)
    request.state.context = result
    return result


def rotate(ctx, user=None, phase="authenticated", mfa=False):
    destination = ctx.session.next_path
    ctx.db.delete(ctx.session)
    ctx.session = new_session(ctx.request, ctx.db, user, phase, mfa, destination)
    ctx.user = user


def authenticated(ctx: Context, allow_setup=False) -> User:
    if not ctx.user or ctx.session.phase != "authenticated":
        raise RedirectTo("/login")
    if ctx.user.totp_enabled and not ctx.session.mfa_verified:
        ctx.db.delete(ctx.session)
        commit(ctx.db)
        ctx.request.state.clear_cookie = True
        raise RedirectTo("/login")
    if not allow_setup:
        if ctx.user.must_change_password:
            raise RedirectTo("/account/password")
        if (ctx.user.totp_required or ctx.user.role == "admin") and not ctx.user.totp_enabled:
            raise RedirectTo("/account/security")
        if ctx.user.email_verification_required and not ctx.user.email_verified_at:
            raise RedirectTo("/account/verify-email")
    return ctx.user


def administrator(ctx):
    account = authenticated(ctx)
    if account.role != "admin":
        raise HTTPException(403, "Only an Admin can open Administration.")
    return account


async def read_form(ctx):
    form = await ctx.request.form(max_files=0, max_fields=80, max_part_size=65536)
    supplied = str(form.get("csrf", ""))
    if not hmac.compare_digest(supplied.encode(), ctx.session.csrf.encode()):
        raise HTTPException(403, "Your session changed. Reload the form and try again.")
    return form


def field(form, key, max_length=150, required=True):
    value = form.get(key, "")
    if not isinstance(value, str):
        raise HTTPException(422, f"Enter a valid {key.replace('_', ' ')}.")
    value = value.strip()
    if required and not value:
        raise HTTPException(422, f"{key.replace('_', ' ').capitalize()} is required.")
    if len(value) > max_length:
        raise HTTPException(422, f"{key.replace('_', ' ').capitalize()} must be {max_length} characters or fewer.")
    return value


def email_field(form):
    from email_validator import EmailNotValidError, validate_email
    try:
        return validate_email(field(form, "email", 190).lower(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(422, "Enter a valid email address.") from None


def integer(form, key, minimum, maximum):
    try:
        value = int(form.get(key, ""))
    except (TypeError, ValueError):
        raise HTTPException(422, f"{key} must be a whole number.") from None
    if not minimum <= value <= maximum:
        raise HTTPException(422, f"{key} must be between {minimum} and {maximum}.")
    return value


def flash(ctx, message, kind="success"):
    ctx.session.flash = {"message": message, "kind": kind}


def audit(db, actor, event, detail):
    db.add(AuditEvent(actor_id=actor.id if actor else None, event=event, detail=detail[:500]))


def throttle(scope, identifier, maximum=10, minutes=15):
    key = digest(f"{scope}:{identifier}")
    now = utcnow()
    cutoff = now - timedelta(minutes=minutes)
    with Session(engine()) as db:
        statement = insert(RateLimit).values(bucket=key, attempts=1, window_start=now)
        statement = statement.on_duplicate_key_update(
            attempts=case((RateLimit.window_start < cutoff, 1), else_=RateLimit.attempts + 1),
            window_start=case((RateLimit.window_start < cutoff, now), else_=RateLimit.window_start))
        db.execute(statement)
        db.commit()
        attempts = db.get(RateLimit, key).attempts
        if attempts > maximum:
            raise HTTPException(429, f"Too many attempts. Try again in {minutes} minutes.")


def request_ip(request):
    return request.client.host if request.client else "unknown"


def verify_factor(db, account, supplied):
    """Caller locks the user row; successful codes are consumed in that transaction."""
    supplied = supplied.strip()
    if account.totp_enabled and account.totp_secret and re.fullmatch(r"[0-9]{6}", supplied):
        totp = pyotp.TOTP(decrypt(account.totp_secret))
        import time
        counter = int(time.time()) // totp.interval
        for candidate in (counter, counter - 1, counter + 1):
            if candidate > account.last_totp_counter and hmac.compare_digest(totp.at(candidate * totp.interval), supplied):
                account.last_totp_counter = candidate
                return True
    normalized = re.sub(r"[\s-]", "", supplied).lower()
    if re.fullmatch(r"[a-f0-9]{20}", normalized):
        record = db.scalar(select(RecoveryCode).where(RecoveryCode.user_id == account.id, RecoveryCode.code_hash == digest(normalized)).with_for_update())
        if record:
            db.delete(record)
            return True
    return False


def make_recovery_codes(db, user_id):
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = []
    for _ in range(10):
        raw = secrets.token_hex(10)
        codes.append("-".join(raw[i:i + 5] for i in range(0, 20, 5)))
        db.add(RecoveryCode(user_id=user_id, code_hash=digest(raw)))
    return codes


async def reauthenticate(ctx, form):
    throttle("reauth", str(ctx.user.id), 8, 5)
    locked = ctx.db.scalar(select(User).where(User.id == ctx.user.id).with_for_update().execution_options(populate_existing=True))
    if not locked or not locked.active:
        raise HTTPException(403, "This account is no longer available.")
    if not await run_in_threadpool(password_ok, str(form.get("current_password", "")), locked.password_hash):
        raise HTTPException(403, "Your current password is incorrect.")
    if locked.totp_enabled and not verify_factor(ctx.db, locked, str(form.get("code", ""))):
        raise HTTPException(403, "Enter a fresh authenticator code or an unused recovery code.")
    return locked


def revoke_sessions(db, user_id, except_hash=None):
    query = delete(WebSession).where(WebSession.user_id == user_id)
    if except_hash:
        query = query.where(WebSession.token_hash != except_hash)
    db.execute(query)


def protect_last_admin(db, target, new_role=None, new_active=None, deleting=False):
    db.execute(select(Guard).where(Guard.id == 1).with_for_update())
    active_admins = list(db.scalars(select(User).where(User.role == "admin", User.active.is_(True)).with_for_update()))
    if target.role == "admin" and target.active and (deleting or new_role != "admin" or not new_active) and len(active_admins) <= 1:
        raise HTTPException(409, "Keep at least one active Admin account.")


def can_manage_campaign(account, campaign):
    return account.role == "admin" or account.role == "gm" and campaign.owner_id == account.id


def is_member(db, account, campaign):
    return account.role == "admin" or campaign.owner_id == account.id or db.get(Membership, (campaign.id, account.id)) is not None


def get_campaign(ctx, campaign_id, manage=False):
    account = authenticated(ctx)
    record = ctx.db.get(Campaign, campaign_id)
    if not record or not is_member(ctx.db, account, record):
        raise HTTPException(404, "Campaign not found.")
    if manage and not can_manage_campaign(account, record):
        raise HTTPException(403, "Only the campaign's Game Master or an Admin can change it.")
    return record


def can_delete_character(account, character):
    return account.role == "admin" or character.owner_id == account.id


def can_manage_character(db, account, character):
    if account.role == "admin" or character.owner_id == account.id:
        return True
    if account.role != "gm" or character.campaign_id is None:
        return False
    campaign = db.get(Campaign, character.campaign_id)
    return bool(campaign and campaign.owner_id == account.id and
                (character.owner_id == campaign.owner_id or db.get(Membership, (campaign.id, character.owner_id))))


def get_character(ctx, character_id):
    account = authenticated(ctx)
    record = ctx.db.get(Character, character_id)
    if not record or not can_manage_character(ctx.db, account, record):
        raise HTTPException(404, "Character not found.")
    return record

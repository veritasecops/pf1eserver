"""Transactional notifications and single-use account links, committed with app actions."""
from datetime import timedelta
import ipaddress
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import select, update

from .models import AccountToken, EmailConfiguration, EmailDelivery, EmailOutbox, User, utcnow
from .security import digest, encrypt


def normalize_base_url(value):
    value = value.strip()
    if not value:
        return ""
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment or url.port == 0
                or any(char.isspace() or ord(char) < 32 for char in value)):
            raise ValueError
        host = url.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            ipaddress.IPv6Address(host)
            host = f"[{host}]"
        elif not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.rstrip(".").split(".")):
            raise ValueError
        netloc = host + (f":{url.port}" if url.port else "")
        result = urlunsplit((url.scheme, netloc, "", "", ""))
        if len(result) > 300:
            raise ValueError
        return result
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Use an Application Base URL such as https://table.example.com, without a path, credentials, query, or fragment.") from None


def email_ready(db):
    config = db.get(EmailConfiguration, 1)
    return bool(config and config.enabled and config.public_base_url)


def application_link(db, path):
    config = db.get(EmailConfiguration, 1)
    return config.public_base_url + path if config and config.public_base_url else path


def invalidate_tokens(db, user_id, purposes=None):
    query = update(AccountToken).where(AccountToken.user_id == user_id, AccountToken.used_at.is_(None))
    if purposes:
        query = query.where(AccountToken.purpose.in_(purposes))
    db.execute(query.values(used_at=utcnow()))


def enqueue(db, recipient, purpose, subject, text, actor_id=None, token_hash=None, invitation_id=None):
    config = db.get(EmailConfiguration, 1)
    if not email_ready(db):
        return False
    delivery = EmailDelivery(actor_id=actor_id, recipient=recipient, provider=config.provider,
                             configuration_version=config.version, purpose=purpose, status="queued",
                             detail="Queued for the email worker.")
    db.add(delivery)
    db.flush()
    db.add(EmailOutbox(delivery_id=delivery.id, subject=subject, encrypted_body=encrypt(text),
                       token_hash=token_hash, invitation_id=invitation_id))
    return True


def account_email(db, account, purpose="verify", actor_id=None):
    if not account.active or not email_ready(db):
        return False
    # Serializes issuance with password/email changes and token consumption.
    account = db.scalar(select(User).where(User.id == account.id).with_for_update().execution_options(populate_existing=True))
    invalidate_tokens(db, account.id, ("verify",) if purpose == "verify" else ("reset", "setup"))
    token = secrets.token_urlsafe(32)
    hours = 1 if purpose == "reset" else 24
    record = AccountToken(token_hash=digest(token), user_id=account.id, email=account.email, purpose=purpose,
                          password_digest=digest(account.password_hash), expires_at=utcnow() + timedelta(hours=hours))
    db.add(record)
    db.flush()
    if purpose == "verify":
        subject = "Welcome to Pathkeeper. Verify your email"
        action = "Confirm your email address to finish setting up your account"
        path = f"/verify-email/{token}"
    elif purpose == "setup":
        subject = "Your Pathkeeper account is ready"
        action = "Choose your own password and confirm your email address"
        path = f"/reset-password/{token}"
    else:
        subject = "Reset your Pathkeeper password"
        action = "Reset your password"
        path = f"/reset-password/{token}"
    text = (f"Hello {account.name},\n\n{action}:\n\n{application_link(db, path)}\n\n"
            f"This link expires in {hours} hour{'s' if hours != 1 else ''} and can be used once.\n"
            "Your authenticator remains required if already enabled.\n\n"
            "If you did not expect this message, ignore it or contact your instance administrator.\n")
    return enqueue(db, account.email, purpose, subject, text, actor_id, token_hash=record.token_hash)


def password_notice(db, account):
    return enqueue(db, account.email, "password_changed", "Your Pathkeeper password changed",
                   "Your Pathkeeper password was changed and previous sessions were signed out.\n\n"
                   "If you did not make this change, contact your instance administrator immediately.\n"
                   "Your authenticator settings have not been removed.\n", account.id)


def invitation_email(db, invitation, campaign, token, actor):
    return enqueue(db, invitation.email, "invitation", "Pathkeeper campaign invitation",
                   f"{actor.name} invited you to {campaign.name}.\n\n"
                   f"Open this link to sign in or create a Player account, then accept the invitation:\n\n"
                   f"{application_link(db, '/join/' + token)}\n\n"
                   f"Use the account email {invitation.email}. This invitation expires in seven days and can be used once.\n",
                   actor.id, invitation_id=invitation.id)

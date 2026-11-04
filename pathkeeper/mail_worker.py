"""Durable outbox worker. An uncertain delivery is recorded, never retried blindly."""
import signal
import threading

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import engine
from .email_delivery import DeliveryResult, DeliverySettings, send_email
from .models import AccountToken, EmailConfiguration, EmailDelivery, EmailOutbox, Invitation, User, utcnow
from .security import decrypt, digest


def discard_reason(db, delivery, item):
    if delivery.purpose in {"verify", "reset", "setup"}:
        token = db.get(AccountToken, item.token_hash) if item.token_hash else None
        user = db.get(User, token.user_id) if token else None
        if not token or token.used_at or token.expires_at <= utcnow() or not user or not user.active or user.email != token.email:
            return "The account link expired or is no longer valid; this email was not sent."
        if token.purpose != "verify" and token.password_digest != digest(user.password_hash):
            return "The password changed after this link was created; this email was not sent."
    elif delivery.purpose == "invitation":
        invite = db.get(Invitation, item.invitation_id) if item.invitation_id else None
        if not invite or invite.revoked or invite.accepted_at or invite.expires_at <= utcnow():
            return "The invitation is no longer valid; this email was not sent."
    return None


def process_one():
    with Session(engine(), expire_on_commit=False) as db:
        row = db.execute(select(EmailDelivery, EmailOutbox).join(EmailOutbox)
                         .where(EmailDelivery.status == "queued").order_by(EmailDelivery.id)
                         .limit(1).with_for_update(skip_locked=True)).first()
        if not row:
            return False
        delivery, item = row
        config = db.get(EmailConfiguration, 1)
        reason = discard_reason(db, delivery, item)
        if not config or not config.enabled:
            reason = "Email delivery was disabled before this message could be sent."
        try:
            body = decrypt(item.encrypted_body) if not reason and item.encrypted_body else ""
        except InvalidToken:
            reason = "The queued message cannot be decrypted. Restore the matching instance key or request a new email."
            body = ""
        if not reason and not body:
            reason = "The queued message body is unavailable. Request a new email."
        if reason:
            delivery.status, delivery.detail, delivery.completed_at = "failed", reason, utcnow()
            item.encrypted_body = None
            db.commit()
            return True
        snapshot = DeliverySettings.from_record(config)
        delivery.provider, delivery.configuration_version = config.provider, config.version
        delivery.status, delivery.detail = "pending", "Sending once. Check provider activity before resending if this remains pending."
        delivery_id, recipient, subject = delivery.id, delivery.recipient, item.subject
        db.commit()
    # No database transaction or row lock spans the provider request.
    try:
        result = send_email(snapshot, recipient, subject, body)
    except Exception:
        # Provider libraries must not leak request credentials or message tokens into logs.
        result = DeliveryResult("unknown", "The provider request was interrupted. Check provider activity before requesting another email.")
    with Session(engine()) as db:
        delivery, item = db.get(EmailDelivery, delivery_id), db.get(EmailOutbox, delivery_id)
        if delivery:
            delivery.status, delivery.detail, delivery.message_id = result.status, result.detail, result.message_id
            delivery.completed_at = utcnow()
        if item:
            item.encrypted_body = None
        db.commit()
    return True


def recover_interrupted():
    with Session(engine()) as db:
        for delivery, item in db.execute(select(EmailDelivery, EmailOutbox).join(EmailOutbox).where(EmailDelivery.status == "pending")):
            delivery.status = "unknown"
            delivery.detail = "The email worker restarted during delivery. Check provider activity before requesting another email."
            delivery.completed_at = utcnow()
            item.encrypted_body = None
        db.commit()


def main():
    stopped = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stopped.set())
    recover_interrupted()
    while not stopped.is_set():
        try:
            worked = process_one()
        except Exception:
            # No exception text: a database/driver error can include private parameters.
            print("Email worker could not complete a database operation; it will reconnect.", flush=True)
            stopped.wait(5)
        else:
            if not worked:
                stopped.wait(1)


if __name__ == "__main__":
    main()

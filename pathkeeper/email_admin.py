import ipaddress
import re

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .database import commit, get_db
from .email_delivery import DeliverySettings, send_email
from .models import EmailConfiguration, EmailDelivery, utcnow
from .notifications import normalize_base_url
from .security import administrator, audit, context, encrypt, field, integer, read_form, reauthenticate, throttle
from .ui import redirect, render

router = APIRouter(prefix="/administration/email")
PUBLIC_FIELDS = ("enabled", "provider", "public_base_url", "sender_name", "sender_email", "reply_to", "smtp_host",
                 "smtp_port", "smtp_security", "smtp_username", "version")


def configuration(db):
    record = db.get(EmailConfiguration, 1)
    if not record:
        raise HTTPException(503, "Email configuration is not initialized. Ask the server operator to run the documented migration.")
    return record


def public_values(record):
    return {name: getattr(record, name) for name in PUBLIC_FIELDS}


def email_address(value, required=False):
    if not value and not required:
        return ""
    try:
        address = validate_email(value, check_deliverability=False, allow_smtputf8=False).ascii_email
        if len(address) > 190:
            raise ValueError
        return address.lower()
    except (EmailNotValidError, ValueError):
        raise HTTPException(422, "Enter a valid sender, reply-to, or recipient email address.") from None


def valid_host(value):
    if not value:
        return ""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        value = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise HTTPException(422, "Enter a relay hostname or IP address, without a URL or port.") from None
    if len(value) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in value.rstrip(".").split(".")):
        raise HTTPException(422, "Enter a relay hostname or IP address, without a URL or port.")
    return value


def validate_settings(form, record):
    values = {"enabled": form.get("enabled") == "on", "provider": field(form, "provider", 10),
              "public_base_url": normalize_base_url(field(form, "public_base_url", 300, False)),
              "sender_name": field(form, "sender_name", 100), "sender_email": email_address(field(form, "sender_email", 190, False)),
              "reply_to": email_address(field(form, "reply_to", 190, False)),
              "smtp_host": valid_host(field(form, "smtp_host", 253, False)),
              "smtp_port": integer(form, "smtp_port", 1, 65535),
              "smtp_security": field(form, "smtp_security", 10),
              "smtp_username": field(form, "smtp_username", 254, False)}
    if values["provider"] not in {"brevo", "smtp"} or values["smtp_security"] not in {"starttls", "ssl", "none"}:
        raise HTTPException(422, "Choose a supported provider and SMTP connection security.")
    if any(ord(char) < 32 or ord(char) == 127 for key in ("sender_name", "smtp_username") for char in values[key]):
        raise HTTPException(422, "Sender name and SMTP username must not contain control characters.")
    secrets = {}
    for name, existing, maximum in (("brevo_key", record.brevo_key, 4096), ("smtp_password", record.smtp_password, 1024)):
        value = form.get(name, "")
        if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
            raise HTTPException(422, "The supplied provider credential is invalid or too long.")
        clear = form.get(f"clear_{name}") == "on"
        if value and clear:
            raise HTTPException(422, "Choose either replacing or removing a saved credential.")
        if name == "brevo_key" and value and not re.fullmatch(r"[!-~]+", value):
            raise HTTPException(422, "The Brevo API key must contain visible ASCII characters without spaces.")
        secrets[name] = encrypt(value) if value else None if clear else existing
    if values["enabled"]:
        if not values["public_base_url"]:
            raise HTTPException(422, "Set the Application Base URL before enabling email delivery.")
        if not values["sender_email"]:
            raise HTTPException(422, "A sender email is required to enable delivery.")
        if values["provider"] == "brevo" and not secrets["brevo_key"]:
            raise HTTPException(422, "Save a Brevo API key before enabling Brevo delivery.")
        if values["provider"] == "smtp":
            if not values["smtp_host"]:
                raise HTTPException(422, "Save an SMTP relay host before enabling SMTP delivery.")
            if values["smtp_username"] and not secrets["smtp_password"]:
                raise HTTPException(422, "Enter the SMTP password or relay key for this username.")
            if values["smtp_username"] and values["smtp_security"] == "none":
                raise HTTPException(422, "Select STARTTLS or TLS before using SMTP authentication.")
    return values, secrets


def page(ctx, record, error=None, values=None, status=200, notice=None):
    deliveries = list(ctx.db.scalars(select(EmailDelivery).order_by(EmailDelivery.id.desc()).limit(25)))
    response = render(ctx, "email_configuration.html", title="Email Configuration", config=values or public_values(record),
                      has_brevo_key=bool(record.brevo_key), has_smtp_password=bool(record.smtp_password),
                      deliveries=deliveries, updated_at=record.updated_at, error=error, notice=notice)
    response.status_code = status
    return response


@router.get("")
async def email_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return page(ctx, configuration(db))


@router.post("")
async def save_configuration(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    admin = administrator(ctx)
    form = await read_form(ctx)
    record = configuration(db)
    if integer(form, "version", 1, 2147483647) != record.version:
        raise HTTPException(409, "Email settings changed in another window. Reload before saving.")
    try:
        values, secrets = validate_settings(form, record)
    except HTTPException as error:
        safe = {name: str(form.get(name, ""))[:300] for name in PUBLIC_FIELDS}
        safe["enabled"] = form.get("enabled") == "on"
        return page(ctx, record, error.detail, safe, error.status_code)
    await reauthenticate(ctx, form)
    administrator(ctx)
    for name, value in {**values, **secrets}.items():
        setattr(record, name, value)
    record.updated_by = admin.id
    record.updated_at = utcnow()
    audit(db, admin, "email.configuration_updated", f"Email delivery {'enabled' if record.enabled else 'disabled'} using {record.provider}. Provider credentials are hidden.")
    return redirect(ctx, "/administration/email", "Email settings saved. Use Send test email to check the saved configuration.")


@router.post("/test")
async def test_email(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    admin = administrator(ctx)
    form = await read_form(ctx)
    throttle("email-test", str(admin.id), 5, 15)
    recipient = email_address(field(form, "recipient", 190), required=True)
    record = configuration(db)
    if integer(form, "version", 1, 2147483647) != record.version:
        raise HTTPException(409, "Email settings changed. Reload before sending a test.")
    if not record.enabled:
        return page(ctx, record, "Enable and save email delivery before sending a test.", status=422)
    snapshot = DeliverySettings.from_record(record)
    delivery = EmailDelivery(actor_id=admin.id, recipient=recipient, provider=record.provider,
                             configuration_version=record.version, purpose="test", status="pending",
                             detail="Sending once. If this stays pending, check provider activity before resending.")
    db.add(delivery)
    commit(db)
    # Commit first: neither the DB connection nor account locks span network I/O.
    result = await run_in_threadpool(send_email, snapshot, recipient, "Pathkeeper email configuration test",
                                     "This test email was requested by an Admin in Pathkeeper.\n\n"
                                     "If you received this message, your saved email configuration reached this inbox.\n"
                                     "No account password or authenticator information is included.\n")
    delivery.status, delivery.detail, delivery.message_id = result.status, result.detail, result.message_id
    delivery.completed_at = utcnow()
    audit(db, admin, "email.test_" + result.status, f"Test via {delivery.provider}: {result.detail}")
    commit(db)
    return page(ctx, configuration(db), error=None if result.status == "accepted" else result.detail,
                notice=result.detail if result.status == "accepted" else None)

"""One delivery interface for Brevo and SMTP. Never log provider responses or secrets."""
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
import json
from http.client import HTTPException as HTTPClientError
import smtplib
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from cryptography.fernet import InvalidToken

from .security import decrypt

TIMEOUT = 10
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class DeliverySettings:
    enabled: bool
    provider: str
    sender_name: str
    sender_email: str
    reply_to: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_username: str
    brevo_key: str | None = field(repr=False)
    smtp_password: str | None = field(repr=False)

    @classmethod
    def from_record(cls, record):
        return cls(**{name: getattr(record, name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    detail: str
    message_id: str = ""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An API key must never follow a provider redirect to another endpoint.
        return None


def open_brevo(request):
    return build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=TIMEOUT)


def send_email(config: DeliverySettings, recipient: str, subject: str, text: str) -> DeliveryResult:
    """Send once, without retries. Call in a worker thread after committing DB state.

    The caller supplies validated recipient/subject/content and records the result.
    'accepted' means provider handoff, not inbox delivery. 'unknown' must not be retried blindly.
    """
    if not config.enabled:
        return DeliveryResult("failed", "Email delivery is disabled.")
    if any("\r" in value or "\n" in value for value in (recipient, subject, config.sender_name, config.sender_email, config.reply_to)):
        return DeliveryResult("failed", "Email headers contain an invalid line break.")
    if config.provider == "brevo":
        return send_brevo(config, recipient, subject, text)
    if config.provider == "smtp":
        return send_smtp(config, recipient, subject, text)
    return DeliveryResult("failed", "Choose a supported email provider.")


def send_brevo(config, recipient, subject, text):
    if not config.brevo_key or not config.sender_email:
        return DeliveryResult("failed", "Save a sender email and Brevo API key first.")
    try:
        key = decrypt(config.brevo_key)
    except InvalidToken:
        return DeliveryResult("failed", "The saved API key cannot be decrypted. Re-enter it or restore the matching instance encryption key.")
    payload = {"sender": {"name": config.sender_name, "email": config.sender_email},
               "to": [{"email": recipient}], "subject": subject, "textContent": text}
    if config.reply_to:
        payload["replyTo"] = {"email": config.reply_to}
    request = Request(BREVO_URL, data=json.dumps(payload).encode(), method="POST",
                      headers={"api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with open_brevo(request) as response:
            if response.status != 201:
                return DeliveryResult("unknown", "Brevo returned an unexpected response. Check its activity log before resending.")
            try:
                result = json.loads(response.read(65536))
                message_id = result.get("messageId", "") if isinstance(result, dict) else ""
                if not isinstance(message_id, str) or not message_id:
                    raise ValueError
            except (ValueError, UnicodeError):
                return DeliveryResult("accepted", "Brevo accepted the message without a readable message ID.")
            return DeliveryResult("accepted", "Brevo accepted the message for delivery.", message_id[:255])
    except HTTPError as error:
        status = error.code
        error.close()
        if status in {401, 403}:
            detail = "Brevo rejected the API credentials or account access. Check your API key and account permissions."
        elif status == 429:
            detail = "Brevo's sending limit was reached. Check your account quota before trying again."
        elif status in {400, 404, 422}:
            detail = "Brevo rejected the message. Check the verified sender, recipient, and transactional email settings."
        elif status >= 500:
            return DeliveryResult("unknown", "Brevo reported a service error. Check its activity log before resending.")
        else:
            detail = "Brevo rejected the request. Check your provider settings and account activity."
        return DeliveryResult("failed", detail)
    except (URLError, OSError, ValueError, HTTPClientError):
        return DeliveryResult("unknown", "The Brevo request could not be completed. Check network access and provider activity before resending.")


def send_smtp(config, recipient, subject, text):
    if not config.sender_email or not config.smtp_host or config.smtp_security not in {"starttls", "ssl", "none"}:
        return DeliveryResult("failed", "Save a valid sender and SMTP relay first.")
    if config.smtp_username and (not config.smtp_password or config.smtp_security == "none"):
        return DeliveryResult("failed", "SMTP authentication requires a saved password and TLS.")
    message = EmailMessage()
    message["From"] = formataddr((config.sender_name, config.sender_email))
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=config.sender_email.rsplit("@", 1)[-1])
    if config.reply_to:
        message["Reply-To"] = config.reply_to
    message.set_content(text)
    smtp = None
    transmitting = False
    try:
        password = decrypt(config.smtp_password) if config.smtp_username else None
        if config.smtp_security == "ssl":
            smtp = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=TIMEOUT, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=TIMEOUT)
        smtp.ehlo_or_helo_if_needed()
        if config.smtp_security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if config.smtp_username:
            smtp.login(config.smtp_username, password)
        transmitting = True
        refused = smtp.send_message(message, from_addr=config.sender_email, to_addrs=[recipient])
        if refused:
            return DeliveryResult("failed", "The SMTP relay rejected the recipient. Check relay permissions and recipient address.")
        return DeliveryResult("accepted", "The SMTP relay accepted the message for delivery.", str(message["Message-ID"])[:255])
    except InvalidToken:
        return DeliveryResult("failed", "The saved SMTP password cannot be decrypted. Re-enter it or restore the matching encryption key.")
    except smtplib.SMTPAuthenticationError:
        return DeliveryResult("failed", "SMTP authentication failed. Check the username and password or relay key.")
    except ssl.SSLError:
        return DeliveryResult("failed", "SMTP TLS verification failed. Check the relay hostname and certificate.")
    except smtplib.SMTPNotSupportedError:
        return DeliveryResult("failed", "The relay does not support the selected TLS or authentication method.")
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
        return DeliveryResult("failed", "The SMTP relay rejected the sender, recipient, or message. Check relay permissions.")
    except (OSError, ValueError):
        return DeliveryResult("unknown" if transmitting else "failed", "The SMTP connection failed. Check the host, port, network, and relay logs before resending.")
    finally:
        if smtp:
            # A failed QUIT must not turn an accepted send into an apparent failure.
            try:
                smtp.quit()
            except OSError:
                smtp.close()

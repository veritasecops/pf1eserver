from dataclasses import replace
import io
import json
import smtplib
import socketserver
import ssl
import threading
from urllib.error import HTTPError, URLError

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.email_delivery import DeliveryResult, DeliverySettings, send_email
from pathkeeper.models import AccountToken, AuditEvent, EmailConfiguration, EmailDelivery, EmailOutbox, SchemaMigration, User
from pathkeeper.security import decrypt, encrypt


def form(**extra):
    return {"version": 1, "enabled": "on", "provider": "brevo", "sender_name": "Pathkeeper",
            "public_base_url": "https://table.example.com",
            "sender_email": "keeper@example.com", "reply_to": "support@example.com",
            "brevo_key": "fixture-api-secret", "smtp_host": "", "smtp_port": 587,
            "smtp_security": "starttls", "smtp_username": "", **extra}


def snapshot(**extra):
    return DeliverySettings(**{"enabled": True, "provider": "brevo", "sender_name": "Pathkeeper",
            "sender_email": "keeper@example.com", "reply_to": "support@example.com",
            "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_security": "starttls",
            "smtp_username": "relay-user", "brevo_key": encrypt("fixture-api-secret"),
            "smtp_password": encrypt("fixture-smtp-secret"), **extra})


@pytest.mark.parametrize("role", ["player", "gm"])
def test_email_configuration_is_admin_only(env, role):
    c = env.login(env.player if role == "player" else env.gm)
    assert c.get("/administration/email").status_code == 403
    assert env.post(c, "/administration/email", form()).status_code == 403
    assert env.post(c, "/administration/email/test", {"recipient": "test@example.com", "version": 1}).status_code == 403


def test_save_requires_csrf_password_mfa_and_never_reflects_secrets(env):
    c = env.login(env.admin)
    assert env.post(c, "/administration/email", form(), use_csrf=False).status_code == 403
    assert env.post(c, "/administration/email", form(current_password="wrong")).status_code == 403
    assert env.post(c, "/administration/email", form(**env.confirm(env.admin))).status_code == 303
    page = c.get("/administration/email")
    assert page.status_code == 200 and "API key saved" in page.text
    assert "fixture-api-secret" not in page.text
    with Session(engine()) as db:
        record = db.get(EmailConfiguration, 1)
        assert record.enabled and record.version == 2 and record.updated_by == env.admin.id
        assert record.brevo_key != "fixture-api-secret" and decrypt(record.brevo_key) == "fixture-api-secret"
        assert "fixture-api-secret" not in " ".join(db.scalars(select(AuditEvent.detail)))
    assert "Email Configuration" in c.get("/administration").text
    assert 'aria-current="page">Email Configuration' in page.text


def test_provider_switch_preserves_credentials_and_clear_is_explicit(env):
    c = env.login(env.admin)
    assert env.post(c, "/administration/email", form(**env.confirm(env.admin))).status_code == 303
    assert env.post(c, "/administration/email", form(version=2, provider="smtp", brevo_key="", smtp_host="10.0.0.25",
        smtp_username="relay", smtp_password="smtp-secret", **env.confirm(env.admin))).status_code == 303
    with Session(engine()) as db:
        record = db.get(EmailConfiguration, 1)
        assert decrypt(record.brevo_key) == "fixture-api-secret" and decrypt(record.smtp_password) == "smtp-secret"
    assert "smtp-secret" not in c.get("/administration/email").text
    assert env.post(c, "/administration/email", form(version=3, enabled="", brevo_key="", clear_brevo_key="on",
        clear_smtp_password="on", **env.confirm(env.admin))).status_code == 303
    with Session(engine()) as db:
        record = db.get(EmailConfiguration, 1)
        assert not record.enabled and not record.brevo_key and not record.smtp_password


@pytest.mark.parametrize("values", [
    {"provider": "unknown"}, {"sender_email": "bad"}, {"reply_to": "bad"},
    {"smtp_host": "https://relay.example.com:587"}, {"smtp_port": 0},
    {"smtp_security": "invalid"}, {"sender_name": "Bad\r\nBcc: attacker@example.com"},
    {"brevo_key": ""}, {"clear_brevo_key": "on"},
    {"provider": "smtp", "smtp_host": ""},
    {"provider": "smtp", "smtp_host": "localhost", "smtp_username": "user", "smtp_password": ""},
    {"provider": "smtp", "smtp_host": "localhost", "smtp_username": "user", "smtp_password": "secret", "smtp_security": "none"},
])
def test_invalid_settings_do_not_save_or_echo_keys(env, values):
    c = env.login(env.admin)
    response = env.post(c, "/administration/email", form(**values))
    assert response.status_code == 422 and "fixture-api-secret" not in response.text
    with Session(engine()) as db:
        assert db.get(EmailConfiguration, 1).version == 1


def test_stale_settings_and_tests_are_rejected(env, monkeypatch):
    from pathkeeper import email_admin
    c = env.login(env.admin)
    assert env.post(c, "/administration/email", form(**env.confirm(env.admin))).status_code == 303
    assert env.post(c, "/administration/email", form()).status_code == 409
    monkeypatch.setattr(email_admin, "send_email", lambda *args: pytest.fail("Stale test must not send"))
    assert env.post(c, "/administration/email/test", {"version": 1, "recipient": "test@example.com"}).status_code == 409


def test_test_email_uses_saved_settings_records_result_and_throttles(env, monkeypatch):
    from pathkeeper import email_admin
    c = env.login(env.admin)
    assert env.post(c, "/administration/email/test", {"version": 1, "recipient": "test@example.com"}).status_code == 422
    assert env.post(c, "/administration/email", form(**env.confirm(env.admin))).status_code == 303
    calls = []
    def sender(config, recipient, subject, text):
        calls.append((config, recipient, subject, text))
        # Attempt is committed before external I/O; no body/credential stored.
        with Session(engine()) as db:
            assert db.scalar(select(EmailDelivery).order_by(EmailDelivery.id.desc())).status == "pending"
        return DeliveryResult("accepted", "Provider accepted the message.", "fixture-message-id")
    monkeypatch.setattr(email_admin, "send_email", sender)
    for _ in range(4):
        response = env.post(c, "/administration/email/test", {"version": 2, "recipient": "test@example.com", "brevo_key": "forged", "provider": "smtp"})
        assert response.status_code == 200 and "Provider accepted" in response.text
    assert len(calls) == 4 and calls[0][0].provider == "brevo"
    assert decrypt(calls[0][0].brevo_key) == "fixture-api-secret"
    assert "fixture-api-secret" not in repr(calls[0][0])
    assert env.post(c, "/administration/email/test", {"version": 2, "recipient": "test@example.com"}).status_code == 429
    with Session(engine()) as db:
        records = list(db.scalars(select(EmailDelivery)))
        assert len(records) == 4 and all(row.status == "accepted" and row.message_id == "fixture-message-id" for row in records)


def test_failed_delivery_history_redacts_provider_output(env, monkeypatch):
    from pathkeeper import email_admin
    c = env.login(env.admin)
    env.post(c, "/administration/email", form(**env.confirm(env.admin)))
    monkeypatch.setattr(email_admin, "send_email", lambda *args: DeliveryResult("unknown", "Check provider activity before resending."))
    response = env.post(c, "/administration/email/test", {"version": 2, "recipient": "test@example.com"})
    assert "Unknown" in response.text and "fixture-api-secret" not in response.text
    assert env.post(c, "/administration/email/test", {"version": 2, "recipient": "invalid"}).status_code == 422


def test_brevo_request_and_response_contract(env, monkeypatch):
    from pathkeeper import email_delivery
    class Response(io.BytesIO):
        status = 201
    captured = []
    def opener(request):
        captured.append(request)
        return Response(b'{"messageId":"<provider-id>"}')
    monkeypatch.setattr(email_delivery, "open_brevo", opener)
    result = send_email(snapshot(), "test@example.com", "Test subject", "A fixed test body")
    request = captured[0]
    assert request.full_url == "https://api.brevo.com/v3/smtp/email" and request.method == "POST"
    assert request.get_header("Api-key") == "fixture-api-secret"
    payload = json.loads(request.data)
    assert payload["textContent"] == "A fixed test body" and payload["replyTo"]["email"] == "support@example.com"
    assert payload["to"] == [{"email": "test@example.com"}]
    assert result.status == "accepted" and result.message_id == "<provider-id>"


@pytest.mark.parametrize("code,status", [(401, "failed"), (400, "failed"), (429, "failed"), (500, "unknown"), (302, "failed")])
def test_brevo_errors_never_leak_raw_response(env, monkeypatch, code, status):
    from pathkeeper import email_delivery
    def opener(request):
        raise HTTPError(request.full_url, code, "fixture-api-secret", {}, io.BytesIO(b'private provider body'))
    monkeypatch.setattr(email_delivery, "open_brevo", opener)
    result = send_email(snapshot(), "test@example.com", "Test", "Body")
    assert result.status == status and "fixture-api-secret" not in result.detail and "private provider body" not in result.detail


def test_brevo_transport_failure_is_uncertain_and_redirects_are_blocked(env, monkeypatch):
    from pathkeeper import email_delivery
    monkeypatch.setattr(email_delivery, "open_brevo", lambda request: (_ for _ in ()).throw(URLError("secret provider output")))
    result = send_email(snapshot(), "test@example.com", "Test", "Body")
    assert result.status == "unknown" and "secret provider output" not in result.detail
    assert email_delivery.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example.com") is None


@pytest.mark.parametrize("security", ["starttls", "ssl"])
def test_smtp_tls_authentication_and_quit_failure(env, monkeypatch, security):
    from pathkeeper import email_delivery
    calls = []
    class SMTP:
        def __init__(self, host, port, timeout, context=None):
            calls.append(("connect", host, port, timeout))
            if security == "ssl":
                assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        def ehlo_or_helo_if_needed(self): calls.append("hello")
        def starttls(self, context):
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            calls.append("starttls")
        def ehlo(self): calls.append("ehlo")
        def login(self, user, password):
            assert (user, password) == ("relay-user", "fixture-smtp-secret")
            calls.append("login")
        def send_message(self, message, from_addr, to_addrs):
            assert from_addr == "keeper@example.com" and to_addrs == ["test@example.com"]
            assert message["Reply-To"] == "support@example.com"
            assert "Body" in message.get_content()
            calls.append("send")
            return {}
        def quit(self): raise smtplib.SMTPServerDisconnected("secret failure after acceptance")
        def close(self): calls.append("close")
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", SMTP)
    result = send_email(snapshot(provider="smtp", smtp_security=security), "test@example.com", "Test", "Body")
    assert result.status == "accepted" and result.message_id
    if security == "starttls":
        assert calls.index("starttls") < calls.index("login") < calls.index("send")


def test_smtp_real_local_relay_protocol(env):
    messages = []
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 fixture SMTP\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command == b"DATA":
                    self.wfile.write(b"354 End with dot\r\n")
                    data = []
                    while (line := self.rfile.readline()) != b".\r\n":
                        if not line: return
                        data.append(line)
                    messages.append(b"".join(data))
                    self.wfile.write(b"250 queued\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 Bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 fixture\r\n")
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = snapshot(provider="smtp", smtp_host="127.0.0.1", smtp_port=server.server_address[1],
                              smtp_security="none", smtp_username="", smtp_password=None)
            result = send_email(config, "test@example.com", "Relay test", "A local test body")
            assert result.status == "accepted"
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert len(messages) == 1 and b"Subject: Relay test" in messages[0] and b"A local test body" in messages[0]


def test_disabled_email_bad_secrets_and_header_injection_do_not_send(env):
    config = snapshot()
    assert send_email(replace(config, enabled=False), "test@example.com", "Test", "Body").status == "failed"
    assert send_email(config, "test@example.com", "Test\r\nBcc: evil@example.com", "Body").status == "failed"
    assert send_email(replace(config, brevo_key="corrupt"), "test@example.com", "Test", "Body").status == "failed"


def test_email_migration_is_idempotent_and_preserves_existing_data(env, isolated_database):
    from pathkeeper.migrations import migrate
    with Session(engine()) as db:
        before = db.scalar(select(func.count()).select_from(EmailConfiguration))
        db.get(EmailConfiguration, 1).brevo_key = encrypt("preserved-fixture-key")
        db.commit()
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(EmailConfiguration)) == before == 1
        assert decrypt(db.get(EmailConfiguration, 1).brevo_key) == "preserved-fixture-key"
        assert db.get(SchemaMigration, 1).name == "email_configuration_and_delivery_history"


def test_upgrade_from_pre_email_schema_preserves_users(env, isolated_database):
    from pathkeeper.migrations import migrate
    for model in (EmailOutbox, AccountToken, EmailDelivery, EmailConfiguration, SchemaMigration):
        model.__table__.drop(isolated_database)
    # Use the default root connection isolation, just like the deployment CLI.
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 5
        record = db.get(EmailConfiguration, 1)
        assert record and not record.enabled and not record.brevo_key
        assert db.get(SchemaMigration, 1)

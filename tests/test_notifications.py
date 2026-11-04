from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import re

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.email_delivery import DeliveryResult
from pathkeeper.models import AccountToken, EmailConfiguration, EmailDelivery, EmailOutbox, Invitation, SchemaMigration, User, utcnow
from pathkeeper.notifications import account_email, invalidate_tokens, normalize_base_url
from pathkeeper.security import COOKIE, decrypt, digest, password_ok
from .conftest import PASSWORD
from .test_signup import signup_form
from .test_workspace import seed_campaign

NEW_PASSWORD = "A-new-secure-password-2026!"


@pytest.fixture
def mail(env):
    with Session(engine()) as db:
        config = db.get(EmailConfiguration, 1)
        config.enabled, config.public_base_url, config.sender_email = True, "https://table.example.com", "keeper@example.com"
        db.commit()
    return env


def latest_link(purpose, prefix):
    with Session(engine()) as db:
        row = db.execute(select(EmailDelivery, EmailOutbox).join(EmailOutbox).where(EmailDelivery.purpose == purpose)
                         .order_by(EmailDelivery.id.desc())).first()
        assert row
        body = decrypt(row[1].encrypted_body)
        token = re.search(prefix + r"/([A-Za-z0-9_-]{43})", body).group(1)
        return prefix + "/" + token, row[0].id


def request_reset(env, user):
    c = env.client()
    assert env.post(c, "/forgot-password", {"email": user.email}).status_code == 200
    return latest_link("reset", "/reset-password")[0]


def reset_form(**values):
    return {"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD, **values}


def test_signup_queues_welcome_verification_and_requires_confirmation(mail):
    c = mail.client()
    assert mail.post(c, "/signup", signup_form()).status_code == 303
    assert c.get("/").headers["location"] == "/account/verify-email"
    path, delivery_id = latest_link("verify", "/verify-email")
    raw = path.rsplit("/", 1)[1]
    with Session(engine()) as db:
        record = db.get(AccountToken, digest(raw))
        assert record and record.token_hash != raw and record.used_at is None
        item = db.get(EmailOutbox, delivery_id)
        assert "https://table.example.com" in decrypt(item.encrypted_body)
        assert raw not in item.encrypted_body
    # Mail scanners can open links without consuming them.
    assert c.get(path).status_code == 200 and c.get(path).headers["referrer-policy"] == "no-referrer"
    assert c.get("/").headers["location"] == "/account/verify-email"
    assert mail.post(c, path).status_code == 200
    assert c.get("/").status_code == 200
    assert mail.post(c, path).status_code == 404
    with Session(engine()) as db:
        account = db.scalar(select(User).where(User.email == "newplayer@example.com"))
        assert account.email_verified_at and not account.email_verification_required


def test_verification_resend_replaces_link_and_expires(mail):
    c = mail.login(mail.player)
    assert mail.post(c, "/account/verify-email").status_code == 303
    old, _ = latest_link("verify", "/verify-email")
    assert mail.post(c, "/account/verify-email").status_code == 303
    new, _ = latest_link("verify", "/verify-email")
    assert c.get(old).status_code == 404
    with Session(engine()) as db:
        db.get(AccountToken, digest(new.rsplit("/", 1)[1])).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert mail.post(c, new).status_code == 404


def test_reset_request_is_generic_for_active_missing_and_disabled(mail):
    c = mail.client()
    disabled = mail.add(active=False)
    responses = [mail.post(c, "/forgot-password", {"email": email}) for email in (mail.player.email, "missing@example.com", disabled.email)]
    assert all(response.status_code == 200 and "If an active account matches" in response.text for response in responses)
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(AccountToken)) == 1
        assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 1


def test_reset_revokes_sessions_marks_email_verified_and_keeps_login_separate(mail):
    existing = mail.login(mail.player)
    path = request_reset(mail, mail.player)
    c = mail.client()
    assert c.get(path).status_code == 200
    assert mail.post(c, path, reset_form()).status_code == 200
    assert existing.get("/").headers["location"] == "/login"
    assert c.get("/").headers["location"] == "/login"
    assert mail.post(c, path, reset_form()).status_code == 404
    with Session(engine()) as db:
        user = db.get(User, mail.player.id)
        assert password_ok(NEW_PASSWORD, user.password_hash) and user.email_verified_at
        assert not user.must_change_password
        assert db.scalar(select(EmailDelivery).where(EmailDelivery.purpose == "password_changed"))


def test_reset_of_current_signed_in_account_rotates_to_anonymous(mail):
    c = mail.login(mail.player)
    old = c.cookies[COOKIE]
    path = request_reset(mail, mail.player)
    assert mail.post(c, path, reset_form()).status_code == 200
    assert c.cookies[COOKIE] != old
    assert c.get("/").headers["location"] == "/login"


def test_reset_requires_mfa_and_preserves_authenticator(mail):
    path = request_reset(mail, mail.admin)
    c = mail.client()
    assert 'name="code"' in c.get(path).text
    assert mail.post(c, path, reset_form(code="wrong")).status_code == 403
    assert mail.post(c, path, reset_form(code=mail.admin.codes.pop())).status_code == 200
    with Session(engine()) as db:
        assert db.get(User, mail.admin.id).totp_enabled
    assert mail.post(c, "/login", {"email": mail.admin.email, "password": NEW_PASSWORD}).headers["location"] == "/login/totp"


def test_concurrent_reset_consumes_link_once(mail):
    path = request_reset(mail, mail.player)
    clients = [mail.client(), mail.client()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda c: mail.post(c, path, reset_form()), clients))
    assert sorted(response.status_code for response in responses) == [200, 404]


@pytest.mark.parametrize("change", ["expired", "email", "password", "disabled"])
def test_reset_invalid_after_account_or_expiry_change(mail, change):
    path = request_reset(mail, mail.player)
    with Session(engine()) as db:
        user = db.get(User, mail.player.id)
        token = db.get(AccountToken, digest(path.rsplit("/", 1)[1]))
        if change == "expired": token.expires_at = utcnow() - timedelta(seconds=1)
        elif change == "email": user.email = "changed@example.com"
        elif change == "password": user.password_hash = "changed-hash"
        else: user.active = False
        db.commit()
    assert mail.post(mail.client(), path, reset_form()).status_code == 404


def test_account_setup_email_avoids_temporary_password_and_requires_new_password(mail):
    c = mail.login(mail.admin)
    response = mail.post(c, "/administration/users", {"name": "Invited user", "email": "setup@example.com", "role": "player", "password": PASSWORD, "active": "on"})
    assert response.status_code == 303
    path, delivery_id = latest_link("setup", "/reset-password")
    with Session(engine()) as db:
        assert PASSWORD not in decrypt(db.get(EmailOutbox, delivery_id).encrypted_body)
    target = mail.client()
    assert mail.post(target, path, reset_form()).status_code == 200
    assert mail.post(target, "/login", {"email": "setup@example.com", "password": NEW_PASSWORD}).status_code == 303
    assert target.get("/").status_code == 200


def test_invitations_queue_canonical_url_and_revoked_invites_do_not_send(mail, monkeypatch):
    from pathkeeper import mail_worker
    campaign = seed_campaign(mail.gm)
    c = mail.login(mail.gm)
    response = mail.post(c, f"/campaigns/{campaign.id}/invitations", {"email": mail.player.email})
    assert "An invitation email has been queued" in response.text and "https://table.example.com/join/" in response.text
    path, _ = latest_link("invitation", "/join")
    with Session(engine()) as db:
        invitation = db.scalar(select(Invitation))
        assert invitation.token_hash == digest(path.rsplit("/", 1)[1])
        invitation.revoked = True
        db.commit()
    monkeypatch.setattr(mail_worker, "send_email", lambda *args: pytest.fail("Revoked invitation must not send"))
    assert mail_worker.process_one()
    with Session(engine()) as db:
        assert db.scalar(select(EmailDelivery)).status == "failed"
        assert db.scalar(select(EmailOutbox)).encrypted_body is None


def test_worker_sends_once_wipes_body_and_records_result(mail, monkeypatch):
    from pathkeeper import mail_worker
    path = request_reset(mail, mail.player)
    captured = []
    def sender(config, recipient, subject, body):
        captured.append((config, recipient, subject, body))
        with Session(engine()) as db:
            assert db.scalar(select(EmailDelivery)).status == "pending"
        return DeliveryResult("accepted", "Accepted by fixture.", "fixture-id")
    monkeypatch.setattr(mail_worker, "send_email", sender)
    assert mail_worker.process_one() and not mail_worker.process_one()
    assert len(captured) == 1 and path in captured[0][3]
    with Session(engine()) as db:
        assert db.scalar(select(EmailDelivery)).message_id == "fixture-id"
        assert db.scalar(select(EmailOutbox)).encrypted_body is None


def test_worker_failure_and_restart_never_resend_uncertain_delivery(mail, monkeypatch):
    from pathkeeper import mail_worker
    request_reset(mail, mail.player)
    monkeypatch.setattr(mail_worker, "send_email", lambda *args: (_ for _ in ()).throw(RuntimeError("private token output")))
    assert mail_worker.process_one() and not mail_worker.process_one()
    with Session(engine()) as db:
        delivery = db.scalar(select(EmailDelivery))
        assert delivery.status == "unknown" and "private token" not in delivery.detail
    # Another interrupted attempt is marked unknown at worker startup.
    request_reset(mail, mail.player2)
    with Session(engine()) as db:
        db.scalar(select(EmailDelivery).where(EmailDelivery.status == "queued")).status = "pending"
        db.commit()
    mail_worker.recover_interrupted()
    assert not mail_worker.process_one()
    with Session(engine()) as db:
        assert all(item.encrypted_body is None for item in db.scalars(select(EmailOutbox)))


def test_reset_csrf_and_request_limits(mail):
    c = mail.client()
    assert mail.post(c, "/forgot-password", {"email": mail.player.email}, use_csrf=False).status_code == 403
    for _ in range(3):
        assert mail.post(c, "/forgot-password", {"email": mail.player.email}).status_code == 200
    assert mail.post(c, "/forgot-password", {"email": mail.player.email}).status_code == 429


def test_invitation_survives_signup_and_email_verification(mail):
    campaign = seed_campaign(mail.gm)
    gm = mail.login(mail.gm)
    mail.post(gm, f"/campaigns/{campaign.id}/invitations", {"email": "newplayer@example.com"})
    join_path, _ = latest_link("invitation", "/join")
    c = mail.client()
    assert c.get(join_path).headers["location"] == "/login"
    c.get("/signup")
    mail.post(c, "/signup", signup_form())
    verify_path, _ = latest_link("verify", "/verify-email")
    response = mail.post(c, verify_path)
    assert f'href="{join_path}"' in response.text
    assert mail.post(c, join_path).status_code == 303


def test_reset_links_ignore_request_host(mail):
    c = mail.client()
    assert c.post("/forgot-password", data={"csrf": mail.csrf(c), "email": mail.player.email}, headers={"host": "attacker.example.com"}).status_code == 200
    with Session(engine()) as db:
        body = decrypt(db.scalar(select(EmailOutbox)).encrypted_body)
        assert "https://table.example.com/reset-password/" in body and "attacker.example.com" not in body


@pytest.mark.parametrize("url", ["https://example.com/path", "ftp://example.com", "https://user:password@example.com", "https://example.com?q=x", "https://example.com#token", "https://example.com:0"])
def test_application_base_url_rejects_unsafe_or_unsupported_forms(url):
    from fastapi import HTTPException
    with pytest.raises(HTTPException): normalize_base_url(url)


def test_workflow_migration_preserves_configuration_and_legacy_access(env, isolated_database):
    from pathkeeper.migrations import migrate
    with isolated_database.begin() as connection:
        connection.execute(text("ALTER TABLE users DROP COLUMN email_verified_at, DROP COLUMN email_verification_required"))
        connection.execute(text("ALTER TABLE email_configuration DROP COLUMN public_base_url"))
        connection.execute(text("DELETE FROM schema_migrations WHERE version = 2"))
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 5
        assert not db.get(User, env.admin.id).email_verification_required
        assert db.get(EmailConfiguration, 1).public_base_url == ""
        assert db.get(SchemaMigration, 2)

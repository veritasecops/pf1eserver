from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import re
import time

import pyotp
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import AuditEvent, Campaign, Character, Membership, RecoveryCode, User, WebSession, utcnow
from pathkeeper.security import COOKIE, PASSWORDS, decrypt, digest, password_ok
from .conftest import PASSWORD


def account_form(target, **extra):
    return {"name": "Managed user", "email": target.email, "role": target.role, "active": "on", **extra}


def test_login_is_normal_password_login_and_health(env):
    c = env.client()
    page = c.get("/login")
    assert page.status_code == 200
    assert 'name="email"' in page.text and 'name="password"' in page.text
    assert "server key" not in page.text.lower() and "setup_token" not in page.text
    assert c.get("/health").json()["database"] == "MariaDB"
    assert c.get("/").status_code == 303


def test_bad_credentials_do_not_authenticate(env):
    c = env.client()
    response = env.post(c, "/login", {"email": env.player.email, "password": "wrong"})
    assert "Email or password is incorrect" in response.text
    assert c.get("/").headers["location"] == "/login"


def test_sessions_rotate_and_store_only_cookie_hashes(env):
    c = env.client()
    old = c.cookies[COOKIE]
    response = env.post(c, "/login", {"email": env.player.email, "password": PASSWORD})
    token = c.cookies[COOKIE]
    assert token != old
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    with Session(engine()) as db:
        assert db.get(WebSession, digest(old)) is None
        assert db.get(WebSession, token) is None
        assert db.get(WebSession, digest(token)).phase == "authenticated"
    assert c.get("/").status_code == 200


@pytest.mark.parametrize("role", ["player", "gm"])
def test_non_admins_cannot_administer_users(env, role):
    c = env.login(env.player if role == "player" else env.gm)
    for path in ("/administration", "/administration/users/new", "/administration/audit", "/administration/permissions", f"/administration/users/{env.admin.id}"):
        assert c.get(path).status_code == 403
    assert env.post(c, "/administration/users", {"name": "Forbidden", "email": "forbidden@example.com", "role": "admin", "password": PASSWORD, "active": "on"}).status_code == 403
    for action in ("delete", "password", "totp-reset"):
        assert env.post(c, f"/administration/users/{env.admin.id}/{action}", {"confirm_email": env.admin.email, "new_password": PASSWORD}).status_code == 403


def test_password_alone_is_not_enough_for_enrolled_admin(env):
    c = env.login(env.admin, complete=False)
    assert c.get("/administration").status_code == 303
    assert c.get("/login").headers["location"] == "/login/totp"
    assert c.get("/account/security").status_code == 303


def test_totp_login_and_replay_protection(env):
    code = pyotp.TOTP(env.admin.secret).now()
    c = env.login(env.admin, complete=False)
    response = env.post(c, "/login/totp", {"code": code})
    assert response.status_code == 303 and c.get("/administration").status_code == 200
    other = env.login(env.admin, complete=False)
    assert "already been used" in env.post(other, "/login/totp", {"code": code}).text
    assert other.get("/administration").status_code == 303


def test_concurrent_totp_is_consumed_once(env):
    first, second = env.login(env.admin, complete=False), env.login(env.admin, complete=False)
    code = pyotp.TOTP(env.admin.secret).now()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda c: env.post(c, "/login/totp", {"code": code}), [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 303]


def test_recovery_codes_are_single_use(env):
    code = env.admin.codes.pop()
    first = env.login(env.admin, complete=False)
    assert env.post(first, "/login/totp", {"code": code}).status_code == 303
    second = env.login(env.admin, complete=False)
    assert "invalid or has already been used" in env.post(second, "/login/totp", {"code": code}).text


def test_admin_enrollment_is_mandatory_and_encrypted(env):
    admin = env.add("admin", "newadmin@example.com")
    c = env.login(admin)
    assert c.get("/administration").headers["location"] == "/account/security"
    assert env.post(c, "/account/security/setup", {"current_password": PASSWORD}).status_code == 303
    with Session(engine()) as db:
        account = db.get(User, admin.id)
        secret = decrypt(account.pending_totp)
        assert secret != account.pending_totp
    assert c.get("/account/security/qr.svg").headers["content-type"].startswith("image/svg+xml")
    bad = env.post(c, "/account/security/enable", {"code": "abcdef"})
    assert bad.status_code == 422
    response = env.post(c, "/account/security/enable", {"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200 and "Save your recovery codes" in response.text
    codes = re.findall(r"<code>([a-f0-9-]{23})</code>", response.text)
    assert len(codes) == 10
    with Session(engine()) as db:
        account = db.get(User, admin.id)
        assert account.totp_enabled and account.pending_totp is None
        assert account.totp_secret != secret and decrypt(account.totp_secret) == secret
        records = list(db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == admin.id)))
        assert len(records) == 10 and all(record.code_hash not in codes for record in records)
    assert c.get("/administration").status_code == 200


def test_expired_enrollment_and_mfa_sessions(env):
    admin = env.add("admin", "expired@example.com")
    c = env.login(admin)
    env.post(c, "/account/security/setup", {"current_password": PASSWORD})
    with Session(engine()) as db:
        db.get(User, admin.id).pending_totp_at = utcnow() - timedelta(minutes=11)
        db.commit()
    assert c.get("/account/security/qr.svg").status_code == 404
    assert env.post(c, "/account/security/enable", {"code": "123456"}).status_code == 409
    pending = env.login(env.admin, complete=False)
    with Session(engine()) as db:
        db.get(WebSession, digest(pending.cookies[COOKIE])).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert pending.get("/login/totp").headers["location"] == "/login"


def test_admin_create_user_hashes_password_and_forces_change(env):
    c = env.login(env.admin)
    response = env.post(c, "/administration/users", {"name": "New player", "email": "new@example.com", "role": "player", "password": PASSWORD, "active": "on"})
    assert response.status_code == 303
    with Session(engine()) as db:
        account = db.scalar(select(User).where(User.email == "new@example.com"))
        assert account.password_hash != PASSWORD and password_ok(PASSWORD, account.password_hash)
        assert account.must_change_password
        user_id = account.id
    new = env.add("player", "othernew@example.com", change=True)
    target = env.login(new)
    assert target.get("/").headers["location"] == "/account/password"
    changed = env.post(target, "/account/password", {"current_password": PASSWORD, "new_password": "A-different-password-2026!", "confirm_password": "A-different-password-2026!"})
    assert changed.status_code == 303 and target.get("/").status_code == 200


def test_disabling_revokes_existing_sessions_and_enable_allows_login(env):
    admin, player = env.login(env.admin), env.login(env.player)
    response = env.post(admin, f"/administration/users/{env.player.id}", account_form(env.player, **env.confirm(env.admin), active=""))
    assert response.status_code == 303
    assert player.get("/").headers["location"] == "/login"
    fresh = env.client()
    assert "incorrect" in env.post(fresh, "/login", {"email": env.player.email, "password": PASSWORD}).text
    response = env.post(admin, f"/administration/users/{env.player.id}", account_form(env.player, **env.confirm(env.admin)))
    assert response.status_code == 303
    assert env.login(env.player).get("/").status_code == 200


def test_last_active_admin_cannot_be_removed_disabled_or_demoted(env):
    c = env.login(env.admin)
    for operation in ("disable", "demote", "delete"):
        values = {**account_form(env.admin), **env.confirm(env.admin)}
        path = f"/administration/users/{env.admin.id}"
        if operation == "disable":
            values["active"] = ""
        elif operation == "demote":
            values["role"] = "player"
        else:
            path += "/delete"
            values["confirm_email"] = env.admin.email
        assert env.post(c, path, values).status_code == 409
    with Session(engine()) as db:
        admin = db.get(User, env.admin.id)
        assert admin.active and admin.role == "admin"


def test_admin_password_reset_preserves_totp_and_revokes_sessions(env):
    target = env.add("player", "reset@example.com", mfa=True)
    player = env.login(target)
    c = env.login(env.admin)
    new_password = "Replacement-password-2026!"
    response = env.post(c, f"/administration/users/{target.id}/password", {"new_password": new_password, **env.confirm(env.admin)})
    assert response.status_code == 303 and player.get("/").status_code == 303
    with Session(engine()) as db:
        record = db.get(User, target.id)
        assert password_ok(new_password, record.password_hash) and record.totp_enabled and record.must_change_password


def test_admin_totp_reset_requires_reenrollment(env):
    target = env.add("player", "resetmfa@example.com", mfa=True)
    player = env.login(target)
    c = env.login(env.admin)
    response = env.post(c, f"/administration/users/{target.id}/totp-reset", {"confirm_email": target.email, **env.confirm(env.admin)})
    assert response.status_code == 303 and player.get("/").status_code == 303
    with Session(engine()) as db:
        record = db.get(User, target.id)
        assert not record.totp_enabled and record.totp_required and record.totp_secret is None
        assert not list(db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == target.id)))
    target.secret = None
    fresh = env.login(target)
    assert fresh.get("/").headers["location"] == "/account/security"


def test_admin_delete_cascades_owned_records_but_preserves_others_characters(env):
    with Session(engine()) as db:
        campaign = Campaign(owner_id=env.gm.id, name="Owned campaign")
        db.add(campaign)
        db.flush()
        other = Character(owner_id=env.player.id, campaign_id=campaign.id, name="Survivor")
        db.add_all([Character(owner_id=env.gm.id, name="Deleted hero"), other])
        db.commit()
        survivor_id = other.id
    c = env.login(env.admin)
    response = env.post(c, f"/administration/users/{env.gm.id}/delete", {"confirm_email": env.gm.email, **env.confirm(env.admin)})
    assert response.status_code == 303
    with Session(engine()) as db:
        assert db.get(User, env.gm.id) is None
        assert db.get(Character, survivor_id).campaign_id is None
        assert not list(db.scalars(select(Character).where(Character.owner_id == env.gm.id)))
        assert not list(db.scalars(select(Campaign).where(Campaign.owner_id == env.gm.id)))


def test_csrf_and_profile_cannot_escalate_role(env):
    c = env.login(env.player)
    assert env.post(c, "/characters", {"name": "No CSRF", "level": 1}, use_csrf=False).status_code == 403
    assert c.post("/characters", data={"csrf": "非ASCII", "name": "Invalid", "level": 1}).status_code == 403
    response = env.post(c, "/account", {"name": "Updated profile", "email": env.player.email, "timezone": "UTC", "bio": "A player", "role": "admin", "totp_required": ""})
    assert response.status_code == 303
    with Session(engine()) as db:
        record = db.get(User, env.player.id)
        assert record.role == "player" and record.name == "Updated profile"
    assert c.get("/administration").status_code == 403


def test_password_change_revokes_other_sessions(env):
    first, second = env.login(env.player), env.login(env.player)
    response = env.post(first, "/account/password", {"current_password": PASSWORD, "new_password": "Changed-password-2026!", "confirm_password": "Changed-password-2026!"})
    assert response.status_code == 303
    assert first.get("/").status_code == 200 and second.get("/").status_code == 303


def test_login_rate_limiting(env):
    c = env.client()
    for _ in range(10):
        assert env.post(c, "/login", {"email": env.player.email, "password": "wrong"}).status_code == 200
    assert env.post(c, "/login", {"email": env.player.email, "password": "wrong"}).status_code == 429


def test_mfa_rate_limit_and_unicode_codes(env):
    c = env.login(env.admin, complete=False)
    for _ in range(8):
        assert env.post(c, "/login/totp", {"code": "١٢٣٤٥٦"}).status_code == 200
    assert env.post(c, "/login/totp", {"code": "000000"}).status_code == 429


def test_mfa_limit_cannot_be_bypassed_by_changing_ip(env, monkeypatch):
    from pathkeeper import auth
    c = env.login(env.admin, complete=False)
    addresses = iter(f"192.0.2.{number}" for number in range(1, 11))
    monkeypatch.setattr(auth, "request_ip", lambda request: next(addresses))
    for _ in range(8):
        assert env.post(c, "/login/totp", {"code": "invalid"}).status_code == 200
    assert env.post(c, "/login/totp", {"code": "invalid"}).status_code == 429


def test_help_is_public_searchable_downloadable_and_escaped(env, monkeypatch):
    from pathkeeper.help import GUIDES, markdown
    from pathkeeper import main
    monkeypatch.setattr(main, "engine", lambda: (_ for _ in ()).throw(RuntimeError("No DB")))
    c = env.client()
    for slug, *_ in GUIDES:
        assert c.get(f"/help/{slug}").status_code == 200
    assert "Authenticator" in c.get("/help?q=TOTP").text
    assert "attachment" in c.get("/help/manual.md").headers["content-disposition"]
    assert c.get("/help/print").status_code == 200
    assert c.get("/help/unknown").status_code == 404
    html, _ = markdown('<script>alert(1)</script>\n\n## A heading\n\n`code`')
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_security_headers_and_cookie_expiration(env):
    c = env.login(env.player)
    response = c.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    with Session(engine()) as db:
        db.get(WebSession, digest(c.cookies[COOKIE])).last_seen = utcnow() - timedelta(hours=2)
        db.commit()
    assert c.get("/").status_code == 303

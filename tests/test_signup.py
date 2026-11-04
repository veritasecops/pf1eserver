import json
import re

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Membership, User, WebSession
from pathkeeper.security import COOKIE, digest, password_ok
from .conftest import PASSWORD
from .test_workspace import seed_campaign


def signup_form(**extra):
    return {"name": "New adventurer", "email": "newplayer@example.com",
            "password": PASSWORD, "confirm_password": PASSWORD, **extra}


def test_signup_creates_only_player_rotates_session_and_allows_login(env):
    c = env.client()
    old_cookie = c.cookies[COOKIE]
    assert "Create a Player account" in c.get("/login").text
    page = c.get("/signup")
    assert page.status_code == 200 and 'name="role"' not in page.text
    response = env.post(c, "/signup", signup_form(email="NewPlayer@Example.com", role="admin", active="", totp_required="on"))
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert c.cookies[COOKIE] != old_cookie and c.get("/").status_code == 200
    with Session(engine()) as db:
        account = db.scalar(select(User).where(User.email == "newplayer@example.com"))
        assert account.role == "player" and account.active
        assert not account.must_change_password and not account.totp_required
        assert account.password_hash != PASSWORD and password_ok(PASSWORD, account.password_hash)
        assert db.get(WebSession, digest(old_cookie)) is None
    assert c.get("/administration").status_code == 403
    env.post(c, "/logout")
    assert env.post(c, "/login", {"email": "newplayer@example.com", "password": PASSWORD}).status_code == 303
    assert c.get("/").status_code == 200


def test_first_public_user_remains_player(env):
    with Session(engine()) as db:
        db.execute(delete(User))
        db.commit()
    c = env.client()
    assert env.post(c, "/signup", signup_form(role="admin")).status_code == 303
    with Session(engine()) as db:
        accounts = list(db.scalars(select(User)))
        assert len(accounts) == 1 and accounts[0].role == "player"


@pytest.mark.parametrize("values,status", [
    ({"confirm_password": "different"}, 422),
    ({"password": "short", "confirm_password": "short"}, 422),
    ({"email": "invalid-email"}, 422),
    ({"name": ""}, 422),
    ({"email": "PLAYER@example.com"}, 409),
])
def test_signup_validation_never_creates_account_or_authenticates(env, values, status):
    c = env.client()
    response = env.post(c, "/signup", signup_form(**values))
    assert response.status_code == status
    assert PASSWORD not in response.text
    assert c.get("/").headers["location"] == "/login"
    with Session(engine()) as db:
        assert len(list(db.scalars(select(User)))) == 5


def test_signup_csrf_rate_limit_and_authenticated_guard(env):
    c = env.client()
    assert env.post(c, "/signup", signup_form(), use_csrf=False).status_code == 403
    for _ in range(10):
        assert env.post(c, "/signup", signup_form(confirm_password="wrong")).status_code == 422
    assert env.post(c, "/signup", signup_form()).status_code == 429
    player = env.login(env.player)
    assert player.get("/signup").headers["location"] == "/"
    assert env.post(player, "/signup", signup_form(role="admin")).headers["location"] == "/"
    with Session(engine()) as db:
        assert db.scalar(select(User).where(User.email == "newplayer@example.com")) is None
        assert db.get(User, env.player.id).role == "player"


def test_invitation_survives_signup_and_requires_explicit_acceptance(env):
    campaign = seed_campaign(env.gm)
    gm, c = env.login(env.gm), env.client()
    invite = env.post(gm, f"/campaigns/{campaign.id}/invitations", {"email": "newplayer@example.com"})
    path = re.search(r'data-origin-path="(/join/[A-Za-z0-9_-]+)"', invite.text).group(1)
    assert c.get(path).headers["location"] == "/login"
    assert c.get("/signup").status_code == 200
    assert env.post(c, "/signup", signup_form()).headers["location"] == path
    with Session(engine()) as db:
        account_id = db.scalar(select(User.id).where(User.email == "newplayer@example.com"))
        assert db.get(Membership, (campaign.id, account_id)) is None
    assert c.get(path).status_code == 200
    assert env.post(c, path).status_code == 303
    with Session(engine()) as db:
        assert db.get(Membership, (campaign.id, account_id)) is not None


def test_generated_admin_password_is_temporary_and_requires_totp(env, capsys):
    from pathkeeper.manage import manage_user
    manage_user("create-admin", "bootstrap@example.com", "Bootstrap Admin", generate_password=True)
    credentials = json.loads(capsys.readouterr().out)
    assert len(credentials["temporary_password"]) >= 24
    with Session(engine()) as db:
        account = db.scalar(select(User).where(User.email == "bootstrap@example.com"))
        assert account.role == "admin" and account.active
        assert account.must_change_password and account.totp_required and not account.totp_enabled
        assert password_ok(credentials["temporary_password"], account.password_hash)
    c = env.client()
    assert env.post(c, "/login", {"email": credentials["email"], "password": credentials["temporary_password"]}).status_code == 303
    assert c.get("/administration").headers["location"] == "/account/password"

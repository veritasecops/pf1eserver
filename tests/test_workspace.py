from datetime import timedelta
import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import AuditEvent, Campaign, Character, Invitation, Membership, User, utcnow
from .test_accounts import account_form


def seed_campaign(owner, name="A private campaign", members=()):
    with Session(engine(), expire_on_commit=False) as db:
        campaign = Campaign(owner_id=owner.id, name=name, description="Campaign notes", setting="The Marches")
        db.add(campaign)
        db.flush()
        for member in members:
            db.add(Membership(campaign_id=campaign.id, user_id=member.id))
        db.commit()
        return campaign


def seed_character(owner, campaign=None, name="Test adventurer"):
    with Session(engine(), expire_on_commit=False) as db:
        character = Character(owner_id=owner.id, campaign_id=campaign.id if campaign else None,
                              name=name, ancestry="Human", class_name="Fighter", level=3, notes="A character")
        db.add(character)
        db.commit()
        return character


def char_form(character=None, **extra):
    return {"name": character.name if character else "New adventurer", "ancestry": "Elf", "class_name": "Wizard", "level": 4,
            "notes": "Updated notes", "campaign_id": character.campaign_id or "" if character else "",
            "version": character.version if character else 1, **extra}


def test_players_have_full_crud_on_own_characters(env):
    c = env.login(env.player)
    response = env.post(c, "/characters", char_form())
    assert response.status_code == 303
    path = response.headers["location"]
    assert c.get(path).status_code == 200 and c.get(path + "/edit").status_code == 200
    with Session(engine()) as db:
        character = db.get(Character, int(path.rsplit("/", 1)[1]))
        assert character.owner_id == env.player.id
        values = char_form(character, name="Updated adventurer")
    assert env.post(c, path, values).status_code == 303
    assert "Updated adventurer" in c.get(path).text
    with Session(engine()) as db:
        version = db.get(Character, int(path.rsplit("/", 1)[1])).version
    assert env.post(c, path + "/delete", {"confirm_name": "Updated adventurer", "version": version}).status_code == 303
    assert c.get(path).status_code == 404


def test_player_cannot_manage_others_or_create_campaigns(env):
    character = seed_character(env.player2)
    c = env.login(env.player)
    assert c.get(f"/characters/{character.id}").status_code == 404
    assert env.post(c, f"/characters/{character.id}", char_form(character)).status_code == 404
    assert env.post(c, f"/characters/{character.id}/delete", {"confirm_name": character.name, "version": 1}).status_code == 404
    assert c.get("/campaigns/new").status_code == 403
    assert env.post(c, "/campaigns", {"name": "Forbidden"}).status_code == 403
    assert env.post(c, "/characters", char_form(owner_id=env.admin.id)).status_code == 303
    with Session(engine()) as db:
        record = db.scalar(select(Character).where(Character.owner_id == env.player.id))
        assert record is not None


@pytest.mark.parametrize("actor", ["player", "gm", "admin"])
def test_character_deletion_is_visible_to_owners_and_admins_and_requires_confirmation(env, actor):
    account = getattr(env, actor)
    character = seed_character(env.player if actor == "admin" else account)
    survivor = seed_character(env.player2, name="Keep this character")
    client = env.login(account)
    path = f"/characters/{character.id}"
    page = client.get(path)
    assert 'href="#delete-character"' in page.text
    assert page.text.count('id="delete-character"') == 1
    assert page.text.index("<body") < page.text.index('id="delete-character"')
    values = {"confirm_name": character.name, "version": character.version}
    assert env.post(client, path + "/delete", values, use_csrf=False).status_code == 403
    assert env.post(client, path + "/delete", {**values, "confirm_name": "Wrong name"}).status_code == 422
    assert env.post(client, path + "/delete", {**values, "version": character.version + 1}).status_code == 409
    with Session(engine()) as db:
        assert db.get(Character, character.id) is not None
        assert db.scalar(select(AuditEvent).where(AuditEvent.event == "character.deleted")) is None
    response = env.post(client, path + "/delete", values)
    assert response.status_code == 303
    assert response.headers["location"] == "/characters"
    assert client.get(path).status_code == 404
    with Session(engine()) as db:
        assert db.get(Character, character.id) is None
        assert db.get(Character, survivor.id) is not None
        event = db.scalar(select(AuditEvent).where(AuditEvent.event == "character.deleted"))
        assert event.actor_id == account.id
        assert character.name in event.detail


def test_gm_campaign_crud_and_unrelated_campaign_boundary(env):
    c = env.login(env.gm)
    created = env.post(c, "/campaigns", {"name": "GM world", "description": "A world", "setting": "North", "owner_id": env.gm2.id})
    assert created.status_code == 303
    path = created.headers["location"]
    with Session(engine()) as db:
        campaign = db.get(Campaign, int(path.rsplit("/", 1)[1]))
        assert campaign.owner_id == env.gm.id
    assert c.get(path).status_code == 200
    assert env.post(c, path, {"name": "Revised world", "description": "Revised", "setting": "South", "version": 1}).status_code == 303
    unrelated = seed_campaign(env.gm2)
    assert c.get(f"/campaigns/{unrelated.id}").status_code == 404
    assert env.post(c, f"/campaigns/{unrelated.id}", {"name": "Stolen", "version": 1}).status_code == 404
    assert env.post(c, path + "/delete", {"confirm_name": "Revised world", "version": 2}).status_code == 303
    assert c.get(path).status_code == 404


def test_gm_can_manage_only_joined_assigned_characters(env):
    campaign = seed_campaign(env.gm, members=[env.player])
    elsewhere = seed_campaign(env.gm2, members=[env.player])
    assigned = seed_character(env.player, campaign)
    standalone = seed_character(env.player, name="Standalone")
    other_campaign = seed_character(env.player, elsewhere, name="Elsewhere")
    unjoined = seed_character(env.player2, campaign, name="Nonmember")
    c = env.login(env.gm)
    assert c.get(f"/characters/{assigned.id}").status_code == 200
    assert env.post(c, f"/characters/{assigned.id}", char_form(assigned, name="GM edited")).status_code == 303
    for record in (standalone, other_campaign, unjoined):
        assert c.get(f"/characters/{record.id}").status_code == 404
    listing = c.get("/characters")
    assert listing.status_code == 200 and "GM edited" in listing.text
    assert "Standalone" not in listing.text and "Nonmember" not in listing.text and "Elsewhere" not in listing.text
    with Session(engine()) as db:
        record = db.get(Character, assigned.id)
        assert env.post(c, f"/characters/{record.id}", char_form(record, campaign_id="")).status_code == 403
        version = record.version
    assert "Delete character" not in c.get(f"/characters/{assigned.id}").text
    assert env.post(c, f"/characters/{assigned.id}/delete", {"confirm_name": "GM edited", "version": version}).status_code == 403
    with Session(engine()) as db:
        assert db.get(Character, assigned.id) is not None


@pytest.mark.parametrize("actor", ["player", "gm", "admin"])
def test_direct_character_creation_ignores_another_owner_for_every_role(env,actor):
    campaign = seed_campaign(env.gm, members=[env.player])
    account = getattr(env,actor)
    c = env.login(account)
    response = env.post(c, "/characters", char_form(owner_id=env.player2.id, campaign_id=campaign.id))
    assert response.status_code == 303
    with Session(engine()) as db:
        record = db.get(Character, int(response.headers["location"].rsplit("/", 1)[1]))
        assert record.owner_id == account.id and record.campaign_id == campaign.id
    response = env.post(c, "/characters", char_form(owner_id=env.player2.id))
    assert response.status_code == 303
    with Session(engine()) as db:
        record = db.get(Character,int(response.headers["location"].rsplit("/",1)[1]))
        assert record.owner_id == account.id and record.campaign_id is None


def test_joined_gm_cannot_edit_other_gms_campaign(env):
    campaign = seed_campaign(env.gm2, members=[env.gm])
    c = env.login(env.gm)
    assert c.get(f"/campaigns/{campaign.id}").status_code == 200
    assert c.get(f"/campaigns/{campaign.id}/edit").status_code == 403
    assert env.post(c, f"/campaigns/{campaign.id}/invitations", {"email": env.player.email}).status_code == 403


def test_invitation_is_email_bound_hashed_single_use_and_grants_membership(env):
    campaign = seed_campaign(env.gm)
    gm, player, wrong = env.login(env.gm), env.login(env.player), env.login(env.player2)
    response = env.post(gm, f"/campaigns/{campaign.id}/invitations", {"email": env.player.email})
    assert response.status_code == 200
    path = re.search(r'data-origin-path="(/join/[A-Za-z0-9_-]+)"', response.text).group(1)
    token = path.rsplit("/", 1)[1]
    with Session(engine()) as db:
        invite = db.scalar(select(Invitation))
        assert invite.token_hash != token and token not in invite.token_hash
    assert wrong.get(path).status_code == 403 and env.post(wrong, path).status_code == 403
    assert player.get(path).status_code == 200
    assert env.post(player, path).status_code == 303
    assert player.get(f"/campaigns/{campaign.id}").status_code == 200
    assert player.get(path).status_code == 404 and env.post(player, path).status_code == 404
    with Session(engine()) as db:
        assert db.get(Membership, (campaign.id, env.player.id)) is not None


def test_invitation_survives_login_round_trip_and_expiry_revoke(env):
    campaign = seed_campaign(env.gm)
    gm, player = env.login(env.gm), env.client()
    response = env.post(gm, f"/campaigns/{campaign.id}/invitations", {"email": env.player.email})
    path = re.search(r'data-origin-path="(/join/[A-Za-z0-9_-]+)"', response.text).group(1)
    assert player.get(path).headers["location"] == "/login"
    player.get("/login")
    logged = env.post(player, "/login", {"email": env.player.email, "password": env.player.password})
    assert logged.headers["location"] == path
    with Session(engine()) as db:
        invitation = db.scalar(select(Invitation))
        invitation.expires_at = utcnow() - timedelta(seconds=1)
        invitation_id = invitation.id
        db.commit()
    assert player.get(path).status_code == 404
    assert env.post(gm, f"/invitations/{invitation_id}/revoke").status_code == 303


def test_removing_member_detaches_characters_and_revokes_gm_scope(env):
    campaign = seed_campaign(env.gm, members=[env.player])
    character = seed_character(env.player, campaign)
    gm, player = env.login(env.gm), env.login(env.player)
    assert gm.get(f"/characters/{character.id}").status_code == 200
    assert env.post(gm, f"/campaigns/{campaign.id}/members/{env.player.id}/remove").status_code == 303
    assert gm.get(f"/characters/{character.id}").status_code == 404
    assert player.get(f"/characters/{character.id}").status_code == 200
    assert player.get(f"/campaigns/{campaign.id}").status_code == 404
    with Session(engine()) as db:
        assert db.get(Character, character.id).campaign_id is None


def test_admin_full_campaign_character_crud_and_ownership_transfer(env):
    campaign = seed_campaign(env.gm)
    character = seed_character(env.player)
    c = env.login(env.admin)
    assert c.get(f"/campaigns/{campaign.id}").status_code == 200
    assert env.post(c, f"/campaigns/{campaign.id}", {"name": campaign.name, "setting": "New", "description": "Updated", "version": 1, "owner_id": env.gm2.id}).status_code == 303
    assert c.get(f"/characters/{character.id}").status_code == 200
    assert env.post(c, f"/characters/{character.id}", char_form(character, owner_id=env.player2.id, campaign_id=campaign.id)).status_code == 303
    with Session(engine()) as db:
        assert db.get(Campaign, campaign.id).owner_id == env.gm2.id
        assert db.get(Character, character.id).owner_id == env.player2.id
    assert env.post(c, f"/characters/{character.id}/delete", {"confirm_name": character.name, "version": 2}).status_code == 303
    assert env.post(c, f"/campaigns/{campaign.id}/delete", {"confirm_name": campaign.name, "version": 2}).status_code == 303


def test_campaign_owner_cannot_be_demoted_until_transfer(env):
    campaign = seed_campaign(env.gm)
    c = env.login(env.admin)
    assert env.post(c, f"/administration/users/{env.gm.id}", {**account_form(env.gm, role="player"), **env.confirm(env.admin)}).status_code == 409
    assert env.post(c, f"/campaigns/{campaign.id}", {"name": campaign.name, "setting": "", "description": "", "version": 1, "owner_id": env.gm2.id}).status_code == 303
    assert env.post(c, f"/administration/users/{env.gm.id}", {**account_form(env.gm, role="player"), **env.confirm(env.admin)}).status_code == 303
    with Session(engine()) as db:
        assert db.get(User, env.gm.id).role == "player"


def test_version_conflict_and_escaped_user_content(env):
    character = seed_character(env.player)
    c = env.login(env.player)
    response = env.post(c, f"/characters/{character.id}", char_form(character, name="<script>alert(1)</script>"))
    assert response.status_code == 303
    page = c.get(f"/characters/{character.id}")
    assert "&lt;script&gt;" in page.text and "<script>alert(1)</script>" not in page.text
    assert env.post(c, f"/characters/{character.id}", char_form(character, name="Stale overwrite")).status_code == 409
    with Session(engine()) as db:
        assert db.get(Character, character.id).name == "<script>alert(1)</script>"


def test_player_cannot_assign_character_to_unjoined_campaign(env):
    campaign = seed_campaign(env.gm)
    c = env.login(env.player)
    assert env.post(c, "/characters", char_form(campaign_id=campaign.id)).status_code == 404


def test_character_level_validation(env):
    c = env.login(env.player)
    for invalid in (0, 41, "1.5", "wrong"):
        assert env.post(c, "/characters", char_form(level=invalid)).status_code == 422

from copy import deepcopy
import json
import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.migrations import migrate
from pathkeeper.models import Character, CharacterDraft, SchemaMigration
from .test_character_wizard import fighter, finish, save
from .test_workspace import char_form, seed_campaign, seed_character


def test_campaign_npc_wizard_and_roster(env):
    campaign = seed_campaign(env.gm, members=[env.player, env.gm2])
    other_campaign = seed_campaign(env.gm, "Other campaign")
    path = f"/campaigns/{campaign.id}"
    start_path = f"{path}/npcs/new"
    gm, player, other_gm = (env.login(account) for account in (env.gm, env.player, env.gm2))
    assert 'id="npcs"' in gm.get(path).text
    for client in (player, other_gm):
        assert 'id="npcs"' not in client.get(path).text
        assert client.get(start_path).status_code == 403

    draft_path = gm.get(start_path).headers["location"]
    draft_id = draft_path.rsplit("/", 1)[1]
    page = gm.get(draft_path)
    boot = json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>', page.text, re.S).group(1))
    assert boot["is_npc"] and boot["return_path"] == f"{path}#npcs"
    data = fighter(deepcopy(boot["data"]))
    data.update(campaign_id=other_campaign.id, owner_id=env.player.id)
    saved = save(env, gm, draft_id, boot["version"], data)
    assert saved.status_code == 200, saved.text
    assert draft_path in gm.get(path).text
    assert draft_path not in gm.get("/characters").text
    assert player.get(draft_path).status_code == 404
    assert finish(env, other_gm, draft_id, saved.json()["version"]).status_code == 404

    completed = finish(env, gm, draft_id, saved.json()["version"])
    assert completed.status_code == 200
    assert finish(env, gm, draft_id, saved.json()["version"]).json() == completed.json()
    sheet_path = completed.json()["location"]
    npc_id = int(sheet_path.rsplit("/", 1)[1])
    with Session(engine()) as db:
        npc = db.get(Character, npc_id)
        assert npc.is_npc and npc.campaign_id == campaign.id and npc.owner_id == env.gm.id
        assert npc.sheet_data["input"]["campaign_id"] == campaign.id
        assert npc.sheet_data["input"]["owner_id"] == env.gm.id
    roster = gm.get(path).text
    assert '<table aria-labelledby="campaign-npcs-title">' in roster
    assert f'href="{sheet_path}">{data["name"]}</a>' in roster
    assert draft_path not in roster
    for listing in ("/", "/characters", f"/campaigns/{other_campaign.id}"):
        assert data["name"] not in gm.get(listing).text
    assert f'href="{path}#npcs"' in gm.get(sheet_path).text
    for client in (player, other_gm):
        assert data["name"] not in client.get(path).text
        assert client.get(sheet_path).status_code == 404
        assert client.get(f"{sheet_path}/portrait").status_code == 404
        assert env.post(client, f"{sheet_path}/delete").status_code == 404

    admin = env.login(env.admin)
    updated = env.post(admin, path, {"version": campaign.version, "name": campaign.name, "owner_id": env.gm2.id})
    assert updated.status_code == 303
    assert gm.get(sheet_path).status_code == 404
    assert other_gm.get(sheet_path).status_code == 200
    edit_page = other_gm.get(f"{sheet_path}/sheet/edit")
    assert "NPC creation" in edit_page.text
    edit = json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>', edit_page.text, re.S).group(1))
    assert edit["mode"] == "edit"
    edit_saved = save(env, other_gm, edit["draft_id"], edit["version"], {**edit["data"], "name": "Edited NPC"})
    assert edit_saved.status_code == 200, edit_saved.text
    assert finish(env, other_gm, edit["draft_id"], edit_saved.json()["version"]).json() == completed.json()
    with Session(engine()) as db:
        npc = db.get(Character, npc_id)
        assert npc.owner_id == env.gm2.id and npc.sheet_data["input"]["owner_id"] == env.gm2.id
    updated_npc = env.post(admin, sheet_path, char_form(
        npc, ancestry=npc.ancestry, class_name=npc.class_name, name="Renamed NPC",
        campaign_id=other_campaign.id, owner_id=env.player.id))
    assert updated_npc.status_code == 303
    with Session(engine()) as db:
        npc = db.get(Character, npc_id)
        assert npc.campaign_id == campaign.id and npc.owner_id == env.gm2.id
    deleted = env.post(other_gm, f"{sheet_path}/delete", {"version": npc.version, "confirm_name": npc.name})
    assert deleted.headers["location"] == f"{path}#npcs"
    assert other_gm.get(sheet_path).status_code == 404


def test_deleting_campaign_removes_npcs_and_drafts_and_detaches_player_characters(env):
    campaign = seed_campaign(env.gm, members=[env.player])
    player_character = seed_character(env.player, campaign)
    gm = env.login(env.gm)
    path = f"/campaigns/{campaign.id}"
    draft_id = gm.get(f"{path}/npcs/new").headers["location"].rsplit("/", 1)[1]
    with Session(engine(), expire_on_commit=False) as db:
        npc = Character(name="Campaign NPC", owner_id=env.gm.id, campaign_id=campaign.id, is_npc=True)
        db.add(npc)
        db.commit()
    discarded = env.post(gm, f"/api/character-drafts/{draft_id}/discard")
    assert discarded.json()["location"] == f"{path}#npcs"
    draft_id = gm.get(f"{path}/npcs/new").headers["location"].rsplit("/", 1)[1]
    assert env.post(gm, f"{path}/delete", {"version": campaign.version, "confirm_name": campaign.name}).status_code == 303
    with Session(engine()) as db:
        assert db.get(Character, npc.id) is None
        assert db.get(CharacterDraft, draft_id) is None
        assert db.get(Character, player_character.id).campaign_id is None


def test_campaign_npc_migration_preserves_existing_characters_and_drafts(env, isolated_database):
    character = seed_character(env.player)
    client = env.login(env.player)
    draft_id = client.get("/characters/new").headers["location"].rsplit("/", 1)[1]
    with isolated_database.begin() as connection:
        connection.execute(text("ALTER TABLE character_drafts DROP FOREIGN KEY fk_character_drafts_npc_campaign"))
        connection.execute(text("ALTER TABLE character_drafts DROP COLUMN npc_campaign_id"))
        connection.execute(text("ALTER TABLE characters DROP COLUMN is_npc"))
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(SchemaMigration, 30)
        assert db.get(Character, character.id).is_npc is False
        assert db.get(CharacterDraft, draft_id).npc_campaign_id is None
        assert db.scalar(select(Character.name)) == character.name

import secrets

from sqlalchemy.orm import Session

from pathkeeper.advancement import level_for
from pathkeeper.database import engine
from pathkeeper.models import Character
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character, char_form


def test_advancement_thresholds():
    for speed, second, twentieth in (
        ("slow", 3000, 5350000), ("medium", 2000, 3600000), ("fast", 1300, 2400000),
    ):
        assert level_for(second - 1, speed) == 1
        assert level_for(second, speed) == 2
        assert level_for(twentieth - 1, speed) == 19
        assert level_for(twentieth, speed) == 20


def test_xp_autosave_campaign_speed_and_detach(env):
    gm = env.login(env.gm)
    created = env.post(gm, "/campaigns", {"name": "Fast campaign", "xp_speed": "fast"})
    assert created.status_code == 303
    campaign_path = created.headers["location"]
    campaign_id = int(campaign_path.rsplit("/", 1)[1])
    assert 'value="fast" selected' in gm.get(campaign_path + "/edit").text
    assert env.post(gm, "/campaigns", {"name": "Invalid", "xp_speed": "instant"}).status_code == 422

    character = seed_character(env.gm)
    player_path = f"/characters/{character.id}"
    assert env.post(gm, player_path, char_form(character, campaign_id=campaign_id)).status_code == 303
    sheet = SheetForm(gm.get(player_path).text)
    assert {"level", "next_level"} <= sheet.readonly
    assert sheet.values["experience"] == "7500"
    assert sheet.values["level"] == "4"
    assert sheet.values["next_level"] == "10000"
    sheet.values.update(experience="1300", level="20", next_level="999")
    saved = gm.post(player_path + "/play-sheet", data=sheet.values, headers={
        "Accept": "application/json", "X-Sheet-Save-Id": secrets.token_hex(16),
    })
    assert saved.status_code == 200
    assert saved.json()["values"]["level"] == "2"
    assert saved.json()["values"]["next_level"] == "3300"
    assert env.post(gm, campaign_path, {"name": "Fast campaign", "version": 1, "xp_speed": "medium"}).status_code == 303
    with Session(engine()) as db:
        character = db.get(Character, character.id)
        assert character.level == 1
        assert character.play_data["experience"] == "1300"
    assert env.post(gm, campaign_path + "/delete", {"confirm_name": "Fast campaign", "version": 2}).status_code == 303
    assert SheetForm(gm.get(player_path).text).values["next_level"] == "3000"


def test_legacy_migration_preserves_recorded_xp_and_seeds_missing_xp(env, isolated_database):
    from sqlalchemy import text
    from pathkeeper.migrations import migrate

    legacy = seed_character(env.player)
    recorded = seed_character(env.player, name="Hero with XP")
    with Session(engine()) as db:
        db.get(Character, recorded.id).play_data = {"experience": "14000", "notes": "Keep this"}
        db.commit()
    with isolated_database.begin() as connection:
        connection.execute(text("ALTER TABLE campaigns DROP COLUMN xp_speed"))
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(Character, legacy.id).level == 3
        assert db.get(Character, legacy.id).play_data["experience"] == "7500"
        assert db.get(Character, recorded.id).level == 4
        assert db.get(Character, recorded.id).play_data == {"experience": "14000", "notes": "Keep this"}

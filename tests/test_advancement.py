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
    assert sheet.values["level"] == "3"
    assert sheet.values["next_level"] == "6000"
    sheet.values.update(experience="1300", level="20", next_level="999")
    saved = gm.post(player_path + "/play-sheet", data=sheet.values, headers={
        "Accept": "application/json", "X-Sheet-Save-Id": secrets.token_hex(16),
    })
    assert saved.status_code == 200
    assert saved.json()["values"]["level"] == "3"
    assert not saved.json()["can_level_up"]
    assert saved.json()["values"]["next_level"] == "6000"
    assert env.post(gm, campaign_path, {"name": "Fast campaign", "version": 1, "xp_speed": "medium"}).status_code == 303
    with Session(engine()) as db:
        character = db.get(Character, character.id)
        assert character.level == 3
        assert character.play_data["experience"] == "1300"
    assert env.post(gm, campaign_path + "/delete", {"confirm_name": "Fast campaign", "version": 2}).status_code == 303
    assert SheetForm(gm.get(player_path).text).values["next_level"] == "14000"


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
        assert db.get(Character, recorded.id).level == 3
        assert db.get(Character, recorded.id).play_data == {"experience": "14000", "notes": "Keep this"}

def test_wizard_gates_level_and_saves_choices_once(env):
    character = seed_character(env.player, name="Ready fighter")
    path = f"/characters/{character.id}"
    client = env.login(env.player)
    sheet = SheetForm(client.get(path).text)
    sheet.values.update({
        "experience": "23000", "ability.con.score": "13", "ability.int.score": "10",
        "hp.total": "20", "hp.current": "16", "bab": "3",
        "save.fortitude.base": "3", "save.reflex.base": "1", "save.will.base": "1",
    })
    saved = client.post(path + "/play-sheet", data=sheet.values, headers={
        "Accept": "application/json", "X-Sheet-Save-Id": secrets.token_hex(16),
    })
    assert saved.status_code == 200
    assert saved.json()["can_level_up"]
    assert saved.json()["values"]["level"] == "3"
    wizard = client.get(path + "/level-up")
    assert wizard.status_code == 200
    assert wizard.text.count('data-level-step>') == 3
    assert '>Current ranks</th>' in wizard.text and 'ItemName=Climb' in wizard.text
    assert 'Review and advance' not in wizard.text
    assert 'other_changes' not in wizard.text
    assert env.login(env.admin).get(path + "/level-up").status_code == 403
    data = {"version": saved.json()["version"], "target": 4, "hit_die": 5, "favored": "hp",
            "ability": "con", "rank_climb": 3, "choice_0": "Improved Initiative", "reviewed": "1"}
    invalid = env.post(client, path + "/level-up", {**data, "rank_climb": 2})
    assert invalid.status_code == 422
    assert "Assign exactly 3 skill ranks" in invalid.text
    ineligible = env.post(client, path + "/level-up", {**data, "choice_0": "Toughness"})
    assert ineligible.status_code == 422 and "Choose an available feat" in ineligible.text
    missing_score = env.post(client, path + "/level-up", {**data, "choice_0": "Power Attack"})
    assert missing_score.status_code == 422 and "ability score or base attack bonus" in missing_score.text
    assert env.post(client, path + "/level-up", data).status_code == 303
    assert env.post(client, path + "/level-up", data).status_code == 409
    page = client.get(path)
    assert "Improved Initiative" in page.text
    sheet = SheetForm(page.text)
    assert sheet.values["level"] == "4"
    assert sheet.values["next_level"] == "23000"
    assert sheet.values["experience"] == "23000"
    assert sheet.values["ability.con.score"] == "14"
    assert sheet.values["hp.total"] == "31"
    assert sheet.values["hp.current"] == "27"
    assert sheet.values["bab"] == "4"
    assert sheet.values["initiative.misc"] == "4"
    assert sheet.values["save.fortitude.base"] == "4"
    assert sheet.values["skill.climb.ranks"] == "3"
    assert env.post(client, path + "/play-sheet", sheet.values).status_code == 303
    with Session(engine()) as db:
        saved_character = db.get(Character, character.id)
        assert len(saved_character.play_data["advancement_history"]) == 1


def test_class_progression_tables_cover_all_selectable_classes():
    from pathkeeper.pf1_data import CLASS_PROGRESSIONS, CLASSES

    assert set(CLASS_PROGRESSIONS) == set(CLASSES)
    assert len(CLASSES) == 49
    assert all(len(profile["levels"]) == 20 for profile in CLASS_PROGRESSIONS.values())
    assert CLASS_PROGRESSIONS["fighter"]["levels"][19]["bab"] == 20
    assert CLASS_PROGRESSIONS["bard"]["levels"][19]["known"]["6"] == 5
    assert CLASS_PROGRESSIONS["arcanist"]["levels"][0]["slots"]["1"] == 2
    assert CLASS_PROGRESSIONS["arcanist"]["levels"][0]["prepared"]["0"] == 4
    assert CLASS_PROGRESSIONS["monk-unchained"]["levels"][0]["saves"] == [2, 2, 0]

def test_bard_level_up_requires_new_spells_and_updates_slots(env):
    character = seed_character(env.player, name="Advancing bard")
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.class_name, record.level = "Bard", 1
        record.play_data = {
            "experience": "3000", "ability.con.score": "10", "ability.int.score": "10",
            "ability.cha.score": "14", "hp.total": "8", "hp.current": "8",
            "spell.0.list": "Detect Magic", "spell.1.list": "Cure Light Wounds",
        }
        db.commit()
        version = record.version
    client = env.login(env.player)
    path = f"/characters/{character.id}"
    page = client.get(path + "/level-up")
    assert page.status_code == 200 and "Versatile performance" in page.text
    data = {"version": version, "target": 2, "hit_die": 4, "favored": "none", "rank_climb": 2,
            "rank_disguise": 2, "rank_bluff": 2, "rank_diplomacy": 1,
            "choice_0": "Oratory", "spells_0": "Light", "reviewed": "1"}
    assert env.post(client, path + "/level-up", data).status_code == 422
    assert env.post(client, path + "/level-up", {**data, "spells_1": "Charm Person"}).status_code == 303
    sheet = SheetForm(client.get(path).text)
    assert sheet.values["level"] == "2"
    assert sheet.values["spell.1.daily"] == "2"
    assert sheet.values["spell.1.bonus"] == "1"
    assert sheet.values["spell.1.list"] == "Cure Light Wounds\nCharm Person"
    assert sheet.values["caster_level"] == "2"

def test_migration_removes_only_retired_advancement_notes(env, isolated_database):
    from pathkeeper.migrations import migrate

    character = seed_character(env.player)
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.play_data = {
            "experience": "7500",
            "advancement_history": [{"level": 3, "choices": [], "notes": "Retired text"}],
        }
        db.commit()
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        assert record.notes == character.notes
        assert record.play_data == {
            "experience": "7500", "advancement_history": [{"level": 3, "choices": []}],
        }

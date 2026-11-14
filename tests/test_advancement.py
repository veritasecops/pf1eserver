import secrets

from sqlalchemy.orm import Session

from pathkeeper.advancement import level_for
from pathkeeper.character_rules import calculate, defaults
from pathkeeper.database import engine
from pathkeeper.models import Character
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_campaign, seed_character, char_form


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
    assert "Your XP qualifies you for level 5." in wizard.text
    assert "Advance to level 4 and continue" in wizard.text
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
    advanced = env.post(client, path + "/level-up", data)
    assert advanced.status_code == 303
    assert advanced.headers["location"] == path + "/level-up"
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

    next_level = client.get(advanced.headers["location"])
    assert 'name="target" value="5"' in next_level.text
    assert "Advance to level 5</button>" in next_level.text
    assert "Extra Bombs" not in next_level.text
    assert "Extra Discovery" not in next_level.text
    second = {"version": SheetForm(client.get(path).text).values["version"], "target": 5, "hit_die": 5, "favored": "none",
              "rank_climb": 2, "rank_swim": 1, "choice_0": "Toughness", "choice_1": "Axes"}
    for feat in ("Extra Bombs", "Extra Discovery", "Implant Bomb"):
        blocked = env.post(client, path + "/level-up", {**second, "choice_0": feat})
        assert blocked.status_code == 422
        assert "Choose an available feat for General feat" in blocked.text
    # An earlier level's ranks count toward the cap for the next level.
    invalid = env.post(client, path + "/level-up", {**second, "rank_climb": 3})
    assert invalid.status_code == 422
    completed = env.post(client, path + "/level-up", second)
    assert completed.status_code == 303
    assert completed.headers["location"] == path
    assert env.post(client, path + "/level-up", second).status_code == 409
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        assert record.level == 5
        assert record.play_data["experience"] == "23000"
        assert record.play_data["skill.climb.ranks"] == "5"
        assert [entry["level"] for entry in record.play_data["advancement_history"]] == [4, 5]


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

def test_bard_level_up_preserves_spells_and_updates_slots(env):
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
    assert 'name="spells_' not in page.text and 'name="swap_spell"' not in page.text
    assert env.post(client, path + "/level-up", {**data, "spells_1": "Charm Person",
                                              "swap_spell": "1.0", "replacement_spell": "Shield"}).status_code == 303
    sheet = SheetForm(client.get(path).text)
    assert sheet.values["level"] == "2"
    assert sheet.values["spell.1.daily"] == "2"
    assert sheet.values["spell.1.bonus"] == "1"
    assert sheet.values["spell.1.list"] == "Cure Light Wounds"
    assert sheet.values["spell.0.list"] == "Detect Magic"
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


def test_class_feat_gate_uses_features_granted_by_the_target_level():
    from types import SimpleNamespace

    from pathkeeper.class_catalog import class_profile
    from pathkeeper.feat_class_requirements import class_feat_gate

    character = SimpleNamespace(play_data={})

    def blocked(class_id, target):
        profile = class_profile({}, class_id)
        return class_feat_gate(character, {}, {class_id: target}, profile["levels"][target - 1]["bab"], [])

    assert "extra bombs" not in blocked("alchemist", 1)
    assert "extra discovery" in blocked("alchemist", 1)
    assert "extra discovery" not in blocked("alchemist", 2)
    assert "implant bomb" in blocked("alchemist", 8)
    assert "planar preservationist" in blocked("alchemist", 8)
    assert "advanced weapon training" in blocked("fighter", 4)
    assert "advanced weapon training" not in blocked("fighter", 5)
    assert "advanced weapon training" in blocked("barbarian", 10)
    assert "extra bombs" in class_feat_gate(character, {}, {"fighter": 5}, 5, [("Bomb", "")])


def test_multiclass_advancement_uses_class_and_character_levels(env):
    character = seed_character(env.player, name="Fighter learning magic")
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.play_data = {
            "experience": "23000", "alignment": "N", "hp.total": "24", "hp.current": "20",
            "ability.con.score": "12", "ability.int.score": "13", "skill.spellcraft.ranks": "1",
        }
        db.commit()
    client = env.login(env.player)
    path = f"/characters/{character.id}"
    wizard = client.get(path + "/level-up?class_id=wizard")
    assert wizard.status_code == 200
    assert "Wizard 1" in wizard.text and "CHARACTER LEVEL 4" in wizard.text
    assert 'name="ability"' in wizard.text and "Arcane school" in wizard.text
    assert client.get(path + "/level-up?class_id=paladin").status_code == 422
    data = {
        "version": SheetForm(client.get(path).text).values["version"],
        "class_id": "wizard", "target": 4, "hit_die": 4, "ability": "int", "favored": "none",
        "rank_spellcraft": 3, "rank_knowledge-arcana": 4, "rank_climb": 1,
        "choice_0": "Familiar", "choice_1": "Universalist",
    }
    assert env.post(client, path + "/level-up", {**data, "favored": "hp"}).status_code == 422
    assert env.post(client, path + "/level-up", data).status_code == 303
    page = client.get(path)
    sheet = SheetForm(page.text)
    assert sheet.values["class_name"] == "Fighter 3 / Wizard 1"
    assert sheet.values["level"] == "4"
    assert sheet.values["hp.total"] == "29"
    assert sheet.values["bab"] == "3" and "bab" in sheet.readonly
    assert [sheet.values[f"save.{key}.base"] for key in ("fortitude", "reflex", "will")] == ["3", "1", "3"]
    assert sheet.values["skill.spellcraft.total"] == "9"
    assert sheet.values["caster_level"] == "1"
    assert "Scribe Scroll" in page.text
    assert env.post(client, path + "/play-sheet", sheet.values).status_code == 303
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        assert record.play_data["class_levels"] == [["fighter", 3], ["wizard", 1]]
        assert record.play_data["advancement_history"][0]["class_level"] == 1
    wizard = client.get(path + "/level-up?class_id=fighter")
    assert "Fighter 4" in wizard.text and "CHARACTER LEVEL 5" in wizard.text
    assert "General feat" in wizard.text and "Bonus feat" in wizard.text


def test_legacy_multiclass_spellbooks_save_independently(env):
    character = seed_character(env.player, name="Arcane and divine caster")
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.class_name = "Cleric of Shax 2 / Wizard 1"
        record.play_data = {
            "spell.1.list": "Bless", "ability.int.score": "14",
            "ability.wis.score": "16", "ability.con.score": "10", "hp.total": "18",
            "experience": "14000",
        }
        db.commit()
    client = env.login(env.player)
    path = f"/characters/{character.id}"
    page = client.get(path)
    assert "Cleric Spells" in page.text and "Wizard Spells" in page.text
    assert "Caster level 1 · Intelligence casting · Concentration +3" in page.text
    assert "Save DC 13" in page.text
    sheet = SheetForm(page.text)
    classes = {"version": sheet.values["version"], "favored_class": "cleric", "level.cleric": 2, "level.wizard": 1}
    assert env.post(client, path + "/classes", {**classes, "level.wizard": 2}).status_code == 422
    assert env.post(client, path + "/classes", classes).status_code == 303
    sheet = SheetForm(client.get(path).text)
    sheet.values.update({"spellbook.wizard.1.list": "Magic Missile", "spellbook.wizard.1.used.0": "1"})
    assert env.post(client, path + "/play-sheet", sheet.values).status_code == 303
    page = client.get(path)
    assert '>Magic Missile</a>' in page.text
    sheet = SheetForm(page.text)
    assert sheet.values["spell.1.list"] == "Bless"
    assert sheet.values["spellbook.wizard.1.list"] == "Magic Missile"
    assert sheet.values["spellbook.wizard.1.used.0"] == "1"
    assert "spell.1.used.0" not in sheet.values


def test_npc_can_advance_in_a_second_favored_class(env):
    campaign = seed_campaign(env.gm)
    character = seed_character(env.gm, campaign, name="NPC arcanist")
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.is_npc = True
        record.ancestry = "Half-Elf"
        record.level = 1
        record.play_data = {
            "experience": "3000", "alignment": "N", "hp.total": "10",
            "ability.int.score": "10", "ability.con.score": "10",
        }
        db.commit()
    gm = env.login(env.gm)
    path = f"/characters/{character.id}"
    assert "Second favored class" in gm.get(path + "/level-up?class_id=rogue").text
    data = {
        "version": SheetForm(gm.get(path).text).values["version"], "class_id": "rogue",
        "target": 2, "hit_die": 4, "favored": "hp", "second_favored": "rogue",
        "rank_climb": 2, "rank_stealth": 2, "rank_perception": 2, "rank_bluff": 2,
    }
    assert env.post(gm, path + "/level-up", data).status_code == 303
    assert SheetForm(gm.get(path).text).values["hp.total"] == "15"
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        assert record.play_data["favored_classes"] == ["fighter", "rogue"]


def test_starting_class_reward_requires_a_favored_class():
    creation = defaults(1)
    creation.update(race="half-elf", class_id="fighter", favored_class="wizard", favored_bonus="hp")
    assert calculate(creation, {})["hp"] == 10
    creation["second_favored"] = "fighter"
    assert calculate(creation, {})["hp"] == 11


def test_shared_class_features_keep_both_sources(env):
    character = seed_character(env.player)
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.level = 4
        record.class_name = "Rogue 1 / Slayer 3"
        db.commit()
    client = env.login(env.player)
    path = f"/characters/{character.id}"
    page = client.get(path)
    assert 'data-remove-class-ability="rogue:sneak attack"' in page.text
    assert 'data-remove-class-ability="slayer:sneak attack"' in page.text
    assert "+2d6" in page.text
    version = SheetForm(page.text).values["version"]
    assert env.post(client, path + "/class-abilities/remove", {
        "ability": "rogue:sneak attack", "version": version,
    }).status_code == 200
    page = client.get(path)
    assert 'data-remove-class-ability="rogue:sneak attack"' not in page.text
    assert 'data-remove-class-ability="slayer:sneak attack"' in page.text
    assert "+2d6" not in page.text and "+1d6" in page.text

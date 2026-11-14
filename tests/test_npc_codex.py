from collections import Counter

from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character
from pathkeeper.npc_codex import entries

from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_campaign


def test_published_npc_codex_coverage():
    codex = entries()
    assert Counter(item["category"] for item in codex.values()) == {
        "Core class": 220, "Prestige class": 40, "NPC class": 50, "Iconic": 33, "Animal companion": 45,
    }
    assert codex["savage-mercenary"]["page"] == 10
    assert codex["small-cat-20"]["page"] == 307
    assert "DC 19" in dict(codex["viper-snake-18-19"]["sections"]["Special Abilities"])["Poison"]
    assert all(len(item["scores"]) == 6 and item["hp"] > 0 and
               (sum(level for _, level in item["classes"]) == item["level"] or item.get("companion_level"))
               for item in codex.values())


def test_npc_codex_access_filters_and_editable_campaign_copies(env):
    campaign = seed_campaign(env.gm, members=[env.player])
    campaign_path = f"/campaigns/{campaign.id}"
    catalog_path = campaign_path + "/npcs/catalog"
    gm = env.login(env.gm)
    player = env.login(env.player)
    admin = env.login(env.admin)
    assert "Add NPC" in gm.get(campaign_path).text
    assert "Add NPC" not in player.get(campaign_path).text
    assert gm.get("/administration/npc-codex").status_code == 403
    admin_page = admin.get("/administration/npc-codex").text
    assert 'href="/administration/npc-codex" class="active"' in admin_page
    assert "388 entries" in admin_page
    assert "33 entries" in admin.get("/administration/npc-codex", params={"category": "Iconic"}).text
    assert admin.get("/administration/npc-codex/not-found").status_code == 404
    assert player.get(catalog_path).status_code == 403
    assert env.post(player, catalog_path, {"npc_key": "savage-mercenary"}).status_code == 403
    assert gm.post(catalog_path, data={"npc_key": "savage-mercenary"}).status_code == 403
    assert env.post(gm, catalog_path, {"npc_key": "missing"}).status_code == 404
    selection = gm.get(catalog_path, params={"q": "savage mercenary"})
    assert "1 entry" in selection.text and "Savage Mercenary" in selection.text
    detail = gm.get(catalog_path + "/savage-mercenary")
    assert "NPC Codex, p. 10" in detail.text and "greatsword" in detail.text

    added = env.post(gm, catalog_path, {"npc_key": "savage-mercenary"})
    assert added.status_code == 303
    path = added.headers["location"]
    assert path in gm.get(campaign_path).text
    assert player.get(path).status_code == 404
    sheet = SheetForm(gm.get(path).text)
    assert {key: sheet.values[key] for key in (
        "hp.total", "ability.str.score", "ac.total", "ac.touch", "ac.flat", "save.fortitude.total", "weapon.0.name"
    )} == {
        "hp.total": "17", "ability.str.score": "21", "ac.total": "15", "ac.touch": "9",
        "ac.flat": "14", "save.fortitude.total": "6", "weapon.0.name": "greatsword",
    }
    sheet.values.update({"name": "Campaign mercenary", "hp.current": "13", "ability.str.score": "22"})
    assert env.post(gm, path + "/play-sheet", sheet.values).status_code == 303
    edited = SheetForm(gm.get(path).text)
    assert edited.values["name"] == "Campaign mercenary"
    assert edited.values["hp.current"] == "13"
    assert edited.values["ability.str.score"] == "22"
    second = env.post(gm, catalog_path, {"npc_key": "savage-mercenary"})
    second_path = second.headers["location"]
    assert second_path != path
    assert SheetForm(gm.get(second_path).text).values["hp.current"] == "17"
    with Session(engine()) as db:
        character = db.get(Character, int(path.rsplit("/", 1)[1]))
        assert character.is_npc and character.campaign_id == campaign.id and character.owner_id == env.gm.id


def test_prestige_stat_block_retains_separate_casters(env):
    campaign = seed_campaign(env.gm)
    gm = env.login(env.gm)
    added = env.post(gm, f"/campaigns/{campaign.id}/npcs/catalog", {"npc_key": "death-master"})
    assert added.status_code == 303
    page = gm.get(added.headers["location"])
    assert "Caster level 12 · Intelligence casting · Concentration +15" in page.text
    sheet = SheetForm(page.text)
    assert sheet.values["caster_level"] == "12"
    assert "dimensional anchor" in sheet.values["spell.4.list"]
    assert "magic missile" in sheet.values["spellbook.wizard.1.list"]
    assert sheet.values["bab"] == "8"
    assert sheet.values["save.will.total"] == "20"
    assert env.post(gm, added.headers["location"] + "/play-sheet", sheet.values).status_code == 303

from collections import Counter

from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character
from pathkeeper.npc_codex import browse, entries
from pathkeeper.npc_codex_editor import editor_values, parse_entry

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
    assert all(parse_entry(editor_values(item), item, {})["scores"] == item["scores"] for item in codex.values())


def test_codex_filters_combine_and_match_companion_level_ranges():
    result = browse({"ancestry": "Human", "level": "1", "cr": "1/2", "category": "Core class"})
    assert "savage-mercenary" in dict(result["items"])
    assert all(item["ancestry"] == "Human" and item["level"] == 1 and item["cr"] == "1/2"
               for _, item in result["items"])
    assert result["filter_options"]["cr"][:3] == ["1/3", "1/2", "1"]
    for level in ("10", "11"):
        result = browse({"ancestry": "Animal", "level": level, "cr": "none", "q": "horse"})
        assert list(dict(result["items"])) == ["horse-10-11"]
    assert browse({"ancestry": "invalid", "level": "-1", "cr": "invalid"})["total"] == 388


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
    assert "/edit?from=list&amp;page=1" in admin_page
    assert '<th scope="col">Page</th>' not in admin_page
    assert "33 entries" in admin.get("/administration/npc-codex", params={"category": "Iconic"}).text
    assert admin.get("/administration/npc-codex/not-found").status_code == 404
    assert player.get(catalog_path).status_code == 403
    assert env.post(player, catalog_path, {"npc_key": "savage-mercenary"}).status_code == 403
    assert gm.post(catalog_path, data={"npc_key": "savage-mercenary"}).status_code == 403
    assert env.post(gm, catalog_path, {"npc_key": "missing"}).status_code == 404
    selection = gm.get(catalog_path, params={"q": "savage mercenary", "ancestry": "Human", "level": "1", "cr": "1/2"})
    assert "1 entry" in selection.text and "Savage Mercenary" in selection.text
    assert '<th scope="col">Page</th>' not in selection.text
    assert "/edit?from=list" not in selection.text
    filters = "q=savage+mercenary&amp;ancestry=Human&amp;level=1&amp;cr=1%2F2&amp;page=1"
    assert f'href="{catalog_path}/savage-mercenary?{filters}"' in selection.text
    detail = gm.get(catalog_path + "/savage-mercenary", params={"q": "savage mercenary", "ancestry": "Human", "level": 1, "cr": "1/2"})
    assert f'href="{catalog_path}?{filters}"' in detail.text
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


def test_admin_edits_codex_templates_without_changing_existing_campaign_copies(env):
    campaign = seed_campaign(env.gm)
    gm, admin = env.login(env.gm), env.login(env.admin)
    catalog = f"/campaigns/{campaign.id}/npcs/catalog"
    detail = "/administration/npc-codex/savage-mercenary"
    edit = detail + "/edit"
    assert "Edit NPC" in admin.get(detail).text
    assert admin.get(edit).status_code == 200
    assert gm.get(edit).status_code == 403
    before = env.post(gm, catalog, {"npc_key": "savage-mercenary"}).headers["location"]
    item = entries()["savage-mercenary"]
    values = {**editor_values(item), "version": 0, "name": "Veteran mercenary", "hp": 28}
    assert env.post(gm, edit, values).status_code == 403
    assert admin.post(edit, data=values).status_code == 403
    invalid = env.post(admin, edit, {**values, "Statistics": "Feats: Cleave"})
    assert invalid.status_code == 422 and "Keep the Base Atk line" in invalid.text
    values["Offense"] = values["Offense"].replace("Speed: 30 ft.", "Speed: 40 ft.")
    assert env.post(admin, edit, values).status_code == 303
    assert env.post(admin, edit, values).status_code == 409
    assert "Veteran mercenary" in gm.get(catalog, params={"q": "veteran mercenary"}).text
    after = env.post(gm, catalog, {"npc_key": "savage-mercenary"}).headers["location"]
    old, new = [SheetForm(gm.get(path).text).values for path in (before, after)]
    assert (old["name"], old["hp.total"]) == ("Savage Mercenary", "17")
    assert (new["name"], new["hp.total"], new["speed.armor"]) == ("Veteran mercenary", "28", "40")


def test_editing_from_codex_list_keeps_filters_and_page(env):
    admin = env.login(env.admin)
    base = "/administration/npc-codex"
    params = "ancestry=Human&page=2"
    result = browse({"ancestry": "Human", "page": "2"})
    key, item = result["items"][0]
    edit = f"{base}/{key}/edit?from=list&{params}"
    back = f'{base}?ancestry=Human&amp;page=2'
    page = admin.get(f"{base}?{params}")
    assert f'href="{edit.replace("&", "&amp;")}"' in page.text
    form = admin.get(edit)
    assert form.status_code == 200 and f'href="{back}">Cancel' in form.text
    values = {**editor_values(item), "version": 0, "hp": item["hp"] + 1}
    invalid = env.post(admin, edit, {**values, "hp": 0})
    assert invalid.status_code == 422 and f'href="{back}">Cancel' in invalid.text
    saved = env.post(admin, edit, values)
    assert saved.status_code == 303 and saved.headers["location"] == f"{base}?{params}"

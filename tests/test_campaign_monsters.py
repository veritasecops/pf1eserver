from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.migrations import migrate
from pathkeeper.models import Campaign, CampaignMonster, SchemaMigration
from .test_workspace import seed_campaign


def test_campaign_monster_index_adds_separate_copies_and_keeps_them_scoped(env):
    campaign = seed_campaign(env.gm, members=[env.player, env.gm2])
    other_campaign = seed_campaign(env.gm, name="Other campaign")
    campaign_path = f"/campaigns/{campaign.id}"
    block = f"{campaign_path}#monster-index"
    index = f"{campaign_path}/monsters"
    catalog = f"{index}/catalog"
    key = sha256(b"Akata").hexdigest()
    form = {"monster_key": key}

    gm = env.login(env.gm)
    page = gm.get(campaign_path).text
    assert page.index('id="npcs"') < page.index('id="monster-index"')
    assert f'href="{catalog}"' in page
    assert "No monsters added yet." in page
    assert gm.get(index).headers["location"] == block
    picker = gm.get(catalog, params={"letter": "A", "q": "akata"}).text
    assert "Akata" in picker and f'href="{block}"' in picker
    assert 'name="quantity"' in picker
    detail = gm.get(f"{index}/{key}").text
    assert "15 (2d8+6)" in detail and f'href="{block}"' in detail
    assert env.post(gm, index, form, use_csrf=False).status_code == 403
    assert env.post(gm, index, {"monster_key": "unknown"}).status_code == 404
    add = f"{index}?letter=A&q=akata&page=1"
    for invalid in ("", "0", "101", "1.5"):
        assert env.post(gm, add, {**form, "quantity": invalid}).status_code == 422
    assert "No monsters added yet." in gm.get(campaign_path).text
    for batch in ({**form, "quantity": "3"}, form):
        response = env.post(gm, add, batch)
        assert response.status_code == 303
        assert response.headers["location"] == f"{catalog}?letter=A&q=akata&page=1"
    picker = gm.get(catalog, params={"q": "akata"}).text
    assert "4 in roster" in picker and 'aria-label="Add Akata"' in picker
    roster = gm.get(campaign_path).text
    assert roster.count('>Akata</a>') == 4
    assert "Akata" not in gm.get(f"/campaigns/{other_campaign.id}").text
    with Session(engine()) as db:
        copies = db.query(CampaignMonster).order_by(CampaignMonster.id).all()
        assert len(copies) == 4
        ids = [copy.id for copy in copies]
    for copy_id in ids:
        assert f'name="monster_id" value="{copy_id}"' in roster
        assert f'href="{index}/roster/{copy_id}">Akata</a>' in roster
    remove = {"monster_id": ids[1]}
    assert env.post(gm, f"/campaigns/{other_campaign.id}/monsters/remove", remove).status_code == 404
    edit = f"{index}/roster/{ids[0]}/edit"
    assert f'href="{edit}#campaign-monster-notes">Add notes</a>' in gm.get(edit.removesuffix("/edit")).text
    editor = gm.get(edit)
    assert editor.status_code == 200 and "15 (2d8+6)" in editor.text
    assert 'id="campaign-monster-notes" name="notes"' in editor.text
    stat_field = next(
        f"stat_{i}_{j}" for i, section in enumerate(copies[0].stat_block["sections"])
        for j, (label, _) in enumerate(section["fields"]) if label == "hp"
    )
    update = {"version": copies[0].version, "name": "Wounded Akata", "notes": "Found in the ruins.",
              stat_field: "9 (2d8+6)"}
    response = env.post(gm, edit, update)
    assert response.headers["location"] == f"{index}/roster/{ids[0]}"
    assert env.post(gm, edit, update).status_code == 409
    updated = gm.get(response.headers["location"]).text
    assert "Wounded Akata" in updated and "9 (2d8+6)" in updated and "Found in the ruins." in updated
    assert f'href="{edit}#campaign-monster-notes">Edit notes</a>' in updated
    other_copy = gm.get(f"{index}/roster/{ids[1]}").text
    assert "15 (2d8+6)" in other_copy and "Found in the ruins." not in other_copy
    assert "15 (2d8+6)" in gm.get(f"{index}/{key}").text
    assert gm.get(f"/campaigns/{other_campaign.id}/monsters/roster/{ids[0]}").status_code == 404

    for account in (env.player, env.gm2):
        member = env.login(account)
        assert 'id="monster-index"' not in member.get(campaign_path).text
        assert member.get(index).status_code == 403
        assert member.get(catalog).status_code == 403
        assert member.get(f"{index}/{key}").status_code == 403
        assert env.post(member, index, form).status_code == 403
        assert env.post(member, f"{index}/remove", remove).status_code == 403
        assert member.get(edit).status_code == 403
        assert env.post(member, edit, update).status_code == 403
    outsider = env.login(env.player2)
    assert outsider.get(index).status_code == 404

    admin = env.login(env.admin)
    assert "Akata" in admin.get(campaign_path).text
    assert env.post(admin, f"{index}/remove", remove).headers["location"] == block
    roster = gm.get(campaign_path).text
    assert roster.count('>Akata</a>') == 2
    assert ">Wounded Akata</a>" in roster
    assert f'name="monster_id" value="{ids[1]}"' not in roster
    with Session(engine()) as db:
        assert db.get(Campaign, campaign.id).version == campaign.version
    assert env.post(gm, f"{campaign_path}/delete", {
        "version": campaign.version, "confirm_name": campaign.name,
    }).status_code == 303
    with Session(engine()) as db:
        assert db.query(CampaignMonster).count() == 0


def test_campaign_monster_index_migration_is_repeatable(env, isolated_database):
    campaign = seed_campaign(env.gm)
    key = sha256(b"Akata").hexdigest()
    with isolated_database.begin() as connection:
        connection.execute(text("DROP TABLE campaign_monsters"))
        connection.execute(text(
            "CREATE TABLE campaign_monsters (campaign_id BIGINT NOT NULL, monster_key VARCHAR(64) NOT NULL, "
            "PRIMARY KEY (campaign_id, monster_key), FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE)"
        ))
        connection.execute(text("INSERT INTO campaign_monsters (campaign_id, monster_key) VALUES (:campaign, :key)"),
                           {"campaign": campaign.id, "key": key})
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(SchemaMigration, 32)
        assert db.get(SchemaMigration, 33)
        assert db.get(Campaign, campaign.id).name == campaign.name
        copy = db.query(CampaignMonster).one()
        assert (copy.campaign_id, copy.monster_key) == (campaign.id, key)
        assert copy.stat_block["entry"]["name"] == "Akata"
        assert copy.stat_block["sections"]
        db.add(CampaignMonster(campaign_id=campaign.id, monster_key=key, stat_block=copy.stat_block))
        db.flush()
        assert db.query(CampaignMonster).count() == 2

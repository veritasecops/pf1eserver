from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.migrations import migrate
from pathkeeper.models import Campaign, CampaignMonster, SchemaMigration
from .test_workspace import seed_campaign


def test_campaign_monster_index_reuses_catalog_and_keeps_selections_scoped(env):
    campaign = seed_campaign(env.gm, members=[env.player, env.gm2])
    other_campaign = seed_campaign(env.gm, name="Other campaign")
    campaign_path = f"/campaigns/{campaign.id}"
    index = f"{campaign_path}/monsters"
    catalog = f"{index}/catalog"
    key = sha256(b"Akata").hexdigest()
    form = {"monster_key": key}

    gm = env.login(env.gm)
    assert f'href="{index}"' in gm.get(campaign_path).text
    assert "No monsters added yet." in gm.get(index).text
    assert "Akata" in gm.get(catalog, params={"letter": "A", "q": "akata"}).text
    assert "15 (2d8+6)" in gm.get(f"{index}/{key}").text
    assert env.post(gm, index, form, use_csrf=False).status_code == 403
    assert env.post(gm, index, {"monster_key": "unknown"}).status_code == 404
    add = f"{index}?letter=A&q=akata&page=1"
    for _ in range(2):
        response = env.post(gm, add, form)
        assert response.status_code == 303
        assert response.headers["location"] == f"{catalog}?letter=A&q=akata&page=1"
    assert "Added</span>" in gm.get(catalog, params={"q": "akata"}).text
    assert "Akata" in gm.get(index).text
    assert "Akata" not in gm.get(f"/campaigns/{other_campaign.id}/monsters").text
    with Session(engine()) as db:
        assert db.query(CampaignMonster).count() == 1

    for account in (env.player, env.gm2):
        member = env.login(account)
        assert f'href="{index}"' not in member.get(campaign_path).text
        assert member.get(index).status_code == 403
        assert member.get(catalog).status_code == 403
        assert member.get(f"{index}/{key}").status_code == 403
        assert env.post(member, index, form).status_code == 403
        assert env.post(member, f"{index}/remove", form).status_code == 403
    outsider = env.login(env.player2)
    assert outsider.get(index).status_code == 404

    admin = env.login(env.admin)
    assert "Akata" in admin.get(index).text
    assert env.post(admin, f"{index}/remove", form).headers["location"] == index
    assert "No monsters added yet." in gm.get(index).text
    assert env.post(gm, add, form).status_code == 303
    with Session(engine()) as db:
        assert db.get(Campaign, campaign.id).version == campaign.version
    assert env.post(gm, f"{campaign_path}/delete", {
        "version": campaign.version, "confirm_name": campaign.name,
    }).status_code == 303
    with Session(engine()) as db:
        assert db.get(CampaignMonster, (campaign.id, key)) is None


def test_campaign_monster_index_migration_is_repeatable(env, isolated_database):
    campaign = seed_campaign(env.gm)
    with isolated_database.begin() as connection:
        connection.execute(text("DROP TABLE campaign_monsters"))
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        assert db.get(SchemaMigration, 32)
        assert db.get(Campaign, campaign.id).name == campaign.name
        assert db.query(CampaignMonster).count() == 0

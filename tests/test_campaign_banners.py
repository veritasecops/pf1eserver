from io import BytesIO

from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.migrations import migrate
from pathkeeper.models import Campaign, SchemaMigration
from pathkeeper.portraits import DEFAULT_HEADER_BACKGROUND
from .test_portraits import picture, upload
from .test_workspace import seed_campaign


def test_campaign_banner_visibility_and_permissions(env):
    campaign = seed_campaign(env.gm, members=[env.player, env.gm2])
    path = f"/campaigns/{campaign.id}"
    banner = f"{path}/banner"
    gm = env.login(env.gm)
    assert 'aria-label="Change campaign banner"' in gm.get(path).text
    assert gm.get(banner).headers["location"] == DEFAULT_HEADER_BACKGROUND
    assert upload(env, gm, banner, use_csrf=False).status_code == 403

    saved = upload(env, gm, banner, picture(size=(1800, 900)))
    assert saved.status_code == 200 and saved.json()["custom"]
    image = gm.get(saved.json()["url"])
    assert image.status_code == 200
    assert "no-store" in image.headers["cache-control"]
    with Image.open(BytesIO(image.content)) as resized:
        assert resized.size == (1600, 800)
        assert resized.format == "JPEG"

    for account in (env.player, env.gm2):
        member = env.login(account)
        page = member.get(path).text
        assert f'data-campaign-banner src="{banner}"' in page
        assert 'aria-label="Change campaign banner"' not in page
        assert member.get(banner).content == image.content
        assert upload(env, member, banner).status_code == 403
        assert env.post(member, f"{banner}/remove").status_code == 403
    outsider = env.login(env.player2)
    assert outsider.get(banner).status_code == 404
    assert upload(env, outsider, banner).status_code == 404
    assert upload(env, gm, banner, b"<svg/>").status_code == 422
    assert gm.get(banner).content == image.content

    admin = env.login(env.admin)
    assert upload(env, admin, banner).status_code == 200
    assert env.post(admin, f"{banner}/remove", use_csrf=False).status_code == 403
    reset = env.post(admin, f"{banner}/remove")
    assert reset.json() == {"url": DEFAULT_HEADER_BACKGROUND, "custom": False}
    assert f'data-campaign-banner src="{DEFAULT_HEADER_BACKGROUND}"' in gm.get(path).text
    with Session(engine()) as db:
        stored = db.get(Campaign, campaign.id)
        assert stored.banner is None
        assert stored.version == campaign.version


def test_campaign_banner_migration_preserves_existing_campaigns(env, isolated_database):
    campaign = seed_campaign(env.gm)
    with isolated_database.begin() as connection:
        connection.execute(text("ALTER TABLE campaigns DROP COLUMN banner"))
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        stored = db.get(Campaign, campaign.id)
        assert stored.name == campaign.name and stored.banner is None
        assert db.get(SchemaMigration, 31)


def test_campaign_cards_show_saved_banners_and_return_to_default_on_reset(env):
    campaign = seed_campaign(env.gm, members=[env.player])
    default = seed_campaign(env.gm, name="Default cover", members=[env.player])
    gm, member, outsider = (env.login(account) for account in (env.gm, env.player, env.player2))
    banner = f"/campaigns/{campaign.id}/banner"
    cover = f'class="campaign-cover-image" src="{banner}"'

    for listing in ("/", "/campaigns"):
        assert cover not in member.get(listing).text

    assert upload(env, gm, banner, picture("navy")).status_code == 200
    for listing in ("/", "/campaigns"):
        for client in (gm, member):
            page = client.get(listing).text
            assert cover in page
            assert f'src="/campaigns/{default.id}/banner"' not in page
        assert cover not in outsider.get(listing).text
    first = member.get(banner)
    assert first.status_code == 200 and "no-store" in first.headers["cache-control"]
    assert upload(env, gm, banner, picture("green")).status_code == 200
    assert member.get(banner).content != first.content

    assert env.post(gm, f"{banner}/remove").status_code == 200
    for listing in ("/", "/campaigns"):
        assert cover not in member.get(listing).text

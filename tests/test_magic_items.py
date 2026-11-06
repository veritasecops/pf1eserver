from pathkeeper.catalog_admin import magic_items


def test_magic_item_snapshot_keeps_every_group_and_ioun_stone_variants():
    items = magic_items()
    assert len(items) == 4989
    assert len({item['group'] for item in items}) == 11
    assert all(item['url'].startswith('https://www.aonprd.com/') for item in items)
    amethyst = [item for item in items if item['name'] == 'Amethyst' and 'Ioun Stones' in item['categories']]
    assert {item['fields']['Strength']: item['fields']['Cost'] for item in amethyst} == {
        'Cracked': '150 gp', 'Flawed': '6,000 gp', 'Normal': '8,000 gp',
    }


def test_admin_magic_item_catalog_search_filters_and_pages(env):
    path = '/administration/magic-items'
    assert env.login(env.player).get(path).status_code == 403
    admin = env.login(env.admin)
    listing = admin.get(path)
    assert listing.status_code == 200
    assert '4989 entries' in listing.text and 'Page 1 of 50' in listing.text
    assert listing.text.index('href="/administration/equipment"') < listing.text.index(f'href="{path}"')
    assert f'href="{path}" class="active" aria-current="page"' in listing.text

    result = admin.get(path, params={'q': 'Ring of Invisibility', 'group': 'Rings'})
    assert result.status_code == 200 and '1 entry' in result.text
    assert 'FinalName=Ring%20of%20Invisibility' in result.text and '20,000 gp' in result.text
    page = admin.get(path, params={'group': 'Wondrous Items', 'category': 'Ioun Stones', 'page': 2})
    assert '143 entries' in page.text and 'Page 2 of 2' in page.text
    assert 'group=Wondrous+Items&amp;category=Ioun+Stones&amp;page=1' in page.text

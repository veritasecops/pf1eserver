from pathkeeper.catalog_admin import spells


def test_spell_snapshot_includes_published_class_levels_and_mythic_versions():
    entries = spells()
    urls = {spell['url'] for spell in entries}
    assert len(entries) == len(urls) == 3039
    assert all(url.startswith('https://www.aonprd.com/SpellDisplay.aspx?ItemName=') for url in urls)
    assert all(spell['schools'] for spell in entries)
    assert sum(spell['mythic'] for spell in entries) == 287
    fireball = next(spell for spell in entries if spell['name'] == 'Fireball')
    assert fireball['schools'] == ['Evocation']
    assert fireball['levels']['Wizard'] == [3]
    assert fireball['mythic']


def test_spells_tab_is_admin_only_and_filters_class_and_level_together(env):
    path = '/administration/catalog'
    assert env.login(env.player).get(path, params={'kind': 'spells'}).status_code == 403
    admin = env.login(env.admin)
    assert 'href="/administration/catalog?kind=spells"' in admin.get(path).text

    listing = admin.get(path, params={'kind': 'spells', 'page': 2})
    assert listing.status_code == 200
    assert '3039 spells' in listing.text and 'Page 2 of 61' in listing.text
    assert 'kind=spells" class="active" aria-current="page"' in listing.text
    assert 'kind=spells&amp;q=&amp;school=&amp;class=&amp;level=&amp;mythic=&amp;page=1' in listing.text

    filters = {'kind': 'spells', 'q': 'Adoration', 'class': 'Bard', 'school': 'Enchantment'}
    match = admin.get(path, params={**filters, 'level': 1})
    assert '1 spell' in match.text and 'SpellDisplay.aspx?ItemName=Adoration' in match.text
    assert 'No matching spells.' in admin.get(path, params={**filters, 'level': 2}).text
    assert 'No matching spells.' in admin.get(path, params={**filters, 'mythic': '1'}).text

from sqlalchemy.orm import Session

from pathkeeper.catalog_admin import spell_defaults, spells
from pathkeeper.database import engine
from pathkeeper.models import RuleCatalog


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


def test_admin_can_edit_spell_and_filters_use_saved_values(env):
    path = '/administration/catalog/spells'
    key = next(key for key, spell in spell_defaults().items() if spell['name'] == 'Fireball')
    admin = env.login(env.admin)
    player = env.login(env.player)
    form = {'key': key, 'version': 1, 'name': 'House Fireball', 'schools': ['Conjuration'],
            'url': 'https://www.aonprd.com/SpellDisplay.aspx?ItemName=Fireball#reference',
            'level.Wizard': '4, 6', 'pfs_marked': 'on', 'markers': ['M']}
    assert player.get(f'{path}/{key}').status_code == 403
    assert env.post(player, path, form).status_code == 403
    page = admin.get(f'{path}/{key}')
    assert page.status_code == 200 and 'name="level.Wizard" value="3"' in page.text
    invalid = env.post(admin, path, {**form, 'level.Wizard': '10'})
    assert invalid.status_code == 422 and 'name="level.Wizard" value="10"' in invalid.text
    saved = env.post(admin, path, form)
    assert saved.status_code == 303
    assert env.post(admin, path, form).status_code == 409

    filters = {'kind': 'spells', 'q': 'House Fireball', 'class': 'Wizard', 'school': 'Conjuration'}
    listing = admin.get('/administration/catalog', params={**filters, 'level': 6})
    assert '1 spell' in listing.text and 'Wizard 4/6' in listing.text
    assert 'Special material' in listing.text and 'Mythic version' not in listing.text.split('<tbody>')[1]
    assert form['url'] in listing.text and f'href="{path}/{key}"' in listing.text
    assert 'No matching spells.' in admin.get('/administration/catalog', params={**filters, 'level': 3}).text
    with Session(engine()) as db:
        overrides = db.get(RuleCatalog, 1).data['spell_overrides']
        assert set(overrides) == {key}
        assert overrides[key]['name'] == 'House Fireball'
    assert spell_defaults()[key]['name'] == 'Fireball'


def test_sheet_spell_catalog_requires_character_access_and_uses_overrides(env):
    from .test_workspace import seed_character

    character = seed_character(env.player)
    path = f'/characters/{character.id}/spells'
    assert env.login(env.player2).get(path).status_code == 404
    key = next(key for key, spell in spell_defaults().items() if spell['name'] == 'Fireball')
    with Session(engine()) as db:
        record = db.get(RuleCatalog, 1) or RuleCatalog(id=1, data={})
        record.data = {**record.data, 'spell_overrides': {key: {
            **spell_defaults()[key], 'name': 'House Fireball', 'levels': {'Wizard': [4]},
        }}}
        db.add(record)
        db.commit()
    response = env.login(env.player).get(path)
    assert response.status_code == 200
    entries = response.json()['spells']
    assert len(entries) == len(spells())
    assert next(item for item in entries if item['name'] == 'House Fireball')['levels'] == {'Wizard': [4]}


def test_saved_spell_descriptions_link_directly_from_character_sheet(env):
    from .test_workspace import seed_character

    character = seed_character(env.player)
    with Session(engine()) as db:
        db.get(type(character), character.id).play_data = {
            'spell.0.list': 'Bleed (DC 12)',
            'spell.2.list': 'Enthrall (domain, DC 14)\nA custom formula',
            'spell.3.list': 'Magic Vestment (domain)',
        }
        db.commit()
    response = env.login(env.player).get(f'/characters/{character.id}')
    assert response.status_code == 200
    for name, target in [('Bleed (DC 12)', 'Bleed'), ('Enthrall (domain, DC 14)', 'Enthrall'),
                         ('Magic Vestment (domain)', 'Magic%20Vestment')]:
        assert (f'href="https://www.aonprd.com/SpellDisplay.aspx?ItemName={target}" '
                f'target="_blank" rel="noopener noreferrer">{name}</a>') in response.text
    assert '<li>A custom formula</li>' in response.text

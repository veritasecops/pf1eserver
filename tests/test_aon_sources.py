from copy import deepcopy
import json
from pathlib import Path

from sqlalchemy.orm import Session

from pathkeeper.aon_sources import migrate_sources, reference_key, source_for, source_note
from pathkeeper.database import engine
from pathkeeper.models import RuleCatalog
from pathkeeper.rule_catalog import default_catalog
from scripts.import_aon_sources import parse_source

FIREBALL = 'https://www.aonprd.com/SpellDisplay.aspx?ItemName=Fireball'


def test_import_selects_primary_record_and_text_fragment_sources():
    html = '<h1>Power Attack</h1><b>Source</b> <a><i>Core pg. 131</i></a><br /><h2>Mythic</h2><b>Source</b> Mythic pg. 71<br />'
    assert parse_source(html) == 'Core pg. 131'
    shared = '<h2>First</h2><b>Source</b> Book A pg. 1<br /><h2>Second &amp; Last</h2><b>Source</b> Book B pg. 2<br /><h2>Missing</h2>No citation<h2>Other</h2><b>Source</b> Wrong<br />'
    assert parse_source(shared, 'https://www.aonprd.com/Test.aspx#:~:text=Second%20%26%20Last') == 'Book B pg. 2'
    assert not parse_source(shared, 'https://www.aonprd.com/Test.aspx#:~:text=Missing')
    assert not parse_source(shared, 'https://www.aonprd.com/Test.aspx#:~:text=Unknown')


def test_reference_normalization_and_escaped_citation():
    assert source_for(FIREBALL) == 'PRPG Core Rulebook pg. 283'
    assert reference_key(FIREBALL.replace('Fireball', 'Fireball%20Greater')) == reference_key(FIREBALL.replace('Fireball', 'Fireball+Greater'))
    assert reference_key(FIREBALL + '#:~:text=First') != reference_key(FIREBALL + '#:~:text=Second')
    assert not source_for('https://example.com/SpellDisplay.aspx?ItemName=Fireball')
    note = str(source_note(FIREBALL, {reference_key(FIREBALL): '<script>bad</script>'}))
    assert '&lt;script&gt;bad&lt;/script&gt;' in note and '<script>' not in note
    assert not source_note(None)


def test_sources_are_stored_on_each_supported_snapshot():
    directory = Path(__file__).parents[1] / 'pathkeeper/data'
    for name in ('weapons', 'armor', 'feats', 'spells', 'magic_items', 'equipment_index', 'deities', 'class_progressions'):
        data = json.loads((directory / (name + '.json')).read_text())
        entries = data.values() if isinstance(data, dict) else data
        for item in entries:
            if published := source_for(item.get('url', '')):
                assert item['source'] == published, (name, item)


def test_migration_preserves_custom_sources_urls_and_statistics(env):
    catalog = default_catalog()
    for item in catalog['feats'].values():
        item.pop('source', None)
    catalog['feats']['Toughness']['source'] = 'House Rules pg. 2'
    catalog['skills']['perception'].update(url='https://example.com/custom', source='House Skill pg. 3')
    catalog['armor']['chain-shirt']['source'] = json.loads((Path(__file__).parents[1] / 'pathkeeper/data/aon_source_baseline.json').read_text())[reference_key(catalog['armor']['chain-shirt']['url'])]
    before = deepcopy(catalog)
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1, data=catalog))
        db.commit()
        migrate_sources(db)
        db.commit()
        updated = db.get(RuleCatalog, 1).data
        assert updated['feats']['Power Attack']['source'] == source_for(updated['feats']['Power Attack']['url'])
        assert updated['feats']['Toughness'] == before['feats']['Toughness']
        assert updated['skills']['perception'] == before['skills']['perception']
        armor = updated['armor']['chain-shirt']
        assert armor['source'] == source_for(armor['url'])
        assert {k: v for k, v in armor.items() if k != 'source'} == {k: v for k, v in before['armor']['chain-shirt'].items() if k != 'source'}
        version = db.get(RuleCatalog, 1).version
        migrate_sources(db)
        db.commit()
        assert db.get(RuleCatalog, 1).version == version


def test_all_logged_in_roles_can_read_sources_and_catalog_edits_are_used(env):
    assert env.client().get('/api/reference-sources', params={'url': FIREBALL}).status_code == 303
    for user in (env.admin, env.gm, env.player):
        client = env.login(user)
        response = client.get('/api/reference-sources', params={'url': FIREBALL})
        assert response.status_code == 200
        assert response.json()[FIREBALL] == 'PRPG Core Rulebook pg. 283'
    admin = env.login(env.admin)
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1, data=default_catalog()))
        db.commit()
    page = admin.get('/administration/catalog', params={'kind': 'skills'})
    assert 'data-reference-source>Source: PRPG Core Rulebook pg.' in page.text
    editor = admin.get('/administration/catalog/skills/perception')
    assert 'name="source"' in editor.text
    with Session(engine()) as db:
        record = db.get(RuleCatalog, 1)
        url = record.data['skills']['perception']['url']
        version = record.version
    form = {'key': 'perception', 'name': 'Perception', 'version': version, 'enabled': 'on', 'ability': 'wis',
            'source': 'House Rules pg. 77', 'url': url}
    assert env.post(admin, '/administration/catalog/skills', form).status_code == 303
    assert admin.get('/api/reference-sources', params={'url': url}).json()[url] == form['source']
    assert 'Source: House Rules pg. 77' in admin.get('/administration/catalog', params={'kind': 'skills'}).text
    assert admin.get('/api/reference-sources', params=[('url', FIREBALL)] * 101).status_code == 422


def test_spell_source_is_editable_and_older_forms_preserve_it(env):
    from pathkeeper.catalog_admin import spell_defaults

    key, spell = next((key, spell) for key, spell in spell_defaults().items() if spell['name'] == 'Fireball')
    admin = env.login(env.admin)
    page = admin.get(f'/administration/catalog/spells/{key}')
    assert 'name="source" value="PRPG Core Rulebook pg. 283"' in page.text
    form = {'key': key, 'version': 1, 'name': spell['name'], 'url': spell['url'],
            'schools': spell['schools'], 'source': 'House Fire Magic pg. 10', 'level.Wizard': '3'}
    assert env.post(admin, '/administration/catalog/spells', form).status_code == 303
    assert admin.get('/api/reference-sources', params={'url': FIREBALL}).json()[FIREBALL] == form['source']
    form.pop('source')
    form['version'] = 2
    assert env.post(admin, '/administration/catalog/spells', form).status_code == 303
    assert admin.get('/api/reference-sources', params={'url': FIREBALL}).json()[FIREBALL] == 'House Fire Magic pg. 10'

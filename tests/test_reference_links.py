from copy import deepcopy
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character, CharacterDraft, RuleCatalog
from pathkeeper.pf1_data import CLASSES, OUTLINE
from pathkeeper.reference_links import migrate_reference_links, reference_links, replace_references, replace_url
from pathkeeper.rule_catalog import default_catalog
from .test_workspace import seed_character

OLD = 'https://www.d20pfsrd.com/equipment/weapons/weapon-descriptions/longsword'
NEW = 'https://www.aonprd.com/EquipmentWeaponsDisplay.aspx?ItemName=Longsword'


def test_all_default_reference_links_use_aon():
    for group in ('weapons', 'armor'):
        entries = json.loads((Path(__file__).parents[1] / 'pathkeeper' / 'data' / f'{group}.json').read_text())
        assert len(entries) == (279 if group == 'weapons' else 72)
        assert all('.aonprd.com/' in item['url'] for item in entries.values())
    assert OUTLINE == 'https://www.aonprd.com/Rules.aspx?ID=83'
    assert {'omdura', 'vampire-hunter'}.isdisjoint(CLASSES)
    assert len(CLASSES) == 49
    assert all(value['url'].startswith('https://www.aonprd.com/ClassDisplay.aspx?') for value in CLASSES.values())


def test_reference_normalization_custom_urls_and_unknown_pages():
    assert replace_url('https://www.d20pfsrd.com/equipmenT/#TOC-Coins') == 'https://www.aonprd.com/Rules.aspx?ID=107'
    assert replace_url(OLD + '/#description') == NEW
    assert replace_url(OLD.replace('https://www.', 'http://')) == NEW
    assert replace_url('https://example.com/reference') == 'https://example.com/reference'
    assert replace_url('https://d20pfsrd.com.example.com/weapon') == 'https://d20pfsrd.com.example.com/weapon'
    assert replace_references({'notes': f'Read {OLD}', 'damage': '1d8'}) == {'notes': f'Read {NEW}', 'damage': '1d8'}
    with pytest.raises(ValueError, match='No verified AoN equivalent'):
        replace_url('https://www.d20pfsrd.com/a-custom-rule')


def test_shared_source_pages_map_to_the_correct_variant():
    url = 'https://www.d20pfsrd.com/equipment/armor/shield-light-wooden-or-steel'
    data = {'armor': {'shield-light-steel': {'name': 'Renamed shield', 'url': url},
                      'light-shield': {'name': 'Shield, light wooden', 'url': url}},
            'equipment': [{'name': 'Shield, light wooden', 'kind': 'shield', 'url': url}]}
    updated = replace_references(data)
    assert updated['armor']['shield-light-steel']['url'].endswith('ItemName=Light%20steel')
    assert updated['armor']['light-shield']['url'].endswith('ItemName=Light%20wooden')
    assert updated['equipment'][0]['url'].endswith('ItemName=Light%20wooden')
    # An administrator may intentionally link a different item; follow that URL.
    changed = replace_references({'weapons': {'dagger': {'name': 'Dagger', 'url': OLD}}})
    assert changed['weapons']['dagger']['url'] == NEW


def test_migration_preserves_statistics_custom_edits_and_edit_draft_versions(env):
    character = seed_character(env.player)
    catalog = default_catalog()
    catalog['weapons']['longsword'].update(name='House sword', damage='3d8', url=OLD)
    catalog['armor']['leather']['url'] = 'https://example.com/house-armor'
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1, data=deepcopy(catalog)))
        record = db.get(Character, character.id)
        record.sheet_data = {'catalog': deepcopy(catalog), 'computed': {'equipment': [deepcopy(catalog['weapons']['longsword'])]}}
        record.play_data = {'weapon_inventory': [{'item': deepcopy(catalog['weapons']['longsword'])}], 'money.gp': '42'}
        db.flush()
        before = record.version
        db.add(CharacterDraft(id='a'*32, actor_id=env.player.id, mode='edit', editing_id=record.id,
                              existing_version=before, data={'catalog': deepcopy(catalog)}))
        db.add(CharacterDraft(id='b'*32, actor_id=env.player.id, mode='edit', editing_id=record.id,
                              existing_version=before-1, data={}))
        db.commit()
        migrate_reference_links(db)
        db.commit()
        record = db.get(Character, character.id)
        assert record.version == before+1
        assert record.sheet_data['catalog']['weapons']['longsword']['url'] == NEW
        assert record.play_data['weapon_inventory'][0]['item']['url'] == NEW
        assert record.play_data['money.gp'] == '42'
        assert record.sheet_data['catalog']['weapons']['longsword']['damage'] == '3d8'
        assert db.get(RuleCatalog, 1).data['weapons']['longsword']['name'] == 'House sword'
        assert db.get(RuleCatalog, 1).data['armor']['leather']['url'] == 'https://example.com/house-armor'
        assert db.get(CharacterDraft, 'a'*32).existing_version == record.version
        assert db.get(CharacterDraft, 'a'*32).data['catalog']['weapons']['longsword']['url'] == NEW
        assert db.get(CharacterDraft, 'b'*32).existing_version == before-1
        versions = record.version, db.get(RuleCatalog, 1).version, db.get(CharacterDraft, 'a'*32).version
        migrate_reference_links(db)
        db.commit()
        assert versions == (record.version, db.get(RuleCatalog, 1).version, db.get(CharacterDraft, 'a'*32).version)


def test_unknown_stored_link_rolls_back_without_partial_migration(env):
    character = seed_character(env.player)
    catalog = default_catalog()
    catalog['weapons']['longsword']['url'] = OLD
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1, data=catalog))
        db.get(Character, character.id).sheet_data = {'url': 'https://www.d20pfsrd.com/unmapped-house-rule'}
        db.commit()
        with pytest.raises(ValueError, match='No verified AoN equivalent'):
            migrate_reference_links(db)
        db.rollback()
        assert db.get(RuleCatalog, 1).data['weapons']['longsword']['url'] == OLD


@pytest.mark.parametrize('class_id', ['omdura', 'vampire-hunter'])
def test_unreferenced_classes_are_absent_and_cannot_roll_wealth(env, class_id):
    from .test_character_wizard import start, roll
    client, draft_id, _, _ = start(env)
    page = client.get(f'/characters/drafts/{draft_id}')
    import re
    boot = json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>', page.text, re.S).group(1))
    assert class_id not in boot['classes']
    assert all(item['url'] for item in boot['classes'].values())
    assert roll(env, client, draft_id, purpose='wealth', class_id=class_id).status_code == 422


def test_removed_class_skill_memberships_are_cleaned_without_losing_other_edits(env):
    from pathkeeper.reference_links import remove_unreferenced_classes
    catalog = default_catalog()
    catalog['skills']['climb'].update(classes=['omdura', 'fighter', 'vampire-hunter'], bonus=7)
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1, data=catalog))
        db.commit()
        record = db.get(RuleCatalog, 1)
        before = record.version
        remove_unreferenced_classes(db)
        db.commit()
        assert record.data['skills']['climb']['classes'] == ['fighter']
        assert record.data['skills']['climb']['bonus'] == 7
        assert record.version == before + 1
        remove_unreferenced_classes(db)
        db.commit()
        assert record.version == before + 1

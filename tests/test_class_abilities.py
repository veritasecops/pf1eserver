from urllib.parse import quote

from sqlalchemy.orm import Session

from pathkeeper.class_abilities import class_abilities
from pathkeeper.class_catalog import class_profile
from pathkeeper.database import engine
from pathkeeper.models import RuleCatalog
from pathkeeper.pf1_data import CLASSES
from pathkeeper.rule_catalog import default_catalog


def test_progression_catalog_groups_scaling_features_and_covers_every_class():
    entries, classes = class_abilities(default_catalog())
    assert set(classes) == set(CLASSES)
    bravery = next(item for item in entries if item['class_id'] == 'fighter' and item['name'].casefold() == 'bravery')
    assert [gain['level'] for gain in bravery['gains']] == [2, 6, 10, 14, 18]
    assert bravery['url'].endswith('#:~:text=' + quote('Bravery (Ex):', safe=''))
    talent = next(item for item in entries if item['id'] == 'investigator:investigator talent')
    assert talent['url'] == 'https://www.aonprd.com/InvestigatorTalents.aspx'
    assert all(item['url'].startswith(item['class_url'] + '#:~:text=') for item in entries if item is not talent)
    urls = {item['id']: item['url'] for item in entries}
    assert urls['bard:inspire courage'].endswith('#:~:text=Inspire%20Courage%20%28Su%29%3A')
    assert urls['ranger:3rd favored enemy'].endswith('#:~:text=Favored%20Enemy%20%28Ex%29%3A')
    assert all(1 <= gain['level'] <= 20 for item in entries for gain in item['gains'])
    assert len({(item['class_id'], item['name'].casefold()) for item in entries}) == len(entries)


def test_class_ability_catalog_filters_and_admin_access(env):
    path = '/administration/catalog'
    params = {'kind': 'class-abilities', 'class': 'fighter', 'q': 'Bravery', 'level': '6'}
    assert env.login(env.player).get(path, params=params).status_code == 403
    client = env.login(env.admin)
    page = client.get(path, params=params)
    assert page.status_code == 200
    assert '1 ability' in page.text and '6: bravery +2' in page.text
    assert 'ClassDisplay.aspx?ItemName=Fighter#:~:text=Bravery%20%28Ex%29%3A' in page.text
    edit_path = '/administration/catalog/classes/fighter?feature_level=6#class-features-6'
    assert f'href="{edit_path}" aria-label="Edit bravery for Fighter">Edit</a>' in page.text
    editor = client.get(edit_path)
    assert editor.status_code == 200
    assert '<details id="class-features-6" open>' in editor.text
    assert 'bravery +2' in editor.text
    unfiltered = client.get(path, params={**params, 'level': ''})
    assert 'href="/administration/catalog/classes/fighter?feature_level=2#class-features-2"' in unfiltered.text
    assert 'value="witch"' in page.text and 'value="warrior"' in page.text
    assert 'No matching class abilities.' in client.get(path, params={**params, 'level': '3'}).text
    listing = client.get(path, params={'kind': 'class-abilities', 'page': '2'})
    assert listing.status_code == 200 and 'Page 2 of' in listing.text
    assert 'kind=class-abilities&amp;q=&amp;class=&amp;level=' in listing.text
    assert 'class="active" aria-current="page">Class Abilities</a>' in page.text
    assert 'Class Abilities' in client.get(path).text


def test_class_ability_catalog_uses_active_class_overrides(env):
    catalog = default_catalog()
    levels = [dict(row) for row in class_profile(catalog, 'fighter')['levels']]
    levels[0] = {**levels[0], 'features': 'House ability'}
    catalog['classes'] = {'fighter': {'levels': levels}}
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1, data=catalog))
        db.commit()
    response = env.login(env.admin).get('/administration/catalog', params={'kind': 'class-abilities', 'class': 'fighter', 'q': 'House'})
    assert response.status_code == 200 and '1 ability' in response.text
    assert 'House ability' in response.text
    assert 'House ability</th>' in response.text


def test_sheet_catalog_add_remove_restore_and_autosave_preserve_changes(env):
    from .test_workspace import seed_character
    from .test_deluxe_sheet import SheetForm

    character = seed_character(env.player)
    path = f'/characters/{character.id}'
    client = env.login(env.player)
    assert env.login(env.player2).get(path + '/class-abilities').status_code == 404
    options = client.get(path + '/class-abilities').json()['options']
    assert options and all(item['class_id'] == 'fighter' for item in options)
    bravery = next(item for item in options if item['id'] == 'fighter:bravery')
    assert bravery['owned']
    page = client.get(path)
    assert 'id="add-class-ability"' in page.text
    version = SheetForm(page.text).values['version']
    remove = {'version': version, 'ability': bravery['id']}
    assert env.post(client, path + '/class-abilities/remove', remove).status_code == 200
    assert env.post(client, path + '/class-abilities/remove', remove).status_code == 409
    page = client.get(path)
    assert 'data-remove-class-ability="fighter:bravery"' not in page.text
    form = SheetForm(page.text)
    form.values['notes'] = 'Keep removal after saving'
    assert env.post(client, path + '/play-sheet', form.values).status_code == 303
    page = client.get(path)
    assert 'data-remove-class-ability="fighter:bravery"' not in page.text
    version = SheetForm(page.text).values['version']
    assert env.post(client, path + '/class-abilities', {'version': version, 'ability': 'monk:flurry of blows'}).status_code == 422
    assert env.post(client, path + '/class-abilities', {'version': version, 'ability': bravery['id']}).status_code == 201
    page = client.get(path)
    assert page.text.count('data-remove-class-ability="fighter:bravery"') == 1
    version = SheetForm(page.text).values['version']
    assert env.post(client, path + '/class-abilities', {'version': version, 'ability': bravery['id']}).status_code == 409
    assert env.post(client, path + '/class-abilities', {'version': version, 'ability': 'fighter:weapon mastery'}).status_code == 201
    assert 'data-remove-class-ability="fighter:weapon mastery"' in client.get(path).text


def test_removed_choice_preserves_text_for_restoration(env):
    from pathkeeper.models import Character
    from .test_workspace import seed_character
    from .test_deluxe_sheet import SheetForm

    character = seed_character(env.player)
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.class_name = 'Bard'
        record.play_data = {'feature.0': 'Versatile performance: Oratory'}
        db.commit()
    path = f'/characters/{character.id}'
    client = env.login(env.player)
    form = SheetForm(client.get(path).text)
    assert env.post(client, path + '/class-abilities/remove', {'version': form.values['version'], 'ability': 'bard:versatile performance'}).status_code == 200
    page = client.get(path)
    assert 'data-class-ability-input="0"' not in page.text
    form = SheetForm(page.text)
    assert env.post(client, path + '/class-abilities', {'version': form.values['version'], 'ability': 'bard:versatile performance'}).status_code == 201
    page = client.get(path)
    assert 'data-ability-label="Versatile performance">Oratory</textarea>' in page.text


def test_removing_movement_preserves_manual_speed_modifier(env):
    from pathkeeper.models import Character
    from .test_workspace import seed_character
    from .test_deluxe_sheet import SheetForm

    character = seed_character(env.player)
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.class_name = 'Barbarian'
        db.commit()
    path = f'/characters/{character.id}'
    client = env.login(env.player)
    form = SheetForm(client.get(path).text)
    speed = int(form.values['speed.armor']) + 5
    form.values['speed.armor'] = str(speed)
    assert env.post(client, path + '/play-sheet', form.values).status_code == 303
    form = SheetForm(client.get(path).text)
    assert env.post(client, path + '/class-abilities/remove', {'version': form.values['version'], 'ability': 'barbarian:fast movement'}).status_code == 200
    form = SheetForm(client.get(path).text)
    assert int(form.values['speed.armor']) == speed - 10
    assert env.post(client, path + '/class-abilities', {'version': form.values['version'], 'ability': 'barbarian:fast movement'}).status_code == 201
    form = SheetForm(client.get(path).text)
    assert int(form.values['speed.armor']) == speed


def test_added_freeform_ability_gets_an_editable_choice(env):
    from pathkeeper.models import Character
    from .test_workspace import seed_character
    from .test_deluxe_sheet import SheetForm

    character = seed_character(env.player)
    with Session(engine()) as db:
        record = db.get(Character, character.id)
        record.class_name, record.level = 'Bard', 1
        db.commit()
    path = f'/characters/{character.id}'
    client = env.login(env.player)
    form = SheetForm(client.get(path).text)
    assert env.post(client, path + '/class-abilities', {'version': form.values['version'], 'ability': 'bard:versatile performance'}).status_code == 201
    page = client.get(path)
    assert 'data-class-ability-input="0"' in page.text
    form = SheetForm(page.text)
    form.values['feature.0'] = 'Versatile performance: Comedy'
    assert env.post(client, path + '/play-sheet', form.values).status_code == 303
    assert 'data-ability-label="Versatile performance">Comedy</textarea>' in client.get(path).text
    form = SheetForm(client.get(path).text)
    assert env.post(client, path + '/class-abilities/remove', {'version': form.values['version'], 'ability': 'bard:versatile performance'}).status_code == 200
    page = client.get(path)
    assert 'data-class-ability-input="0"' not in page.text
    assert 'data-feature-row="0" hidden' in page.text
    form = SheetForm(page.text)
    assert env.post(client, path + '/class-abilities', {'version': form.values['version'], 'ability': 'bard:versatile performance'}).status_code == 201
    assert 'data-ability-label="Versatile performance">Comedy</textarea>' in client.get(path).text

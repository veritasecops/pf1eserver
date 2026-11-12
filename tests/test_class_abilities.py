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

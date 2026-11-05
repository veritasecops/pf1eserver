from copy import deepcopy
from urllib.parse import quote

import pytest
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import RuleCatalog
from pathkeeper.reference_links import add_admin_reference_links, reference_links
from pathkeeper.rule_catalog import default_catalog
from .test_rule_catalog import feat_form


@pytest.mark.parametrize('kind,key', [('feats','Improved Initiative'), ('skills','knowledge-arcana'), ('deities','chaldira-zuzaristan')])
def test_individual_reference_links_on_list_and_editor(env, kind, key):
    client=env.login(env.admin)
    url=reference_links()[kind][key]
    listing=client.get('/administration/catalog',params={'kind':kind})
    assert listing.status_code==200
    assert f'href="{url}" target="_blank" rel="noopener noreferrer"' in listing.text
    editor=client.get(f'/administration/catalog/{kind}/{quote(key)}')
    assert editor.status_code==200
    assert f'value="{url}"' in editor.text and 'Open reference' in editor.text


def test_migration_adds_links_and_preserves_unmatched_and_custom_entries(env):
    catalog=default_catalog()
    for kind in ('feats','skills'):
        for item in catalog[kind].values():item.pop('url',None)
    catalog['deities']['chaldira-zuzaristan']['url']=reference_links()['legacy_deity_urls']['chaldira-zuzaristan']
    catalog['feats']['Toughness'].update(url='https://example.com/house-toughness',hint='House rule',effects={'hp':7})
    catalog['deities']['abadar']['url']='https://example.com/house-abadar'
    catalog['skills']['lore']={'name':'House Lore','url':'https://example.com/lore'}
    unchanged=deepcopy(catalog['deities']['atheism'])
    with Session(engine()) as db:
        db.add(RuleCatalog(id=1,data=catalog));db.commit()
        add_admin_reference_links(db);db.commit()
        record=db.get(RuleCatalog,1)
        assert record.data['feats']['Improved Initiative']['url']==reference_links()['feats']['Improved Initiative']
        assert record.data['skills']['knowledge-planes']['url']==reference_links()['skills']['knowledge-planes']
        assert record.data['deities']['chaldira-zuzaristan']['url']==reference_links()['deities']['chaldira-zuzaristan']
        assert record.data['feats']['Toughness']==catalog['feats']['Toughness']
        assert record.data['skills']['lore']==catalog['skills']['lore']
        assert record.data['deities']['abadar']==catalog['deities']['abadar']
        assert record.data['deities']['atheism']==unchanged
        assert len(record.data['deities'])==157
        version=record.version
        add_admin_reference_links(db);db.commit()
        assert record.version==version


@pytest.mark.parametrize('kind,key', [('feats','Improved Initiative'), ('skills','perception')])
def test_reference_edits_validate_and_survive_older_forms(env,kind,key):
    client=env.login(env.admin)
    if kind=='feats':form=feat_form(url='https://example.com/initiative')
    else:form=dict(key=key,name='Perception',version=1,enabled='on',ability='wis',url='https://example.com/perception')
    assert env.post(client,f'/administration/catalog/{kind}',form).status_code==303
    expected=form.pop('url');form['version']=2
    assert env.post(client,f'/administration/catalog/{kind}',form).status_code==303
    with Session(engine()) as db:assert db.get(RuleCatalog,1).data[kind][key]['url']==expected
    form.update(version=3,url='javascript:alert(1)')
    assert env.post(client,f'/administration/catalog/{kind}',form).status_code==422

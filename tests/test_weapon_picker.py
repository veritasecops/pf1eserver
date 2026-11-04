from copy import deepcopy
import json
import re

import pytest
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character, CharacterDraft, RuleCatalog, User
from pathkeeper.deluxe_sheet import baseline
from pathkeeper.rule_catalog import default_catalog
from .test_character_wizard import start, fighter, save, finish


def setup_shop(env):
    client,draft_id,version,data=start(env)
    data=fighter(data)
    data.update(equipment={'leather':1},weapon='',shield='')
    result=save(env,client,draft_id,version,data,8)
    return client,draft_id,result.json()['version']


def catalog_version(client,draft_id):
    page=client.get(f'/characters/drafts/{draft_id}')
    if page.status_code!=200: return 0
    return json.loads(re.search(r'id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))['catalog_version']


def buy(env,client,draft_id,version,quantities,prices=None,**changes):
    return env.post(client,f'/api/character-drafts/{draft_id}/weapons',{
        'version':version,'catalog_version':catalog_version(client,draft_id),
        'payload':json.dumps({'quantities':quantities,'prices':prices or {}}),**changes})


def test_purchase_adds_all_items_and_deducts_once_through_final_sheet(env):
    client,draft_id,version=setup_shop(env)
    result=buy(env,client,draft_id,version,{'longsword':2,'dagger':3})
    assert result.status_code==200,result.text
    body=result.json()
    assert body['data']['equipment']=={'leather':1,'longsword':2,'dagger':3}
    assert body['computed']['spent_cp']==4600 and body['computed']['remaining_cp']==12900
    duplicate=buy(env,client,draft_id,version,{'longsword':2,'dagger':3})
    assert duplicate.status_code==409
    with Session(engine()) as db:
        assert db.get(CharacterDraft,draft_id).data['equipment']['longsword']==2
    # Ordinary autosaves and reloads never deduct a purchase again.
    saved=save(env,client,draft_id,body['version'],body['data'],8)
    assert saved.json()['computed']['remaining_cp']==12900
    made=finish(env,client,draft_id,saved.json()['version'])
    assert made.status_code==200,made.text
    with Session(engine()) as db:
        character=db.get(Character,int(made.json()['location'].rsplit('/',1)[1]))
        values=baseline(character,db.get(User,character.owner_id))
        assert values['money.gp']=='129' and values['money.sp']=='0'
        assert 'Longsword × 2' in values.values() and 'Dagger × 3' in values.values()


def test_additional_purchases_add_quantities_and_removal_restores_balance(env):
    client,draft_id,version=setup_shop(env)
    first=buy(env,client,draft_id,version,{'dagger':1}).json()
    second=buy(env,client,draft_id,first['version'],{'dagger':2,'arrows':1}).json()
    assert second['data']['equipment']['dagger']==3
    assert second['computed']['remaining_cp']==15800
    second['data']['equipment']['dagger']=0
    removed=save(env,client,draft_id,second['version'],second['data'],8)
    assert removed.json()['computed']['remaining_cp']==16400


@pytest.mark.parametrize('quantities,prices',[
    ({'longbow':3},{}), ({'dagger':0},{}), ({'dagger':-1},{}), ({'dagger':True},{}),
    ({'dagger':1.5},{}), ({'dagger':101},{}), ({'backpack':1},{}), ({'not-a-weapon':1},{}),
    ({'longsword':1},{'longsword':1}), ({'shield-light':1},{}),
    ({'shield-light':1},{'shield-light':-1}), ({'shield-light':1},{'shield-light':True}),
    ({'shield-light':1},{'shield-light':1.5}), ({},{}),
])
def test_invalid_or_unaffordable_purchase_preserves_inventory(env,quantities,prices):
    client,draft_id,version=setup_shop(env)
    response=buy(env,client,draft_id,version,quantities,prices)
    assert response.status_code==422,response.text
    with Session(engine()) as db:
        draft=db.get(CharacterDraft,draft_id)
        assert draft.version==version and draft.data['equipment']=={'leather':1}


def test_special_unit_prices_are_counted_and_persisted(env):
    client,draft_id,version=setup_shop(env)
    first=buy(env,client,draft_id,version,{'shield-light':2},{'shield-light':900})
    assert first.status_code==200,first.text
    body=first.json()
    assert body['data']['equipment_prices']['shield-light']==900
    assert body['computed']['spent_cp']==2800
    assert body['computed']['remaining_cp']==14700
    second=buy(env,client,draft_id,body['version'],{'shield-light':1}).json()
    assert second['computed']['spent_cp']==3700
    assert buy(env,client,draft_id,second['version'],{'shield-light':1},{'shield-light':1}).status_code==422


def test_purchase_requires_owner_csrf_current_rules_and_current_inventory(env):
    client,draft_id,version=setup_shop(env)
    other=env.login(env.player2)
    assert buy(env,other,draft_id,version,{'dagger':1}).status_code==404
    assert client.post(f'/api/character-drafts/{draft_id}/weapons',data={'version':version,'catalog_version':0,'payload':'{}'}).status_code==403
    old_version=catalog_version(client,draft_id)
    with Session(engine()) as db:
        catalog=default_catalog()
        catalog['weapons']['longsword']['cost']=5000
        db.add(RuleCatalog(id=1,data=catalog))
        db.commit()
    assert buy(env,client,draft_id,version,{'longsword':1},catalog_version=old_version).status_code==409
    with Session(engine()) as db:
        record=db.get(RuleCatalog,1)
        updated=deepcopy(record.data)
        updated['weapons']['longsword']['enabled']=False
        record.data=updated
        db.commit()
    assert buy(env,client,draft_id,version,{'longsword':1}).status_code==422


def test_free_weapons_work_at_zero_treasure_and_rolled_wealth_requires_a_roll(env):
    client,draft_id,version=setup_shop(env)
    with Session(engine()) as db:
        draft=db.get(CharacterDraft,draft_id)
        draft.data={**draft.data,'equipment':{},'wealth_method':'manual','manual_gold':0}
        db.commit()
        version=draft.version
    free=buy(env,client,draft_id,version,{'quarterstaff':1})
    assert free.status_code==200 and free.json()['computed']['remaining_cp']==0
    data=free.json()['data']
    data['wealth_method']='rolled'
    saved=save(env,client,draft_id,free.json()['version'],data,8)
    assert buy(env,client,draft_id,saved.json()['version'],{'dagger':1}).status_code==422

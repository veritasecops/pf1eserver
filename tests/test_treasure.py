import pytest
import secrets
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character
from pathkeeper.treasure import COINS, COIN_TYPES, treasure
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character
from .test_character_wizard import start, fighter, save, finish


def test_treasure_box_uses_the_published_four_coin_types_and_existing_balance(env):
    client,draft_id,version,data=start(env)
    saved=save(env,client,draft_id,version,fighter(data))
    created=finish(env,client,draft_id,saved.json()['version'])
    page=client.get(created.json()['location'])
    form=SheetForm(page.text)
    assert form.values['money.gp']=='141'
    assert 'id="character-treasure"' in page.text
    assert 'https://www.d20pfsrd.com/equipmenT/#TOC-Coins' in page.text
    assert '141 gp</output>' in page.text
    assert COINS=={'cp':1,'sp':10,'gp':100,'pp':1000}
    assert [coin for coin,_,_ in COIN_TYPES]==['cp','sp','gp','pp']
    for coin in COINS:
        assert form.names.count('money.'+coin)==1
        assert 'money.'+coin not in form.readonly
        assert f'data-remove-coins="{coin}"' in page.text
    assert 'id="add-treasure"' in page.text and 'id="undo-treasure"' in page.text


def test_coin_holdings_create_read_update_and_delete_through_autosave(env):
    character=seed_character(env.player)
    client=env.login(env.player)
    path=f'/characters/{character.id}'
    for holdings in ({'cp':'5','sp':'4','gp':'100','pp':'2'}, {'cp':'0','sp':'8','gp':'75','pp':'1'}, {'cp':'0','sp':'0','gp':'0','pp':'0'}):
        form=SheetForm(client.get(path).text)
        form.values.update({'money.'+coin:amount for coin,amount in holdings.items()})
        response=client.post(path+'/play-sheet',data=form.values,headers={'Accept':'application/json','X-Sheet-Save-Id':secrets.token_hex(16)})
        assert response.status_code==200,response.text
        saved=SheetForm(client.get(path).text)
        assert {coin:saved.values['money.'+coin] for coin in COINS}==holdings
    with Session(engine()) as db:
        assert db.get(Character,character.id).play_data['money.gp']=='0'


@pytest.mark.parametrize('coin,value',[('gp','-1'),('cp','0.5'),('gp','0.001'),('pp','1000000001'),('gp','NaN')])
def test_invalid_coin_updates_do_not_change_saved_treasure(env,coin,value):
    character=seed_character(env.player)
    client=env.login(env.player)
    path=f'/characters/{character.id}'
    form=SheetForm(client.get(path).text)
    form.values.update({'money.gp':'50'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    invalid=SheetForm(client.get(path).text)
    invalid.values['money.'+coin]=value
    response=env.post(client,path+'/play-sheet',invalid.values)
    assert response.status_code==422
    assert SheetForm(client.get(path).text).values['money.gp']=='50'


def test_coin_edits_keep_access_csrf_and_version_protection(env):
    character=seed_character(env.player)
    client=env.login(env.player)
    path=f'/characters/{character.id}'
    form=SheetForm(client.get(path).text)
    form.values['money.gp']='25'
    other=env.login(env.player2)
    assert env.post(other,path+'/play-sheet',form.values).status_code==404
    assert client.post(path+'/play-sheet',data={k:v for k,v in form.values.items() if k!='csrf'}).status_code==403
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    assert env.post(client,path+'/play-sheet',form.values).status_code==409
    assert SheetForm(client.get(path).text).values['money.gp']=='25'

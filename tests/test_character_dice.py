import pytest
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character
from .test_workspace import seed_character


def test_sheet_dice_rolls_use_supported_dice_and_do_not_change_character(env):
    character=seed_character(env.player);client=env.login(env.player);path=f'/characters/{character.id}'
    page=client.get(path)
    assert 'id="open-character-dice"' in page.text and 'id="character-dice-dialog"' in page.text
    assert 'id="pw-dice-canvas"' in page.text
    with Session(engine()) as db: version=db.get(Character,character.id).version
    for sides in (4,6,8,10,12,20,100):
        response=env.post(client,path+'/roll',{'sides':sides,'count':3,'modifier':-2})
        assert response.status_code==200,response.text
        record=response.json();result=record['result']
        assert record['purpose']=='free' and len(result['dice'])==3
        assert all(1<=value<=sides for value in result['dice'])
        assert result['total']==sum(result['dice'])-2
        if sides==100: assert all((pair['tens']+pair['ones'] or 100)==value for pair,value in zip(result['percentile'],result['dice']))
    with Session(engine()) as db:
        saved=db.get(Character,character.id)
        assert saved.version==version and not saved.play_data


def test_percentile_hundred_is_double_zero(env,monkeypatch):
    from pathkeeper import character_dice
    monkeypatch.setattr(character_dice.secrets,'randbelow',lambda sides:sides-1)
    character=seed_character(env.player);client=env.login(env.player)
    response=env.post(client,f'/characters/{character.id}/roll',{'sides':100,'count':1,'modifier':0})
    assert response.json()['result']['dice']==[100]
    assert response.json()['result']['percentile']==[{'tens':0,'ones':0}]


@pytest.mark.parametrize('changes',[{'sides':7},{'count':0},{'count':21},{'modifier':1001},{'count':'1.5'}])
def test_sheet_dice_reject_invalid_requests(env,changes):
    character=seed_character(env.player);client=env.login(env.player)
    assert env.post(client,f'/characters/{character.id}/roll',{'sides':20,'count':1,'modifier':0,**changes}).status_code==422


def test_sheet_dice_require_character_access_and_csrf(env):
    character=seed_character(env.player);client=env.login(env.player);other=env.login(env.player2)
    path=f'/characters/{character.id}/roll';data={'sides':20,'count':1,'modifier':0}
    assert env.post(other,path,data).status_code==404
    assert client.post(path,data=data).status_code==403

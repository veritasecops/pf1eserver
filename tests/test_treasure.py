import pytest
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import CoinTransaction
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
    character_id = int(created.json()['location'].rsplit('/', 1)[1])
    with Session(engine()) as db:
        transaction = db.scalar(select(CoinTransaction).where(CoinTransaction.character_id == character_id))
        assert transaction.source == 'starting_wealth' and transaction.net_cp == 14100
    assert 'id="character-treasure"' in page.text
    assert 'https://www.aonprd.com/Rules.aspx?ID=107' in page.text
    assert '141 gp</output>' in page.text
    assert COINS=={'cp':1,'sp':10,'gp':100,'pp':1000}
    assert [coin for coin,_,_ in COIN_TYPES]==['cp','sp','gp','pp']
    for coin in COINS:
        assert form.names.count('money.'+coin)==1
        assert 'money.'+coin in form.readonly
        assert f'data-remove-coins="{coin}"' in page.text
    assert 'id="add-treasure"' in page.text


def coin_payload(client, character_id, coin, amount=1, action='add'):
    path = f'/characters/{character_id}'
    version = SheetForm(client.get(path).text).values['version']
    return {'version': version, 'request_id': secrets.token_hex(16),
            'coin': coin, 'amount': amount, 'action': action}


def test_chest_coin_operations_are_logged_and_sheet_autosave_cannot_change_them(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    path = f'/characters/{character.id}'
    payload = coin_payload(client, character.id, 'gp', 25)
    assert env.post(client, path + '/treasure', payload).status_code == 200
    assert env.post(client, path + '/treasure', payload).status_code == 200
    form = SheetForm(client.get(path).text)
    form.values['money.gp'] = '1000'
    assert env.post(client, path + '/play-sheet', form.values).status_code == 303
    assert SheetForm(client.get(path).text).values['money.gp'] == '25'
    assert env.post(client, path + '/treasure', coin_payload(client, character.id, 'gp', action='remove')).status_code == 200
    assert SheetForm(client.get(path).text).values['money.gp'] == '0'
    with Session(engine()) as db:
        rows = db.scalars(select(CoinTransaction).where(CoinTransaction.character_id == character.id)
                          .order_by(CoinTransaction.id)).all()
        assert [(row.source, row.net_cp) for row in rows] == [('chest_add', 2500), ('chest_remove', -2500)]
        assert all(row.actor_id == env.player.id for row in rows)
        assert rows[0].after['gp'] == rows[1].before['gp'] == '25'
        assert rows[1].delta['gp'] == '-25'


@pytest.mark.parametrize('amount', ['-1', '0.5', '1000000001', 'NaN'])
def test_invalid_coin_operations_preserve_treasure(env, amount):
    character = seed_character(env.player)
    client = env.login(env.player)
    path = f'/characters/{character.id}/treasure'
    assert env.post(client, path, coin_payload(client, character.id, 'gp', amount)).status_code == 422
    assert SheetForm(client.get(f'/characters/{character.id}').text).values['money.gp'] == '0'


def test_coin_operations_keep_access_csrf_and_version_protection(env):
    character = seed_character(env.player)
    client = env.login(env.player)
    path = f'/characters/{character.id}/treasure'
    payload = coin_payload(client, character.id, 'gp', 25)
    assert env.post(env.login(env.player2), path, payload).status_code == 404
    assert env.post(client, path, payload, use_csrf=False).status_code == 403
    assert env.post(client, path, payload).status_code == 200
    assert env.post(client, path, {**payload, 'request_id': secrets.token_hex(16)}).status_code == 409

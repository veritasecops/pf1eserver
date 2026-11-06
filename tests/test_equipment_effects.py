import secrets
import json
import re
import secrets

from sqlalchemy.orm import Session

from pathkeeper.database import engine
from pathkeeper.models import Character
from .test_character_weapons import setup_sheet, purchase_data
from .test_deluxe_sheet import SheetForm
from .test_equipment_disposal import disposal


def buy(env, client, character, cart):
    form = saved_form(client, character)
    assert env.post(client, f'/characters/{character}/treasure', {
        'version': form.values['version'], 'request_id': secrets.token_hex(16),
        'action': 'add', 'coin': 'gp', 'amount': 200,
    }).status_code == 200
    response=env.post(client,f'/characters/{character}/equipment',purchase_data(client,character,cart))
    assert response.status_code==200,response.text


def saved_form(client,character):return SheetForm(client.get(f'/characters/{character}').text)


def test_equip_swap_unequip_and_remove_keep_manual_offsets(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    buy(env,client,character,{'leather':1,'chain-shirt':1,'buckler':1})
    form=saved_form(client,character)
    form.values.update({'ability.dex.score':'18','ac.misc':'3','skill.climb.misc':'2','speed.armor':'35',
                        'armor.0.equipped':'1','armor.2.equipped':'1'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character)
    assert form.values['ac.armor']=='2' and form.values['ac.shield']=='1' and form.values['ac.dex']=='4'
    assert form.values['ac.total']=='20' and form.values['skill.climb.misc']=='1' and form.values['speed.armor']=='35'
    form.values['armor.1.equipped']='1'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character)
    assert not form.values.get('armor.0.equipped') and form.values['armor.1.equipped']=='1'
    assert not form.values.get('gear.0.equipped') and form.values['gear.1.equipped']=='1'
    assert form.values['ac.armor']=='4' and form.values['skill.climb.misc']=='0'
    # A sale removes equipped modifiers as well as the item and credits coins once.
    sold=env.post(client,path+'/equipment/dispose',disposal(client,character,kind='armor',row=1,action='sell',coins={'gp':7}))
    assert sold.status_code==200,sold.text
    assert sold.json()['values']['ac.total']=='18'
    form=saved_form(client,character)
    assert form.values['ac.armor']=='0' and form.values['skill.climb.misc']=='1'
    form.values.pop('armor.2.equipped')
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character)
    assert form.values['ac.shield']=='0' and form.values['skill.climb.misc']=='2' and form.values['ac.misc']=='3'


def test_fighter_armor_training_and_temporary_dex_follow_equipped_armor(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    buy(env,client,character,{'scale-mail':1})
    form=saved_form(client,character)
    form.values.update({'ability.dex.score':'18','armor.0.equipped':'1'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character)
    assert form.values['ac.armor']=='5' and form.values['ac.dex']=='4' and form.values['speed.armor']=='30'
    assert form.values['skill.climb.misc']=='-3'
    form.values['ability.dex.temp_score']='8'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character);assert form.values['ac.dex']=='-1'
    form.values.pop('armor.0.equipped')
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character)
    assert form.values['speed.armor']=='30' and form.values['ac.dex']=='-1' and form.values['skill.climb.misc']=='0'


def test_rapid_saves_use_displayed_equipment_contributions_without_double_offsets(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    buy(env,client,character,{'leather':1,'chain-shirt':1})
    page=client.get(path).text;original=SheetForm(page)
    shown=json.loads(re.search(r'id="sheet-equipment-effects">(.*?)</script>',page,re.S).group(1))
    original.values.update({'armor.0.equipped':'1','ac.armor':'3'}) # +3 manual offset before armor arrives
    first=client.post(path+'/play-sheet',data=original.values,headers={'Accept':'application/json','X-Sheet-Save-Id':secrets.token_hex(16),'X-Equipment-Effects':json.dumps(shown)})
    assert first.status_code==200,first.text
    assert first.json()['equipment_fields']['ac.armor']=='5'
    # Next request was typed before the first reply updated displayed modifiers.
    original.values['version']=first.json()['version']
    original.values.pop('armor.0.equipped');original.values['armor.1.equipped']='1'
    second=client.post(path+'/play-sheet',data=original.values,headers={'Accept':'application/json','X-Sheet-Save-Id':secrets.token_hex(16),'X-Equipment-Effects':json.dumps(shown)})
    assert second.status_code==200,second.text
    assert second.json()['equipment_fields']['ac.armor']=='7'
    assert saved_form(client,character).values['ac.armor']=='7'


def test_equipped_weapons_recalculate_current_ability_and_feat_modifiers(env):
    client,character=setup_sheet(env);path=f'/characters/{character}'
    buy(env,client,character,{'longsword':1,'shortbow':1})
    form=saved_form(client,character)
    form.values.update({'weapon.0.equipped':'1','weapon.1.equipped':'1','ability.str.score':'20','ability.dex.score':'18'})
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    form=saved_form(client,character)
    assert form.values['weapon.0.attack']=='10' and form.values['weapon.0.damage']=='1d8+5'
    assert form.values['weapon.1.attack']=='9' and form.values['weapon.1.damage']=='1d6'


def test_monk_armor_restrictions_and_dwarf_barbarian_speed_rules():
    from types import SimpleNamespace
    from pathkeeper.equipment_effects import contributions
    from pathkeeper.rule_catalog import default_catalog
    catalog=default_catalog()
    character=SimpleNamespace(class_name='Monk',ancestry='Human',sheet_data={'catalog':catalog,'input':{'race':'human','class_id':'monk'}},
        play_data={'weapon_inventory':[{'id':'scale-mail','row':None,'armor_row':0,'quantity':1,'item':catalog['armor']['scale-mail']}]})
    values={'ability.wis.mod':'4','ability.dex.mod':'3','armor.0.name':'Scale mail','armor.0.equipped':'1'}
    effects=contributions(character,values)
    assert effects['ac.misc']==effects['cmd.misc']=='0' and effects['speed.armor']=='20'
    values['armor.0.equipped']=''
    effects=contributions(character,values)
    assert effects['ac.misc']==effects['cmd.misc']=='4'
    character.sheet_data['input']['class_id']='barbarian'
    assert contributions(character,values)['speed.armor']=='40'
    values['armor.0.equipped']='1'
    assert contributions(character,values)['speed.armor']=='30'
    character.sheet_data['input']['race']='dwarf';character.ancestry='Dwarf'
    assert contributions(character,values)['speed.armor']=='30'

def test_fighter_weapon_training_uses_highest_matching_group(env):
    client, character = setup_sheet(env)
    buy(env, client, character, {'longsword': 1, 'dagger': 1})
    with Session(engine()) as db:
        record = db.get(Character, character)
        record.level = 9
        record.play_data = {**record.play_data, 'advancement_history': [
            {'level': 5, 'choices': [{'feature': 'Weapon training 1', 'choice': 'Heavy blades'}]},
            {'level': 9, 'choices': [{'feature': 'Weapon training 2', 'choice': 'Blades, Light'}]},
        ]}
        db.commit()
    sheet = saved_form(client, character)
    sheet.values.update({'weapon.0.equipped': '1', 'weapon.1.equipped': '1'})
    assert env.post(client, f'/characters/{character}/play-sheet', sheet.values).status_code == 303
    sheet = saved_form(client, character)
    attack_damage = {
        sheet.values[f'weapon.{row}.name']: (sheet.values[f'weapon.{row}.attack'], sheet.values[f'weapon.{row}.damage'])
        for row in (0, 1)
    }
    assert attack_damage['Longsword'] == ('10', '1d8+5')
    assert attack_damage['Dagger'] == ('9', '1d4+4')

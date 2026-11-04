from pathkeeper.models import Character
from pathkeeper.sheet_calculations import calculated_fields
from pathkeeper.sheet_formulas import sheet_formulas
from .test_character_weapons import setup_sheet, purchase_data
from .test_deluxe_sheet import SheetForm
from .test_workspace import seed_character


def test_formula_coverage_includes_first_level_and_custom_skills():
    from pathkeeper.rule_catalog import default_catalog
    catalog=default_catalog()
    catalog['skills']['house-lore']={'name':'House lore','ability':'int','classes':[]}
    character=Character(owner_id=1,name='Tester',class_name='Fighter',level=1,
                        sheet_data={'catalog':catalog,'computed':{'bab':1}},play_data={})
    values={'size':'Small','hp.total':'12','bab':'1','skill_points.base':'2',
            'save.fortitude.base':'2','save.reflex.base':'0','save.will.base':'0'}
    formulas=sheet_formulas(character,values)
    assert set(formulas)==calculated_fields(character,values)
    assert 'rounded down' in formulas['ability.str.mod']
    assert 'only if it is negative' in formulas['ac.flat']
    assert 'minimum 1' in formulas['hp.total']
    assert 'at least one rank' in formulas['skill.house-lore.total']
    assert 'nonblank lines' in formulas['spell.1.known']
    character.level=2
    assert 'hp.total' not in sheet_formulas(character,values)


def test_render_and_autosave_expose_formulas_for_each_locked_field(env):
    character=seed_character(env.player)
    client=env.login(env.player)
    path=f'/characters/{character.id}'
    page=client.get(path)
    assert 'data-sheet-formula=' in page.text and '/static/sheet-formulas.js' in page.text
    form=SheetForm(page.text)
    form.values['ability.dex.score']='18'
    response=client.post(path+'/play-sheet/calculate',data=form.values)
    assert response.status_code==200,response.text
    body=response.json()
    assert set(body['formulas'])==set(body['readonly'])
    assert 'Dexterity modifier' in body['formulas']['initiative.total']
    saved=env.post(client,path+'/play-sheet',form.values)
    assert saved.status_code==303


def test_purchase_formulas_describe_managed_equipment_and_survive_autosave(env):
    client,character=setup_sheet(env)
    path=f'/characters/{character}'
    response=env.post(client,path+'/equipment',purchase_data(client,character,{'dagger':1,'leather':1}))
    assert response.status_code==200,response.text
    body=response.json()
    assert 'base attack bonus' in body['formulas']['weapon.0.attack']
    assert '½ for a Small character' in body['formulas']['armor.0.weight']
    form=SheetForm(client.get(path).text)
    form.values['size']='Small'
    response=client.post(path+'/play-sheet',data=form.values,headers={'Accept':'application/json','X-Sheet-Save-Id':'f'*32})
    assert response.status_code==200,response.text
    assert 'base attack bonus' in response.json()['formulas']['weapon.0.attack']


def test_base_speed_uses_race_ignores_manual_override_and_is_locked(env):
    from sqlalchemy.orm import Session
    from pathkeeper.database import engine
    character=seed_character(env.player)
    with Session(engine()) as db:
        saved=db.get(Character,character.id)
        saved.ancestry='Dwarf'
        saved.play_data={'speed.base':'99','speed.fly':'60'}
        db.commit()
    client=env.login(env.player)
    path=f'/characters/{character.id}'
    page=client.get(path)
    form=SheetForm(page.text)
    assert 'speed.base' in form.readonly
    assert form.values['speed.base']=='20'
    assert form.values['speed.fly']=='60' and 'speed.fly' not in form.readonly
    assert 'Dwarf has a racial land speed of 20 ft.' in page.text
    form.values['speed.base']='999'
    assert env.post(client,path+'/play-sheet',form.values).status_code==303
    assert SheetForm(client.get(path).text).values['speed.base']=='20'


def test_base_speed_uses_wizard_race_and_preserves_unknown_legacy_value():
    from pathkeeper.sheet_calculations import recalculate
    character=Character(owner_id=1,name='Tester',ancestry='Elf',class_name='Fighter',level=2,
                        sheet_data={'input':{'race':'halfling'}},play_data={})
    values={'speed.base':'99'}
    assert recalculate(character,values)['speed.base']=='20'
    assert 'Halfling' in sheet_formulas(character,values)['speed.base']
    character.sheet_data=None;character.ancestry='Unknown ancestry'
    values={'speed.base':'35'}
    assert recalculate(character,values)['speed.base']=='35'
    assert 'previously recorded' in sheet_formulas(character,values)['speed.base']

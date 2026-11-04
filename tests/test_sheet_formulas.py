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

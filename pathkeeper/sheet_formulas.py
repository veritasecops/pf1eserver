"""Plain-language descriptions of the formulas the play sheet actually uses."""
from .pf1_data import ABILITIES
from .rule_catalog import character_catalog
from .sheet_calculations import calculated_fields, base_speed_race


def sheet_formulas(character, values):
    locked=calculated_fields(character,values)
    race=base_speed_race(character)
    speed_source=(f"Base speed is {race['speed']} ft. because {race['name']} has a racial land speed of {race['speed']} ft. This is the speed before class bonuses, armor, or other movement adjustments." if race else 'The character’s previously recorded base speed is preserved because a supported race could not be identified.')
    formulas={
        'level':'Character level is the last completed level. XP on the campaign track unlocks the next level-up wizard.',
        'next_level':'Total XP required for the next level on the campaign advancement track. Blank at level 20.',
        'load.total':'Add the weights of every named gear entry. The total stays blank while any item has an unknown or unrecorded weight.',
        'speed.base':speed_source,
        'player':'The name of the account that owns this character.',
        'class_name':'The class recorded for this character.',
        'initiative.total':'Initiative = Dexterity modifier + miscellaneous initiative modifier.',
        'initiative.dex':'Use the Dexterity modifier. If a temporary Dexterity score is entered, use its modifier instead.',
        'cmb.total':'Combat maneuver bonus = base attack bonus + Strength modifier + combat maneuver size modifier + miscellaneous modifier.',
        'cmd.total':'Combat maneuver defense = 10 + base attack bonus + Strength modifier + Dexterity modifier + combat maneuver size modifier + miscellaneous modifier.',
        'ac.total':'Armor Class = 10 + armor bonus + shield bonus + recorded Dexterity modifier + size modifier + natural armor + deflection + dodge + miscellaneous modifier.',
        'ac.touch':'Touch Armor Class = 10 + recorded Dexterity modifier + size modifier + deflection + dodge + miscellaneous modifier. Armor, shield, and natural armor bonuses are excluded.',
        'ac.flat':'Flat-footed Armor Class = 10 + armor bonus + shield bonus + size modifier + natural armor + deflection + miscellaneous modifier. Add the recorded Dexterity modifier only if it is negative; omit dodge bonuses.',
        'ac.size':'Use the Armor Class size modifier for the entered size: Fine +8, Diminutive +4, Tiny +2, Small +1, Medium 0, Large −1, Huge −2, Gargantuan −4, Colossal −8.',
        'skill_points.total':'Skill points per level = class base skill points + Intelligence modifier, with a minimum of 1, then add the miscellaneous skill point modifier.',
        'skill_points.int':'Use the Intelligence modifier, or its temporary modifier when a temporary Intelligence score is entered.',
        'skill_points.base':'The base skill points per level supplied by the character’s class.',
        'hp.total':'First-level hit points = the class’s full Hit Die + Constitution modifier (minimum 1), then add the recorded favored-class hit point bonus and supported feat hit point bonuses. A temporary Constitution score uses its temporary modifier.',
        'bab':'The first-level base attack bonus saved by the character creation wizard for this class.',
    }
    for ability,label in ABILITIES.items():
        formulas[f'ability.{ability}.mod']=f'{label} modifier = ({label} score − 10) ÷ 2, rounded down. For example, a score of 9 gives −1.'
        formulas[f'ability.{ability}.temp_mod']=f'Temporary {label} modifier = (temporary {label} score − 10) ÷ 2, rounded down. Leave the temporary score blank when no temporary score applies.'
    for kind in ('cmb','cmd'):
        formulas[f'{kind}.bab']='Use the character’s base attack bonus.'
        formulas[f'{kind}.str']='Use the Strength modifier, or its temporary modifier when a temporary Strength score is entered.'
        formulas[f'{kind}.size']='Use the combat maneuver size modifier, the opposite of the Armor Class size modifier: Small −1, Medium 0, Large +1, and so on.'
    formulas['cmd.dex']=formulas['initiative.dex']
    for save,ability in [('fortitude','Constitution'),('reflex','Dexterity'),('will','Wisdom')]:
        formulas[f'save.{save}.total']=f'{save.capitalize()} save = base save bonus + {ability} modifier + magic modifier + miscellaneous modifier.'
        formulas[f'save.{save}.ability']=f'Use the {ability} modifier, or its temporary modifier when a temporary {ability} score is entered.'
        formulas[f'save.{save}.base']=f'The first-level base {save.capitalize()} save bonus supplied by the character’s class.'
    for skill,meta in character_catalog(character)['skills'].items():
        ability=ABILITIES[meta['ability']]
        for row in (skill,skill+'-2') if skill in {'craft','perform','profession'} else (skill,):
            formulas[f'skill.{row}.ability']=f'Use the {ability} modifier, or its temporary modifier when a temporary {ability} score is entered.'
            formulas[f'skill.{row}.total']=f'{meta["name"]} total = {ability} modifier + invested ranks + miscellaneous modifier. Add +3 if this is a class skill and at least one rank is invested. The miscellaneous field holds recorded racial, feat, armor-check, and other adjustments.'
    for row in range(56):
        formulas[f'feature.{row}'] = "Recorded during character creation, level-up, or through Add Feat."
    for level in range(10):
        formulas[f'spell.{level}.known']='Count the nonblank lines in this level’s spell list. Each nonblank line counts as one spell.'
    from .character_weapons import inventory as current_inventory
    inventory=current_inventory(character,values,character_catalog(character))
    for row in range(6):
        entry=next((item for item in inventory if item.get('row')==row),None)
        for part in ('name','quantity','attack','critical','type','range','ammunition','damage'):
            formulas[f'weapon.{row}.{part}']='Supplied by the weapon inventory or saved character creation sheet; add weapons through Add Equipment.'
        if entry and ('fields' not in entry or values.get(f'weapon.{row}.equipped')=='1' and entry['item'].get('damage')):
            item=entry['item']
            formulas[f'weapon.{row}.quantity']='The total number of copies of this weapon recorded in inventory.'
            formulas[f'weapon.{row}.attack']='Weapon attack bonus = base attack bonus + attack ability modifier + Armor Class size modifier + supported feat attack bonuses for this weapon. Ranged weapons use Dexterity; melee weapons use Strength, or Dexterity with Weapon Finesse for an eligible weapon. Use temporary ability modifiers when entered. Bows apply −2 if Strength is below the bow’s rating.'
            formulas[f'weapon.{row}.damage']='Weapon damage starts with the saved damage dice for the character’s size. Melee weapons add Strength; two-handed melee weapons multiply a positive Strength bonus by 1.5 and round down. Thrown weapons and slings add Strength. Bows apply negative Strength, or positive Strength up to the composite bow’s rating (ordinary bows allow no positive bonus). Other ranged weapons add no Strength. Temporary Strength is used when entered.'
        else:
            for part in ('attack','damage'):
                formulas[f'weapon.{row}.{part}']='Retained from the saved weapon entry or character creation snapshot. This existing entry is not recalculated from current ability scores.'
        for part in ('name','quantity','type','bonus','max_dex','penalty','failure','weight'):
            formulas[f'armor.{row}.{part}']='Supplied by the saved armor inventory or character creation sheet; add armor through Add Equipment.'
        entry=next((item for item in inventory if item.get('armor_row')==row),None)
        if entry and 'armor_fields' not in entry:
            formulas[f'armor.{row}.quantity']='The total number of copies of this armor or shield recorded in inventory.'
            formulas[f'armor.{row}.weight']='Weight per item = the saved Medium-size catalog weight, multiplied by ½ for a Small character. This armor row shows one item’s weight; the gear row records the quantity’s combined weight.'
    return {key:formulas[key] for key in locked}

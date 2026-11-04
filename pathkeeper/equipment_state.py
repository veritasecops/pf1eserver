"""Equipped markers shared by an item’s combat row and its gear entry."""
from fastapi import HTTPException
from .rule_catalog import character_catalog


def equipment_groups(character,values):
    from .character_weapons import inventory
    groups=[]
    for entry in inventory(character,values,character_catalog(character)):
        fields=[]
        if entry.get('row') is not None: fields.append(f"weapon.{entry['row']}.equipped")
        if entry.get('armor_row') is not None: fields.append(f"armor.{entry['armor_row']}.equipped")
        gear=entry.get('gear_row')
        if gear is not None and values.get(f'gear.{gear}.name')==entry.get('gear_label'):
            fields.append(f'gear.{gear}.equipped')
        if len(fields)>1:
            groups.append({'fields':fields,'labels':{key:values.get(key.removesuffix('equipped')+'name','') for key in fields}})
    return groups


def equipped_values(values):
    return {key:value for key,value in values.items() if key.endswith('.equipped')}


def sync_equipped(character,values,previous):
    for group in equipment_groups(character,values):
        changes={values.get(key,'') for key in group['fields'] if values.get(key,'')!=previous.get(key,'')}
        if len(changes)>1: raise HTTPException(422,'Use the same equipped status for an item and its gear entry.')
        selected=next(iter(changes)) if changes else values.get(group['fields'][0],'')
        for key in group['fields']: values[key]=selected
    for key in equipped_values(values):
        if not values.get(key.removesuffix('equipped')+'name','').strip(): values[key]=''

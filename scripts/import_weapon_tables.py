"""Convert a DOM export of the requested d20PFSRD tables into bounded weapon facts.

Input: [{"rows": [[{"text": ..., "links": [{"url": ...}], "footnotes": []}, ...], ...]}]
Only the Simple/Martial/Exotic weapon table headers are accepted. No prose is imported.
"""
import json
from pathlib import Path
import re
import sys
from decimal import Decimal
from fractions import Fraction


def convert(tables):
    weapons = {}
    categories = {'Unarmed Attacks':'unarmed','Light Melee Weapons':'light','One-Handed Melee Weapons':'one-handed',
                  'Two-Handed Melee Weapons':'two-handed','Ranged Weapons':'ranged','Ammunition':'ammunition'}
    aliases = {'Crossbow, light':('light-crossbow',['Light crossbow']), 'Sword, short':('shortsword',['Shortsword']),
               'Bolt(s), crossbow (10)':('bolts',['Crossbow bolts (10)']), 'Arrows, common (20)':('arrows',['Arrows (20)'])}
    projectiles = ('bow','crossbow','blowgun','stonebow','pelletbow','wrist launcher','flask thrower','spear-sling','throwing arrow cord')
    for table in tables:
        match = re.fullmatch(r'\((Simple|Martial|Exotic)\)\s*(.*)',table['rows'][0][0]['text'])
        if not match: continue
        group,category = match[1].lower(),categories[match[2]]
        for row in table['rows'][1:]:
            if len(row)!=10: raise ValueError('Unexpected weapon columns')
            name,cost,small,damage,critical,reach,weight,damage_type,special,source = (c['text'] for c in row)
            # Both printings of the sawtooth sabre are distinct rows in the source.
            if row[0].get('footnotes'): name += ' ('+', '.join(row[0]['footnotes'])+')'
            key,known = aliases.get(name,(re.sub(r'[^a-z0-9]+','-',name.lower().replace('+','plus-')).strip('-'),[]))
            if key in weapons: raise ValueError('Duplicate weapon: '+key)
            url=row[0]['links'][0]['url']
            price = re.fullmatch(r'(\d+(?:\.\d+)?) (cp|sp|gp|pp)',cost)
            amount = int(Decimal(price[1])*{'cp':1,'sp':10,'gp':100,'pp':1000}[price[2]]) if price else 0 if cost=='—' else None
            mass = re.fullmatch(r'([0-9./]+) lbs?\.?',weight)
            pounds = float(Fraction(mass[1])) if mass else 0 if weight=='—' else None
            lower=name.lower()
            bow = ('bow' in lower and 'crossbow' not in lower and 'pelletbow' not in lower and 'stonebow' not in lower)
            composite = re.search(r'\(\+(\d)\)',name)
            rating = int(composite[1]) if composite else 0 if 'composite' in lower else None
            ranged = category=='ranged'
            thrown = ranged and not any(word in lower for word in projectiles) and 'sling' not in lower
            finesse = category in {'light','unarmed'} or 'finesse' in special.lower() or lower in {'whip','whip, scorpion','chain, spiked','curve blade, elven'}
            weapons[key] = dict(name=name,kind='gear' if category=='ammunition' else 'weapon',enabled=True,group=group,category=category,
                cost=amount,cost_text=cost,weight=pounds,weight_text=weight,small_damage=small,damage=damage,critical=critical,
                range=reach,damage_type=damage_type,special=special,source=source,url=url,aliases=known,notes='',
                ranged=ranged,bow=bow,two_handed=category=='two-handed',finesse=finesse,thrown=thrown,
                add_strength=thrown or (ranged and 'sling' in lower),strength_rating=rating)
    return weapons


if __name__=='__main__':
    data=convert(json.loads(Path(sys.argv[1]).read_text()))
    Path(sys.argv[2]).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(f'Imported {len(data)} entries.')

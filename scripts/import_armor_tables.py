"""Import the five Armor and Shields tables from a read-only DOM export.

Source: https://www.d20pfsrd.com/equipment/armor
Input matches scripts/import_weapon_tables.py's bounded table facts, with cell URLs.
"""
import json
from pathlib import Path
import re
import sys


def convert(tables):
    result={}
    categories={'Light Armors':'light','Medium Armors':'medium','Heavy Armors':'heavy','Shields':'shield','Extras':'extra'}
    aliases={'Shield, light wooden':('light-shield',['Light wooden shield']),
             'Shield, heavy wooden':('heavy-shield',['Heavy wooden shield'])}
    def number(text,default=None):
        return int(text.replace('–','-')) if re.fullmatch(r'[+–-]?\d+',text) else default
    for table in tables:
        category=categories.get(table['rows'][0][0]['text'])
        if not category: continue
        for row in table['rows'][3:]:
            if len(row)!=10: raise ValueError('Unexpected armor columns')
            name,cost,bonus,dex,acp,failure,speed30,speed20,weight,source=[c['text'] for c in row]
            name=name.rstrip('*').strip()
            key,known=aliases.get(name,(re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-'),[]))
            if category=='extra': key='armor-extra-'+key
            if key in {'klar','war-shield-dwarven'}: key='armor-'+key
            if key in result: raise ValueError('Duplicate armor '+key)
            price=re.fullmatch(r'\+?([\d,]+) gp',cost)
            mass=re.fullmatch(r'\+?([\d.]+) lbs?\.',weight)
            kind='shield' if category=='shield' else 'gear' if category=='extra' else 'armor'
            result[key]=dict(name=name,kind=kind,category=category,enabled=True,cost=int(price[1].replace(',',''))*100 if price else None,
                cost_text=cost,weight=float(mass[1]) if mass else None,weight_text=weight,
                armor=number(bonus,0) if kind=='armor' else 0,shield=number(bonus,0) if kind=='shield' else 0,
                bonus_text=bonus,max_dex=number(dex,100),max_dex_text=dex,acp=number(acp,0),acp_text=acp,
                spell_failure=number(failure.rstrip('%')),spell_failure_text=failure,
                speed_30=number(speed30.removesuffix(' ft.')),speed_20=number(speed20.removesuffix(' ft.')),
                speed_30_text=speed30,speed_20_text=speed20,source=source,url=row[0]['url'],aliases=known,
                notes='See reference for conditional effects.' if bonus=='See text' or category=='extra' else '')
    return result


if __name__=='__main__':
    data=convert(json.loads(Path(sys.argv[1]).read_text()))
    Path(sys.argv[2]).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(f'Imported {len(data)} armor, shield, and extra entries.')

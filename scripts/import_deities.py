"""Import bounded names and URLs from the requested PathfinderWiki deity sections.

Inputs are read-only DOM exports of Deity and its linked regional pantheons.
No descriptions, portraits, or rule mechanics are copied.
"""
import json
from pathlib import Path
import re
import sys
import unicodedata


def convert(sections,regions):
    result={}
    def add(link,section,region=''):
        name,url=link['name'],link['url']
        if not name or not url.startswith('https://pathfinderwiki.com/wiki/'): raise ValueError('Invalid deity reference')
        key=re.sub(r'[^a-z0-9]+','-',unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode().lower()).strip('-')
        entry=result.setdefault(key,dict(name=name,url=url,enabled=True,sections=[],regions=[],aliases=[]))
        if entry['url']!=url: raise ValueError('Ambiguous deity '+name)
        if section not in entry['sections']: entry['sections'].append(section)
        if region and region not in entry['regions']: entry['regions'].append(region)
    excluded={'Inner Sea region','Ascension','Ascended','Test of the Starstone','Category:Ascended mortals','Starstone','Rahadoum'}
    for section in sections:
        if section['section']=='In other regions': continue
        for link in section['links']:
            if link['name'] in excluded: continue
            add(link,section['section'])
    region_names={'Ancient Osirian':'Osirion','Arcadian':'Arcadia','Mwangi':'Mwangi Expanse','Tien':'Tian Xia','Vudran':'Vudra'}
    for group in regions:
        for link in group['links']:
            if link['name'] in {'Arcadian hero-god','Celestial Court'}: continue
            add(link,'In other regions',region_names.get(group['region'],group['region']))
    return dict(sorted(result.items(),key=lambda pair:pair[1]['name'].casefold()))


if __name__=='__main__':
    data=convert(json.loads(Path(sys.argv[1]).read_text()),json.loads(Path(sys.argv[2]).read_text()))
    Path(sys.argv[3]).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(f'Imported {len(data)} unique deity or belief records.')

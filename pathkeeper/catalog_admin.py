"""Administrator forms for the supported first-level rule catalog."""
import json
import re
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .feats import FEAT_CATEGORIES
from .equipment_index import GROUPS as EQUIPMENT_GROUPS, equipment_categories as catalog_categories, equipment_entries
from .class_catalog import class_profile
from .class_editor import editor as class_editor, parse_class
from .models import Guard, RuleCatalog, utcnow
from .pf1_data import ABILITIES, CLASSES
from .rule_catalog import EFFECTS, default_catalog
from .weapons import safe_weapon_url, WEAPON_CATEGORIES, WEAPON_GEAR_CATEGORIES, WEAPON_GROUPS
from .armor import ARMOR_CATEGORIES
from .security import administrator, audit, context, field, integer, read_form
from .ui import redirect, render

router = APIRouter(prefix='/administration/catalog')
equipment_router = APIRouter(prefix='/administration/equipment')
magic_items_router = APIRouter(prefix='/administration/magic-items')
KINDS = {'feats':'Feats','skills':'Skills','weapons':'Weapons','armor':'Armor','equipment':'Equipment','deities':'Deities','classes':'Character Classes'}
RULE_TABS = {**{key: KINDS[key] for key in ('feats', 'skills')}, 'spells': 'Spells',
             **{key: KINDS[key] for key in ('deities', 'classes')}}
SPELL_MARKERS = {'F': 'Special focus', 'M': 'Special material', 'R': 'Religion or ancestry requirement',
                 'T': 'Torag preparation requirement'}


def record_for(ctx, lock=False):
    if lock:
        ctx.db.execute(select(Guard).where(Guard.id == 1).with_for_update())
    query = select(RuleCatalog).where(RuleCatalog.id == 1)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    record = ctx.db.scalar(query)
    if not record:
        record = RuleCatalog(id=1,data=default_catalog())
        ctx.db.add(record)
        ctx.db.flush()
    return record


def kind_check(kind):
    if kind not in KINDS: raise HTTPException(404,'Catalog not found.')


def catalog_location(kind, group=""):
    group = {"weapons": "Weapons", "armor": "Armor"}.get(kind, group)
    if kind in {"equipment", "weapons", "armor"}:
        return "/administration/equipment" + ("?" + urlencode({"equipment_group": group}) if group else "")
    return f"/administration/catalog?kind={kind}"


def editor(ctx, record, kind, key, item, errors=(), new=False):
    response = render(ctx,'catalog_edit.html',title='Add catalog entry' if new else 'Edit '+item.get('name',key),
                      kinds=KINDS,kind=kind,key=key,item=item,new=new,version=record.version,
                      catalog_back=catalog_location(kind, item.get("group", "") if kind == "equipment" else ""),
                      equipment_editor=kind in {"weapons", "armor"},
                      abilities=ABILITIES,classes=CLASSES,skills=record.data['skills'],feats=record.data['feats'],
                      effects=EFFECTS,feat_categories=FEAT_CATEGORIES,errors=errors,weapon_url=safe_weapon_url,weapon_categories=WEAPON_CATEGORIES,weapon_groups=WEAPON_GROUPS,armor_categories=ARMOR_CATEGORIES,equipment_groups=EQUIPMENT_GROUPS)
    if errors: response.status_code=422
    return response


@router.get('')
async def catalog_page(request: Request, db: Session = Depends(get_db)):
    ctx=context(request,db)
    administrator(ctx)
    kind = request.query_params.get('kind', 'feats')
    if kind == 'spells':
        return render_spell_catalog(ctx, request)
    if kind == 'equipment':
        query = urlencode([(key, value) for key, value in request.query_params.multi_items() if key != 'kind'])
        return RedirectResponse('/administration/equipment' + ('?' + query if query else ''), status_code=303)
    return render_catalog(ctx, request, kind)


@equipment_router.get('')
async def equipment_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return render_catalog(ctx, request, 'equipment')


@lru_cache
def magic_items():
    return json.loads((Path(__file__).parent / 'data' / 'magic_items.json').read_text())


@lru_cache
def spells():
    return json.loads((Path(__file__).parent / 'data' / 'spells.json').read_text())


@lru_cache
def spell_defaults():
    return {sha256(spell['url'].encode()).hexdigest(): spell for spell in spells()}


@lru_cache
def spell_choices():
    return (sorted({school for spell in spells() for school in spell['schools']}),
            sorted({name for spell in spells() for name in spell['levels']}))


def render_spell_catalog(ctx, request):
    params = request.query_params
    overrides = record_for(ctx).data.get('spell_overrides', {})
    entries = ((key, overrides.get(key, spell)) for key, spell in spell_defaults().items())
    schools, classes = spell_choices()
    search = params.get('q', '').strip()[:100]
    school = params.get('school', '')
    school = school if school in schools else ''
    spell_class = params.get('class', '')
    spell_class = spell_class if spell_class in classes else ''
    raw_level = params.get('level', '')
    level = int(raw_level) if re.fullmatch(r'[0-9]', raw_level) else None
    mythic = params.get('mythic') == '1'

    def matches(spell):
        if search.casefold() not in spell['name'].casefold() or (school and school not in spell['schools']):
            return False
        if mythic and not spell['mythic']:
            return False
        levels = spell['levels']
        if spell_class:
            return spell_class in levels and (level is None or level in levels[spell_class])
        return level is None or any(level in values for values in levels.values())

    items = sorted(((key, spell) for key, spell in entries if matches(spell)),
                   key=lambda entry: (entry[1]['name'].casefold(), entry[0]))
    total = len(items)
    pages = max(1, (total + 49) // 50)
    raw_page = params.get('page', '')
    page = min(int(raw_page), pages) if re.fullmatch(r'[1-9][0-9]{0,5}', raw_page) else 1
    query = urlencode({'kind': 'spells', 'q': search, 'school': school, 'class': spell_class,
                       'level': '' if level is None else level, 'mythic': '1' if mythic else ''})
    return render(ctx, 'spell_catalog.html', title='Spells', kind='spells', rule_tabs=RULE_TABS,
                  items=items[(page - 1) * 50:page * 50], schools=schools, classes=classes,
                  search=search, school=school, spell_class=spell_class, level=level, mythic=mythic,
                  total=total, page=page, pages=pages, query=query, marker_labels=SPELL_MARKERS)


def spell_editor(ctx, record, key, form=None, errors=()):
    spell = spell_defaults().get(key)
    if spell is None:
        raise HTTPException(404, 'Spell not found.')
    spell = record.data.get('spell_overrides', {}).get(key, spell)
    schools, classes = spell_choices()
    values = {**spell, 'class_levels': {name: ', '.join(map(str, levels)) for name, levels in spell['levels'].items()}}
    if form is not None:
        values.update(name=form.get('name', ''), url=form.get('url', ''),
                      schools=form.getlist('schools'), markers=form.getlist('markers'),
                      mythic=form.get('mythic') == 'on', pfs_marked=form.get('pfs_marked') == 'on',
                      class_levels={name: form.get(f'level.{name}', '') for name in classes})
    response = render(ctx, 'spell_edit.html', title='Edit spell', kind='spells', rule_tabs=RULE_TABS,
                      key=key, spell=values, schools=schools, classes=classes, marker_labels=SPELL_MARKERS,
                      version=record.version, errors=errors)
    if errors:
        response.status_code = 422
    return response


def parse_spell(form):
    schools, classes = spell_choices()
    selected_schools = set(form.getlist('schools'))
    if not selected_schools or selected_schools.difference(schools):
        raise HTTPException(422, 'Select at least one spell school from the list.')
    markers = set(form.getlist('markers'))
    if markers.difference(SPELL_MARKERS):
        raise HTTPException(422, 'Choose source markers from the list.')
    url = field(form, 'url', 1000)
    if not safe_weapon_url(url):
        raise HTTPException(422, 'Enter a valid HTTP or HTTPS spell reference URL.')
    levels = {}
    for name in classes:
        raw = field(form, f'level.{name}', 40, required=False)
        if raw:
            if not re.fullmatch(r'[0-9](?:\s*,\s*[0-9])*', raw):
                raise HTTPException(422, f'Enter levels 0 through 9 for {name}, separated by commas.')
            levels[name] = sorted({int(value) for value in raw.split(',')})
    mythic = form.get('mythic') == 'on'
    return {'name': field(form, 'name'), 'url': url, 'schools': sorted(selected_schools),
            'levels': levels, 'mythic': mythic, 'pfs_marked': form.get('pfs_marked') == 'on',
            'markers': sorted(markers | ({'Y'} if mythic else set()))}


@magic_items_router.get('')
async def magic_items_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    params = request.query_params
    search = params.get('q', '').strip()[:100]
    catalog = magic_items()
    groups = sorted({item['group'] for item in catalog})
    group = params.get('group', '')
    if group not in groups:
        group = ''
    group_items = [item for item in catalog if not group or item['group'] == group]
    categories = sorted({category for item in group_items for category in item['categories']})
    category = params.get('category', '')
    if category not in categories:
        category = ''
    items = [item for item in group_items if search.casefold() in item['name'].casefold()
             and (not category or category in item['categories'])]
    total = len(items)
    pages = max(1, (total + 99) // 100)
    raw_page = params.get('page', '')
    page = min(int(raw_page), pages) if re.fullmatch(r'[1-9][0-9]{0,5}', raw_page) else 1
    query = urlencode({'q': search, 'group': group, 'category': category})
    return render(ctx, 'magic_items.html', title='Magic Items', items=items[(page - 1) * 100:page * 100],
                  groups=groups, group=group, categories=categories, category=category,
                  search=search, total=total, page=page, pages=pages, query=query)


def render_catalog(ctx, request, kind):
    kind_check(kind)
    record = record_for(ctx)
    search=request.query_params.get('q','').strip()[:100]
    entries = {key: class_profile(record.data, key) for key in CLASSES} if kind == 'classes' else record.data.get(kind, {})
    if kind == 'equipment':
        entries = equipment_entries(record.data)
    items=[(key,item) for key,item in entries.items() if search.casefold() in item.get('name',key).casefold()]
    group=request.query_params.get('group','') if kind in {'weapons', 'equipment'} else ''
    category=request.query_params.get('category','') if kind=='weapons' else ''
    if kind == 'weapons' and group in WEAPON_GROUPS:
        items=[(key,item) for key,item in items if group in item.get('proficiencies', [item.get('group')])]
    feat_category = request.query_params.get('feat_category', '') if kind == 'feats' else ''
    if feat_category in FEAT_CATEGORIES:
        items = [(key, item) for key, item in items if feat_category in item.get('categories', ())]
    if category in WEAPON_CATEGORIES: items=[(key,item) for key,item in items if item.get('category')==category]
    equipment_group = request.query_params.get('equipment_group', '') if kind == 'equipment' else ''
    equipment_category = request.query_params.get('equipment_category', '') if kind == 'equipment' else ''
    equipment_categories = []
    equipment_counts = {}
    equipment_status = ''
    if kind == 'equipment':
        equipment_counts = {label: sum(item["group"] == label for item in entries.values()) for label in EQUIPMENT_GROUPS}
        equipment_status = request.query_params.get('equipment_status', '')
        if equipment_status in {'available', 'archived'}:
            items = [(key, item) for key, item in items if item.get('enabled', True) == (equipment_status == 'available')]
        else:
            equipment_status = ''
        if equipment_group not in EQUIPMENT_GROUPS:
            # Older category bookmarks may not specify a group.
            matching_groups = {item["group"] for item in entries.values()
                               if equipment_category and equipment_category in item["categories"]}
            equipment_group = next(iter(matching_groups)) if len(matching_groups) == 1 else EQUIPMENT_GROUPS[0]
        items = [(key, item) for key, item in items if item["group"] == equipment_group]
        if equipment_group == 'Weapons' and group in WEAPON_GROUPS:
            items = [(key, item) for key, item in items if group in item.get('proficiencies', ())]
        equipment_categories = catalog_categories(entries, equipment_group)
        if equipment_category in equipment_categories:
            items = [(key, item) for key, item in items if equipment_category in item["categories"]]
    items.sort(key=lambda pair:pair[1].get('name',pair[0]).casefold())
    total = len(items)
    pages = max(1, (total + 99) // 100) if kind in {'feats', 'equipment'} else 1
    raw_page = request.query_params.get('page', '1')
    page = min(int(raw_page), pages) if re.fullmatch(r'[1-9][0-9]{0,5}', raw_page) else 1
    if kind in {'feats', 'equipment'}:
        items = items[(page - 1) * 100:page * 100]
    return render(ctx,'catalog.html',title='Equipment' if kind == 'equipment' else 'Rules catalog',kinds=KINDS,kind=kind,items=items,search=search,total=total,page=page,pages=pages,version=record.version,weapon_url=safe_weapon_url,weapon_groups=WEAPON_GROUPS,weapon_categories=WEAPON_CATEGORIES,group_filter=group,category_filter=category,feat_category=feat_category,feat_categories=FEAT_CATEGORIES,equipment_groups=EQUIPMENT_GROUPS,equipment_group=equipment_group,equipment_category=equipment_category,equipment_categories=equipment_categories,
                  equipment_counts=equipment_counts,equipment_status=equipment_status,weapon_items=record.data.get('weapons', {}),rule_tabs=RULE_TABS)


@router.get('/{kind}/new')
async def new_entry(kind: str, request: Request, db: Session = Depends(get_db)):
    ctx=context(request,db)
    administrator(ctx)
    kind_check(kind)
    if kind == 'classes':
        raise HTTPException(404, 'Select a character class to edit.')
    item = {'enabled': True, 'ability': 'str', 'kind': 'weapon'}
    if kind == 'equipment':
        group = request.query_params.get('equipment_group', 'Miscellaneous')
        item['group'] = group if group in {'Special Materials', 'Miscellaneous'} else 'Miscellaneous'
    return editor(ctx, record_for(ctx), kind, '', item, new=True)


@router.get('/{kind}/{key}')
async def edit_entry(kind: str, key: str, request: Request, db: Session = Depends(get_db)):
    ctx=context(request,db)
    administrator(ctx)
    if kind == 'spells':
        return spell_editor(ctx, record_for(ctx), key)
    kind_check(kind)
    record=record_for(ctx)
    if kind == 'classes':
        if key not in CLASSES:
            raise HTTPException(404, 'Character class not found.')
        return class_editor(ctx, record, key)
    if kind == 'equipment':
        item = equipment_entries(record.data).get(key)
        if item is None:
            raise HTTPException(404, 'Equipment entry not found.')
        if item.get('editor_kind'):
            return redirect(ctx, f"/administration/catalog/{item['editor_kind']}/{item['editor_key']}")
        return editor(ctx, record, kind, key, {'enabled': True, **item})
    if key not in record.data[kind]: raise HTTPException(404,'Catalog entry not found.')
    return editor(ctx,record,kind,key,record.data[kind][key])


def parse_entry(form,kind,key,catalog):
    item={'enabled':form.get('enabled')=='on'}
    item['name']=key if kind=='feats' else field(form,'name',100)
    if kind == 'equipment':
        item.update(group=field(form, 'group', 30), url=field(form, 'url', 1000, required=False),
                    cost_text=field(form, 'cost_text', 1000, required=False),
                    weight_text=field(form, 'weight_text', 120, required=False),
                    details=field(form, 'details', 3000, required=False))
        categories = field(form, 'equipment_categories', 1000, required=False)
        item['categories'] = list(dict.fromkeys(line.strip() for line in categories.splitlines() if line.strip()))
        if item['group'] not in EQUIPMENT_GROUPS:
            raise HTTPException(422, 'Choose an equipment group.')
        if item['url'] and not safe_weapon_url(item['url']):
            raise HTTPException(422, 'Use a safe HTTP or HTTPS reference link.')
        return item

    def number(name,low=-100,high=100,decimal=False):
        raw=str(form.get(name,'0')).strip() or '0'
        if decimal:
            from decimal import Decimal, InvalidOperation
            try:
                value=Decimal(raw)
                if not value.is_finite() or not low<=value<=high or value.as_tuple().exponent < -2: raise ValueError
                return float(value)
            except (ValueError,InvalidOperation): raise HTTPException(422,f'{name}: enter a number from {low} to {high}, with at most two decimal places.') from None
        return integer({name:raw},name,low,high)
    if kind in {'feats', 'skills'}:
        existing = catalog[kind].get(key, {})
        item['url'] = field({'url': form.get('url', existing.get('url', ''))}, 'url', 1000, required=False)
        if item['url'] and not safe_weapon_url(item['url']):
            raise HTTPException(422, 'Reference link must be a safe HTTP or HTTPS URL.')
    if kind=='feats':
        item.update(hint=field(form,'hint',1000,required=False),combat=form.get('combat')=='on',
                    monk=form.get('monk')=='on',repeatable=form.get('repeatable')=='on',finesse=form.get('finesse')=='on',
                    pfs_marked=form.get('pfs_marked')=='on', prerequisite_notes=field(form,'prerequisite_notes',2000,required=False),
                    mastery=field(form,'mastery',20,required=False))
        categories = set(form.getlist('categories'))
        if categories - set(FEAT_CATEGORIES):
            raise HTTPException(422, 'Choose categories from the feat category list.')
        if 'categories_present' in form:
            item['categories'] = [label for label in FEAT_CATEGORIES if label in categories]
        elif 'categories' in catalog[kind].get(key, {}):
            item['categories'] = catalog[kind][key]['categories']
        if item['mastery'] not in {'', 'armor', 'shield', 'weapon'}:
            raise HTTPException(422, 'Choose a valid mastery category.')
        choice=str(form.get('choice',''))
        if choice not in {'','skill','weapon'}: raise HTTPException(422,'Choose a valid selection type.')
        item['choice']=choice
        item['bab']=number('bab',0,40)
        for ability in ABILITIES: item[ability]=number(ability,0,40)
        requires=str(form.get('requires',''))
        if requires and (requires not in catalog['feats'] or requires==key): raise HTTPException(422,'Choose another existing prerequisite feat.')
        visited={key}
        dependency=requires
        while dependency:
            if dependency in visited: raise HTTPException(422,'Feat prerequisites cannot form a cycle.')
            visited.add(dependency)
            dependency=catalog['feats'].get(dependency,{}).get('requires','')
        item['requires']=requires
        item['effects']={target:number('effect.'+target) for target in [*EFFECTS,*('skill:'+skill for skill in catalog['skills'])]}
        item['effects']={key:value for key,value in item['effects'].items() if value}
        if item['effects'].get('selected_skill') and choice!='skill': raise HTTPException(422,'A selected-skill bonus requires a skill selection.')
        if item['effects'].get('selected_weapon') and choice!='weapon': raise HTTPException(422,'A selected-weapon bonus requires a weapon selection.')
        if item['repeatable'] and not choice: raise HTTPException(422,'Repeatable feats require a skill or weapon choice; copies with the same choice do not stack.')
    elif kind=='skills':
        ability=str(form.get('ability',''))
        if ability not in ABILITIES: raise HTTPException(422,'Choose a valid skill ability.')
        classes=form.getlist('classes')
        if set(classes)-set(CLASSES): raise HTTPException(422,'Choose valid classes.')
        item.update(ability=ability,classes=sorted(set(classes)),armor=form.get('armor')=='on',trained=form.get('trained')=='on',bonus=number('bonus'))
    elif kind=='deities':
        existing=catalog.get('deities',{}).get(key,{})
        item['url']=field(form,'url',1000)
        if not safe_weapon_url(item['url']): raise HTTPException(422,'Description link must be an HTTP or HTTPS URL without credentials or spaces.')
        item['aliases']=list(existing.get('aliases',[]))
        if existing and existing['name']!=item['name']: item['aliases']=list(dict.fromkeys([*item['aliases'],existing['name']]))
        item['sections']=existing.get('sections',[])
        item['regions']=existing.get('regions',[])
        for other,entry in catalog.get('deities',{}).items():
            if other!=key and item['name'].casefold() in {name.casefold() for name in [entry['name'],*entry.get('aliases',[])]}:
                raise HTTPException(422,'A deity with that name or alias already exists.')
    elif kind=='armor':
        category=str(form.get('category',''))
        if category not in ARMOR_CATEGORIES: raise HTTPException(422,'Choose an armor category.')
        item.update(category=category,kind='shield' if category=='shield' else 'gear' if category=='extra' else 'armor',
                    cost=None if not str(form.get('cost','')).strip() else number('cost',0,100000000),
                    weight=None if not str(form.get('weight','')).strip() else number('weight',0,100000,True),
                    armor=number('armor',0,100),shield=number('shield',0,100),max_dex=number('max_dex',0,100),
                    acp=number('acp',-100,0))
        for name in ('spell_failure','speed_30','speed_20'):
            item[name]=number(name,0,100) if str(form.get(name,'')).strip() else None
        for name in ('url','cost_text','weight_text','bonus_text','max_dex_text','acp_text','spell_failure_text','speed_30_text','speed_20_text','source','notes'):
            item[name]=field(form,name,3000 if name=='notes' else 1000 if name=='url' else 300,required=False)
        if item['url'] and not safe_weapon_url(item['url']): raise HTTPException(422,'Armor link must be a safe HTTP or HTTPS URL.')
        aliases=field(form,'aliases',2000,required=False)
        item['aliases']=list(dict.fromkeys(name.strip() for name in aliases.splitlines() if name.strip()))
        if len(item['aliases'])>20 or any(len(name)>100 for name in item['aliases']): raise HTTPException(422,'Use up to 20 aliases of 100 characters each.')
        old=catalog.get('armor',{}).get(key,{})
        if old and old['name']!=item['name']: item['aliases']=list(dict.fromkeys([*item['aliases'],old['name']]))
    else:
        existing=catalog['weapons'].get(key,{})
        category=str(form.get('category',existing.get('category','ranged' if form.get('ranged')=='on' else 'one-handed')))
        group=field(form,'group',100)
        if category not in WEAPON_CATEGORIES or group not in WEAPON_GROUPS: raise HTTPException(422,'Choose a weapon proficiency and category from the lists.')
        item.update(kind='gear' if category in WEAPON_GEAR_CATEGORIES else 'weapon',category=category,group=group,
                    proficiencies=existing.get('proficiencies', [group]) if group == existing.get('group') else [group],
                    cost=None if 'cost' in form and not str(form['cost']).strip() else number('cost',0,100000000),
                    weight=None if 'weight' in form and not str(form['weight']).strip() else number('weight',0,100000,True),
                    damage=field(form,'damage',120,required=False),small_damage=field(form,'small_damage',120,required=False))
        for name,maximum in {'critical':120,'range':120,'damage_type':120,'special':1000,'source':300,
                             'cost_text':120,'weight_text':120,'notes':3000,'url':1000}.items():
            item[name]=field(form,name,maximum,required=False) if name in form else existing.get(name,'')
        if item['url'] and not safe_weapon_url(item['url']): raise HTTPException(422,'Weapon link must be an HTTP or HTTPS URL without credentials or spaces.')
        aliases=field(form,'aliases',2000,required=False) if 'aliases' in form else '\n'.join(existing.get('aliases',[]))
        item['aliases']=list(dict.fromkeys(name.strip() for name in aliases.splitlines() if name.strip()))
        if len(item['aliases'])>20 or any(len(name)>100 for name in item['aliases']): raise HTTPException(422,'Use up to 20 aliases of 100 characters each.')
        if existing and existing['name']!=item['name']:
            item['aliases']=list(dict.fromkeys([*item['aliases'],existing['name']]))
        for flag in ('ranged','bow','two_handed','finesse','thrown','add_strength'): item[flag]=form.get(flag)=='on'
        rating=str(form.get('strength_rating',existing.get('strength_rating') if existing.get('strength_rating') is not None else '')).strip()
        item['strength_rating']=number('strength_rating',0,20) if rating else None
        if item['strength_rating'] is not None and 'strength_rating' not in form: item['strength_rating']=existing.get('strength_rating')
        if item['bow'] and not item['ranged']: raise HTTPException(422,'A bow must be a ranged weapon.')
        if item['strength_rating'] is not None and not item['bow']: raise HTTPException(422,'A composite Strength rating requires a bow.')
        for name in ('detail_proficiency', 'weapon_groups', 'detail_stats'):
            if name in existing:
                item[name] = existing[name]
        if item['kind']=='gear' and any(item[flag] for flag in ('ranged','bow','two_handed','thrown','add_strength')): raise HTTPException(422,'Weapon accessories are carried as equipment and cannot be equipped as attacks.')
    return item


@router.post('/{kind}')
async def save_entry(kind: str, request: Request, db: Session = Depends(get_db)):
    ctx=context(request,db)
    administrator(ctx)
    if kind != 'spells':
        kind_check(kind)
    form=await read_form(ctx,max_fields=500 if kind == 'classes' else 200)
    record=record_for(ctx,True)
    if integer(form,'version',1,2**31-1)!=record.version: raise HTTPException(409,'The catalog changed in another window. Reload before saving.')
    new=form.get('new')=='1'
    key=field(form,'key',100 if kind in {'feats','equipment','spells'} else 60)
    if kind == 'spells':
        original = spell_defaults().get(key)
        if original is None:
            raise HTTPException(404, 'Spell not found.')
        try:
            spell = parse_spell(form)
        except HTTPException as error:
            return spell_editor(ctx, record, key, form, [error.detail])
        overrides = dict(record.data.get('spell_overrides', {}))
        if spell == original:
            overrides.pop(key, None)
        else:
            overrides[key] = spell
        record.data = {**record.data, 'spell_overrides': overrides}
        record.updated_at, record.updated_by = utcnow(), ctx.user.id
        audit(db, ctx.user, 'catalog.updated', f"Updated spell: {original['name']}.")
        return redirect(ctx, '/administration/catalog?kind=spells', 'Spell saved.')
    if kind == 'classes':
        if new or key not in CLASSES:
            raise HTTPException(404, 'Character class not found.')
        try:
            item, skills = parse_class(form, key, record.data)
        except HTTPException as error:
            if error.status_code != 422:
                raise
            return class_editor(ctx, record, key, form, [error.detail])
        updated = deepcopy(record.data)
        updated.setdefault("classes", {})[key] = item
        if key != "expert":
            for skill_key, skill in updated["skills"].items():
                classes = set(skill.get("classes", [])) - {key}
                if skill_key in skills:
                    classes.add(key)
                skill["classes"] = sorted(classes)
        record.data = updated
        record.updated_at, record.updated_by = utcnow(), ctx.user.id
        audit(db, ctx.user, 'catalog.updated', f'Updated character class {key}.')
        return redirect(ctx, '/administration/catalog?kind=classes', 'Character class saved.')
    if key.casefold()=='new': raise HTTPException(422,'Choose an identifier other than new.')
    if kind=='feats' and any(char in key for char in '/\\?#'):
        raise HTTPException(422,'Feat names cannot contain slashes, question marks or hash signs.')
    if new and kind!='feats' and (not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*',key) or key.endswith('-2')):
        raise HTTPException(422,'Use a stable lowercase identifier with letters, numbers and single hyphens, without a -2 ending.')
    entries = equipment_entries(record.data) if kind == 'equipment' else record.data[kind]
    if new and any(existing.casefold()==key.casefold() for existing in entries): raise HTTPException(409,'That catalog identifier already exists.')
    if not new and key not in entries: raise HTTPException(404,'Catalog entry not found.')
    if kind == 'equipment' and not new and entries[key].get('editor_kind'):
        raise HTTPException(422, 'Edit this item in its Weapons or Armor catalog.')
    if new and len(entries) >= {'skills':75, 'feats':10000, 'equipment':10000}.get(kind,1000): raise HTTPException(422, 'This catalog has reached its entry limit.')
    if new and kind in {'weapons','armor'}:
        from .pf1_data import EQUIPMENT
        if key in EQUIPMENT or key in record.data.get('armor' if kind=='weapons' else 'weapons',{}): raise HTTPException(409,'That identifier is already used by equipment.')
    try:
        item=parse_entry(form,kind,key,record.data)
    except HTTPException as error:
        if error.status_code!=422: raise
        readonly = {'csrf', 'version', 'detail_proficiency', 'weapon_groups', 'detail_stats'}
        item={**entries.get(key,{}),**{k:str(v) for k,v in form.items() if k not in readonly}}
        item.update(enabled=form.get('enabled')=='on',effects={target:form.get('effect.'+target,0) for target in [*EFFECTS,*('skill:'+s for s in record.data['skills'])]},classes=form.getlist('classes'))
        for flag in ('combat','monk','repeatable','finesse','pfs_marked','armor','trained','ranged','bow','two_handed','thrown','add_strength'): item[flag]=form.get(flag)=='on'
        if kind == 'feats' and 'categories_present' in form:
            item['categories'] = form.getlist('categories')
        if kind == 'equipment':
            item['categories'] = str(form.get('equipment_categories', '')).splitlines()
        return editor(ctx,record,kind,key,item,[error.detail],new)
    updated=deepcopy(record.data)
    updated.setdefault('equipment_index' if kind == 'equipment' else kind, {})[key]=item
    record.data=updated
    record.updated_at,record.updated_by=utcnow(),ctx.user.id
    audit(db,ctx.user,'catalog.created' if new else 'catalog.updated',f'{"Added" if new else "Updated"} {kind}: {key}.')
    location = catalog_location(kind, item.get('group', '') if kind == 'equipment' else '')
    return redirect(ctx,location,'Catalog saved. Reload open wizards to use the updated rules. Existing character snapshots retain their rules.')

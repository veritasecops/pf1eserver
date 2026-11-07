"""Published citations for AoN references, served locally without live scraping."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit
from markupsafe import Markup, escape

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import RuleCatalog
from .security import authenticated, context

router = APIRouter()
DATA = Path(__file__).parent / 'data'


def reference_key(url):
    if not isinstance(url, str):
        return ''
    try:
        parts = urlsplit(url)
    except ValueError:
        return ''
    if parts.hostname not in {'www.aonprd.com', 'aonprd.com'}:
        return ''
    return 'www.aonprd.com' + unquote_plus(parts.path + ('?' + parts.query if parts.query else '')
                                         + ('#' + parts.fragment if parts.fragment else '')).casefold()


@lru_cache
def published_sources():
    return json.loads((DATA / 'aon_sources.json').read_text())


def source_for(url):
    return published_sources().get(reference_key(url), '')


def source_note(url, overrides=None):
    source = (overrides or {}).get(reference_key(url), source_for(url))
    return Markup('<small class="aon-source secondary-text" data-reference-source>Source: {}</small>').format(escape(source)) if source else ''


def enrich_sources(value, replace_legacy=False):
    """Add sources by exact reference; preserve custom sources and custom URLs."""
    baseline = json.loads((DATA / 'aon_source_baseline.json').read_text()) if replace_legacy else {}

    def visit(item):
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, dict):
            return item
        result = {key: visit(child) for key, child in item.items()}
        url = item.get('url')
        if isinstance(url, str):
            key = reference_key(url)
            source = published_sources().get(key)
            if source and (not item.get('source') or item.get('source') == baseline.get(key)):
                result['source'] = source
        return result

    return visit(value)


def catalog_sources(catalog):
    result = {}

    def visit(item):
        if isinstance(item, dict):
            if isinstance(item.get('url'), str) and 'source' in item:
                key = reference_key(item['url'])
                if key:
                    result[key] = item['source']
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(catalog)
    return result


@router.get('/api/reference-sources')
def reference_sources(request: Request, db: Session = Depends(get_db)):
    authenticated(context(request, db))
    urls = request.query_params.getlist('url')
    if len(urls) > 100 or any(len(url) > 2000 for url in urls):
        raise HTTPException(422, 'Request up to 100 reference URLs.')
    record = db.get(RuleCatalog, 1)
    overrides = catalog_sources(record.data) if record else {}
    return {url: overrides.get(reference_key(url), source_for(url)) for url in urls}


def migrate_sources(db):
    from sqlalchemy import select

    for record in db.scalars(select(RuleCatalog).with_for_update()):
        updated = enrich_sources(deepcopy(record.data), replace_legacy=True)
        if updated != record.data:
            record.data = updated
    db.info.pop('rule_catalog', None)

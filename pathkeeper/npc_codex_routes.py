"""Administration and campaign views of the NPC codex."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .catalog_admin import record_for
from .database import get_db
from .models import utcnow
from .npc_codex import CATEGORIES, browse, class_label, codex_entries, entries, make_character
from .npc_codex_editor import SECTIONS, editor_values, parse_entry
from .pf1_data import ABILITIES, ALIGNMENTS
from .rule_catalog import load_catalog
from .security import administrator, audit, context, field, get_campaign, integer, read_form
from .sheet_calculations import SIZE_MODIFIERS
from .ui import redirect, render

router = APIRouter()
ADMIN_CODEX = "/administration/npc-codex"
CAMPAIGN_CODEX = "/campaigns/{campaign_id}/npcs/catalog"


def filter_query(filters):
    return urlencode({key: value for key, value in {"q": filters["search"], **filters["selected"]}.items() if value})


def page_query(filters):
    query = filter_query(filters)
    return f"{query}&page={filters['page']}" if query else f"page={filters['page']}"


def render_codex(ctx, campaign=None, key=None):
    items = codex_entries(load_catalog(ctx.db))
    filters = browse(ctx.request.query_params, items)
    base = CAMPAIGN_CODEX.format(campaign_id=campaign.id) if campaign else ADMIN_CODEX
    entry = items.get(key) if key is not None else None
    if key is not None and entry is None:
        raise HTTPException(404, "NPC codex entry not found.")
    return render(ctx, "npc_codex.html", title=entry["name"] if entry else "NPC Codex", campaign=campaign,
                  base=base, entry=entry, entry_key=key, list_query=page_query(filters), query=filter_query(filters),
                  class_label=class_label, **filters)


@router.get(ADMIN_CODEX)
@router.get(ADMIN_CODEX + "/{key}")
async def admin_codex(request: Request, key: str | None = None, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return render_codex(ctx, key=key)


def render_editor(ctx, key, item, version, values=None, error=None):
    return_url = editor_return_url(ctx)
    response = render(ctx, "npc_codex_edit.html", title=f"Edit {item['name']}", key=key, item=item,
                      values=editor_values(item) if values is None else values, version=version,
                      sections=SECTIONS, categories=CATEGORIES[:-1], abilities=ABILITIES,
                      alignments=ALIGNMENTS, sizes=SIZE_MODIFIERS, error=error,
                      back_url=return_url or f"{ADMIN_CODEX}/{key}")
    if error:
        response.status_code = 422
    return response


def editor_return_url(ctx):
    params = ctx.request.query_params
    if params.get("from") != "list":
        return None
    filters = browse(params, codex_entries(load_catalog(ctx.db)))
    return f"{ADMIN_CODEX}?{page_query(filters)}"


def editable_entry(key, catalog):
    original = entries().get(key)
    if original is None:
        raise HTTPException(404, "NPC codex entry not found.")
    edit = catalog.get("npc_codex_overrides", {}).get(key)
    return (edit["entry"], edit["version"]) if edit else (original, 0)


@router.get(ADMIN_CODEX + "/{key}/edit")
async def edit_codex_npc(key: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    item, version = editable_entry(key, load_catalog(db))
    return render_editor(ctx, key, item, version)


@router.post(ADMIN_CODEX + "/{key}/edit")
async def save_codex_npc(key: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    form = await read_form(ctx)
    record = record_for(ctx, lock=True)
    item, version = editable_entry(key, record.data)
    if integer(form, "version", 0, 2**31 - 1) != version:
        raise HTTPException(409, "This NPC changed while you were editing it. Reload the entry and reapply your changes.")
    try:
        updated = parse_entry(form, item, record.data)
    except HTTPException as error:
        return render_editor(ctx, key, item, version, values=form, error=error.detail)
    overrides = record.data.get("npc_codex_overrides", {})
    record.data = {**record.data, "npc_codex_overrides": {**overrides, key: {"entry": updated, "version": version + 1}}}
    record.updated_by = ctx.user.id
    record.updated_at = utcnow()
    audit(db, ctx.user, "npc_codex.updated", f"Updated {updated['name']} in the NPC Codex.")
    return redirect(ctx, editor_return_url(ctx) or f"{ADMIN_CODEX}/{key}", "NPC Codex entry saved.")


@router.get(CAMPAIGN_CODEX)
@router.get(CAMPAIGN_CODEX + "/{key}")
async def campaign_codex(campaign_id: int, request: Request, key: str | None = None, db: Session = Depends(get_db)):
    ctx = context(request, db)
    campaign = get_campaign(ctx, campaign_id, manage=True)
    return render_codex(ctx, campaign=campaign, key=key)


@router.post(CAMPAIGN_CODEX)
async def add_codex_npc(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    campaign = get_campaign(ctx, campaign_id, manage=True, lock=True)
    form = await read_form(ctx)
    key = field(form, "npc_key", 120)
    catalog = load_catalog(db)
    entry = codex_entries(catalog).get(key)
    if entry is None:
        raise HTTPException(404, "NPC codex entry not found.")
    character = make_character(entry, campaign, catalog)
    db.add(character)
    db.flush()
    audit(db, ctx.user, "campaign.npc_codex_added", f"Added {character.name} to {campaign.name} from the NPC Codex.")
    return redirect(ctx, f"/characters/{character.id}", f"{character.name} added to the campaign.")

"""Administration and campaign views of the NPC codex."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .npc_codex import browse, class_label, entries, make_character
from .rule_catalog import load_catalog
from .security import administrator, audit, context, field, get_campaign, read_form
from .ui import redirect, render

router = APIRouter()
ADMIN_CODEX = "/administration/npc-codex"
CAMPAIGN_CODEX = "/campaigns/{campaign_id}/npcs/catalog"


def render_codex(ctx, campaign=None, key=None):
    filters = browse(ctx.request.query_params)
    base = CAMPAIGN_CODEX.format(campaign_id=campaign.id) if campaign else ADMIN_CODEX
    query = urlencode({"q": filters["search"], "category": filters["category"]})
    entry = entries().get(key) if key is not None else None
    if key is not None and entry is None:
        raise HTTPException(404, "NPC codex entry not found.")
    return render(ctx, "npc_codex.html", title=entry["name"] if entry else "NPC Codex", campaign=campaign,
                  base=base, entry=entry, entry_key=key, query=query, class_label=class_label, **filters)


@router.get(ADMIN_CODEX)
@router.get(ADMIN_CODEX + "/{key}")
async def admin_codex(request: Request, key: str | None = None, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return render_codex(ctx, key=key)


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
    entry = entries().get(key)
    if entry is None:
        raise HTTPException(404, "NPC codex entry not found.")
    character = make_character(entry, campaign, load_catalog(db))
    db.add(character)
    db.flush()
    audit(db, ctx.user, "campaign.npc_codex_added", f"Added {character.name} to {campaign.name} from the NPC Codex.")
    return redirect(ctx, f"/characters/{character.id}", f"{character.name} added to the campaign.")

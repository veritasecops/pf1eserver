import json
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from .advancement import XP_TRACKS, apply_advancement, detach_characters, preserve_xp, track
from .database import commit, get_db
from . import level_up
from .models import Campaign, Character, CharacterDraft, Invitation, Membership, User, utcnow
from .security import (audit, authenticated, can_delete_character, can_manage_campaign, context, digest, email_field,
                       field, get_campaign, get_character, integer, is_member, read_form)
from .ui import redirect, render
from .notifications import application_link, invitation_email
from .pf1_data import ABILITIES, CLASSES, RACES, SKILLS
from .rule_catalog import character_catalog, load_catalog
from .weapons import sheet_weapon_links
from .feature_links import normalized, sheet_ability_blocks, sheet_feature_links
from .armor import sheet_armor_links
from .deluxe_sheet import baseline, parse_sheet, sheet_values, view_context
from .sheet_calculations import calculated_fields, recalculate
from .sheet_formulas import sheet_formulas
from .sheet_feats import removable_rows, remove_feat
from .trait_defenses import trait_defenses
from .equipment_state import equipment_groups, equipped_values, sync_equipped
from .equipment_effects import contributions, persist_effects
from .portraits import DEFAULT_HEADER_BACKGROUND, header_background_url, portrait_url

router = APIRouter()


def campaign_xp_speed(form, default="slow"):
    speed = form.get("xp_speed", default)
    if not isinstance(speed, str) or speed not in XP_TRACKS:
        raise HTTPException(422, "Choose Slow, Medium, or Fast XP advancement.")
    return speed


def campaigns_query(account):
    query = select(Campaign)
    if account.role != "admin":
        query = query.outerjoin(Membership, and_(Membership.campaign_id == Campaign.id, Membership.user_id == account.id))
        query = query.where(or_(Campaign.owner_id == account.id, Membership.user_id.is_not(None)))
    return query


def characters_query(account):
    query = select(Character)
    if account.role == "admin":
        return query
    if account.role == "player":
        return query.where(Character.owner_id == account.id)
    return query.outerjoin(Campaign, Campaign.id == Character.campaign_id).outerjoin(
        Membership, and_(Membership.campaign_id == Character.campaign_id, Membership.user_id == Character.owner_id)).where(
        or_(Character.owner_id == account.id, and_(Campaign.owner_id == account.id, Membership.user_id.is_not(None))))


def verify_version(form, record):
    if integer(form, "version", 1, 2**31 - 1) != record.version:
        raise HTTPException(409, "This record has changed. Reload before saving again.")


@router.get("/")
async def home(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    campaigns = list(db.scalars(campaigns_query(account).order_by(Campaign.id.desc())))
    owned = list(db.scalars(select(Character).where(Character.owner_id == account.id).order_by(Character.name)))
    accessible = db.scalar(select(func.count()).select_from(characters_query(account).subquery()))
    return render(ctx, "dashboard.html", title="Your workspace", campaigns=campaigns[:6], characters=owned[:6],
                  counts={"characters": len(owned), "campaigns": len(campaigns), "managed": sum(c.owner_id == account.id for c in campaigns), "accessible": accessible})


@router.get("/campaigns")
async def campaigns_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    campaigns = db.execute(campaigns_query(account).add_columns(User.name).join(User, User.id == Campaign.owner_id).order_by(Campaign.id.desc())).all()
    return render(ctx, "campaigns.html", title="Campaigns", campaigns=campaigns)


def available_campaign_characters(account):
    query = select(Character).where(Character.campaign_id.is_(None))
    if account.role != "admin":
        query = query.where(Character.owner_id == account.id)
    return query


def campaign_character_options(ctx):
    return ctx.db.execute(
        available_campaign_characters(ctx.user).add_columns(User.name)
        .join(User, User.id == Character.owner_id).order_by(Character.name, Character.id)
    ).all()


def assign_campaign_character(ctx, campaign, form):
    character_id = integer(form, "character_id", 1, 2**63 - 1)
    character = ctx.db.scalar(
        available_campaign_characters(ctx.user).where(Character.id == character_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if character is None:
        raise HTTPException(422, "Choose an available character that is unassigned to a campaign.")
    preserve_xp(character, "slow")
    character.campaign_id = campaign.id
    if character.sheet_data:
        character.sheet_data = {**character.sheet_data, "input": {
            **character.sheet_data["input"], "campaign_id": campaign.id,
        }}
    audit(ctx.db, ctx.user, "campaign.character_added", f"Added {character.name} to {campaign.name}.")


@router.get("/campaigns/new")
async def campaign_new(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    if account.role == "player":
        raise HTTPException(403, "Only Game Masters and Admins can create campaigns.")
    owners = list(db.scalars(select(User).where(User.role.in_(["gm", "admin"]), User.active.is_(True)).order_by(User.name))) if account.role == "admin" else []
    return render(ctx, "campaign_form.html", title="Create campaign", campaign=None, owners=owners, xp_tracks=XP_TRACKS,
                  character_options=campaign_character_options(ctx))


@router.post("/campaigns")
async def campaign_create(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    if account.role == "player":
        raise HTTPException(403, "Only Game Masters and Admins can create campaigns.")
    form = await read_form(ctx)
    owner_id = integer(form, "owner_id", 1, 2**63 - 1) if account.role == "admin" else account.id
    owner = db.get(User, owner_id)
    if not owner or not owner.active or owner.role not in {"gm", "admin"}:
        raise HTTPException(422, "Choose an active Game Master or Admin as owner.")
    campaign = Campaign(xp_speed=campaign_xp_speed(form), owner_id=owner_id, name=field(form, "name"), description=field(form, "description", 20000, False), setting=field(form, "setting", 150, False))
    db.add(campaign)
    if form.get("character_id"):
        db.flush()
        assign_campaign_character(ctx, campaign, form)
    audit(db, account, "campaign.created", f"Created campaign {campaign.name}.")
    commit(db)
    return redirect(ctx, f"/campaigns/{campaign.id}", "Campaign created. You can now invite players.")


@router.get("/campaigns/{campaign_id}")
async def campaign_page(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    campaign = get_campaign(ctx, campaign_id)
    manage = can_manage_campaign(ctx.user, campaign)
    characters = db.execute(characters_query(ctx.user).where(Character.campaign_id == campaign_id).add_columns(User.name).join(User, User.id == Character.owner_id).order_by(Character.name)).all()
    members = db.execute(select(User, Membership.joined_at).join(Membership, Membership.user_id == User.id).where(Membership.campaign_id == campaign_id).order_by(User.name)).all()
    invitations = list(db.scalars(select(Invitation).where(Invitation.campaign_id == campaign_id).order_by(Invitation.id.desc()).limit(50))) if manage else []
    owner = db.get(User, campaign.owner_id)
    return render(ctx, "campaign.html", title=campaign.name, campaign=campaign, manage=manage,
                  characters=characters, members=members, invitations=invitations, owner=owner, now=utcnow(),
                  character_options=campaign_character_options(ctx))


@router.post("/campaigns/{campaign_id}/characters")
async def campaign_add_character(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    campaign = get_campaign(ctx, campaign_id, lock=True)
    assign_campaign_character(ctx, campaign, form)
    return redirect(ctx, f"/campaigns/{campaign.id}", "Character added to the campaign.")


@router.get("/campaigns/{campaign_id}/edit")
async def campaign_edit(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    campaign = get_campaign(ctx, campaign_id, manage=True)
    owners = list(db.scalars(select(User).where(User.role.in_(["gm", "admin"]), User.active.is_(True)).order_by(User.name))) if ctx.user.role == "admin" else []
    return render(ctx, "campaign_form.html", title="Edit campaign", campaign=campaign, owners=owners, xp_tracks=XP_TRACKS)


@router.post("/campaigns/{campaign_id}")
async def campaign_update(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    campaign = get_campaign(ctx, campaign_id, manage=True, lock=True)
    verify_version(form, campaign)
    if ctx.user.role == "admin":
        owner = db.get(User, integer(form, "owner_id", 1, 2**63 - 1))
        if not owner or not owner.active or owner.role not in {"gm", "admin"}:
            raise HTTPException(422, "Choose an active Game Master or Admin as owner.")
        campaign.owner_id = owner.id
    speed = campaign_xp_speed(form, campaign.xp_speed)
    if speed != campaign.xp_speed:
        for character in db.scalars(select(Character).where(Character.campaign_id == campaign.id).order_by(Character.id).with_for_update()):
            preserve_xp(character, campaign.xp_speed)
            character.version += 1
        campaign.xp_speed = speed
    campaign.name = field(form, "name")
    campaign.setting = field(form, "setting", 150, False)
    campaign.description = field(form, "description", 20000, False)
    audit(db, ctx.user, "campaign.updated", f"Updated campaign {campaign.name}.")
    return redirect(ctx, f"/campaigns/{campaign.id}", "Campaign saved.")


@router.post("/campaigns/{campaign_id}/delete")
async def campaign_delete(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    campaign = get_campaign(ctx, campaign_id, manage=True, lock=True)
    verify_version(form, campaign)
    if field(form, "confirm_name") != campaign.name:
        raise HTTPException(422, "Type the campaign's name to confirm deletion.")
    audit(db, ctx.user, "campaign.deleted", f"Deleted campaign {campaign.name}. Characters were detached, not deleted.")
    detach_characters(db, campaign)
    db.delete(campaign)
    return redirect(ctx, "/campaigns", "Campaign deleted. Its characters remain with their owners.")


@router.post("/campaigns/{campaign_id}/invitations")
async def invite_create(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    campaign = get_campaign(ctx, campaign_id, manage=True)
    form = await read_form(ctx)
    email = email_field(form)
    from .security import throttle
    throttle("campaign-invitation", str(ctx.user.id), 20, 60)
    token = secrets.token_urlsafe(32)
    invitation = Invitation(campaign_id=campaign.id, created_by=ctx.user.id, email=email, token_hash=digest(token), expires_at=utcnow() + timedelta(days=7))
    db.add(invitation)
    audit(db, ctx.user, "invitation.created", f"Created a seven-day invitation for {email} to {campaign.name}.")
    db.flush()
    emailed = invitation_email(db, invitation, campaign, token, ctx.user)
    commit(db)
    return render(ctx, "invitation_created.html", title="Invitation ready", campaign=campaign, invitation=invitation,
                  invitation_path=f"/join/{token}", invitation_url=application_link(db, f"/join/{token}"), emailed=emailed)


@router.post("/invitations/{invitation_id}/revoke")
async def invite_revoke(invitation_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx)
    await read_form(ctx)
    invitation = db.get(Invitation, invitation_id)
    if not invitation:
        raise HTTPException(404, "Invitation not found.")
    campaign = get_campaign(ctx, invitation.campaign_id, manage=True)
    invitation.revoked = True
    audit(db, ctx.user, "invitation.revoked", f"Revoked an invitation for {invitation.email} to {campaign.name}.")
    return redirect(ctx, f"/campaigns/{campaign.id}", "Invitation revoked.")


def valid_invitation(db, token, lock=False):
    statement = select(Invitation).where(Invitation.token_hash == digest(token))
    if lock:
        statement = statement.with_for_update()
    invitation = db.scalar(statement)
    if not invitation or invitation.revoked or invitation.accepted_at or invitation.expires_at <= utcnow():
        raise HTTPException(404, "This invitation has expired, was revoked, or has already been used.")
    return invitation


@router.get("/join/{token}")
async def invitation_page(token: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    # Validate only after authentication, so invitation metadata remains private.
    ctx.session.next_path = f"/join/{token}" if len(token) <= 100 else "/"
    commit(db)
    account = authenticated(ctx)
    invitation = valid_invitation(db, token)
    if account.email != invitation.email:
        raise HTTPException(403, "This invitation belongs to a different email address. Sign in with the invited account.")
    campaign = db.get(Campaign, invitation.campaign_id)
    return render(ctx, "invitation.html", title="Join a campaign", campaign=campaign, invitation=invitation, token=token)


@router.post("/join/{token}")
async def invitation_accept(token: str, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    await read_form(ctx)
    invitation = valid_invitation(db, token, lock=True)
    if account.email != invitation.email:
        raise HTTPException(403, "This invitation belongs to a different email address.")
    if not db.get(Membership, (invitation.campaign_id, account.id)):
        db.add(Membership(campaign_id=invitation.campaign_id, user_id=account.id))
    invitation.accepted_by = account.id
    invitation.accepted_at = utcnow()
    ctx.session.next_path = "/"
    audit(db, account, "invitation.accepted", "Joined a campaign through an email-bound invitation.")
    return redirect(ctx, f"/campaigns/{invitation.campaign_id}", "You have joined the campaign. Assign a character when you are ready.")


@router.post("/campaigns/{campaign_id}/members/{user_id}/remove")
async def member_remove(campaign_id: int, user_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    await read_form(ctx)
    campaign = get_campaign(ctx, campaign_id, manage=True, lock=True)
    if user_id == campaign.owner_id:
        raise HTTPException(422, "The campaign owner cannot be removed.")
    db.execute(delete(Membership).where(Membership.campaign_id == campaign_id, Membership.user_id == user_id))
    detach_characters(db, campaign, user_id)
    audit(db, ctx.user, "member.removed", "Removed a campaign member and detached their characters.")
    return redirect(ctx, f"/campaigns/{campaign.id}", "Member removed. Their characters remain in their account.")


@router.get("/characters")
async def characters_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    account = authenticated(ctx)
    query = characters_query(account).add_columns(User.name, Campaign.name).join(User, User.id == Character.owner_id)
    # characters_query already joins Campaign for GMs.
    if account.role != "gm":
        query = query.outerjoin(Campaign, Campaign.id == Character.campaign_id)
    search = request.query_params.get("q", "")[:100].strip()
    if search:
        query = query.where(or_(Character.name.ilike(f"%{search}%"), Character.class_name.ilike(f"%{search}%")))
    characters = db.execute(query.order_by(Character.name)).all()
    drafts = list(db.scalars(select(CharacterDraft).where(
        CharacterDraft.actor_id == account.id, CharacterDraft.mode == "create",
        CharacterDraft.finalized_at.is_(None)).order_by(CharacterDraft.updated_at.desc(), CharacterDraft.id)))
    if search:
        term = search.casefold()
        drafts = [draft for draft in drafts if term in (draft.data.get("name") or "Unnamed character").casefold()
                  or term in CLASSES.get(draft.data.get("class_id"), {}).get("name", "Class unassigned").casefold()]
    return render(ctx, "characters.html", title="Characters", characters=characters, drafts=drafts,
                  draft_races=RACES, draft_classes=CLASSES, search=search)


def character_options(ctx, include_owners=True):
    campaigns = list(ctx.db.scalars(campaigns_query(ctx.user).order_by(Campaign.name)))
    if include_owners and ctx.user.role == "admin":
        owners = list(ctx.db.scalars(select(User).order_by(User.name)))
    else:
        owners = []
    return {"campaigns": campaigns, "owners": owners}


def character_values(ctx, form, existing=None):
    if existing and ctx.user.role == "admin":
        owner_id = integer(form, "owner_id", 1, 2**63 - 1)
    else:
        owner_id = existing.owner_id if existing else ctx.user.id
    if not ctx.db.get(User, owner_id):
        raise HTTPException(422, "Choose a valid owner.")
    raw_campaign = form.get("campaign_id", "")
    campaign_id = integer(form, "campaign_id", 1, 2**63 - 1) if raw_campaign else None
    if existing and ctx.user.role != "admin" and existing.owner_id != ctx.user.id and campaign_id != existing.campaign_id:
        raise HTTPException(403, "Only the character's owner or an Admin can move it between campaigns.")
    if campaign_id:
        campaign = ctx.db.get(Campaign, campaign_id, with_for_update=True, populate_existing=True)
        if not campaign or ctx.user.role != "admin" and not is_member(ctx.db, ctx.user, campaign):
            raise HTTPException(404, "Campaign not found.")
        if ctx.user.role != "admin" and owner_id == ctx.user.id and not is_member(ctx.db, ctx.user, campaign):
            raise HTTPException(403, "Join the campaign before assigning a character.")
    return {"name": field(form, "name"), "owner_id": owner_id, "campaign_id": campaign_id,
            "ancestry": field(form, "ancestry", 100, False), "class_name": field(form, "class_name", 100, False),
            "level": existing.level if existing else integer(form, "level", 1, 20), "notes": field(form, "notes", 20000, False)}


@router.post("/characters")
async def character_create(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx)
    form = await read_form(ctx)
    character = Character(**character_values(ctx, form))
    speed = track(db.get(Campaign, character.campaign_id)) if character.campaign_id else "slow"
    preserve_xp(character, speed)
    db.add(character)
    audit(db, ctx.user, "character.created", f"Created character {character.name}.")
    commit(db)
    return redirect(ctx, f"/characters/{character.id}", "Character created.")


@router.get("/characters/{character_id}")
async def character_page(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    return render_character(ctx, character)


def render_character(ctx, character, values=None, errors=()):
    owner = ctx.db.get(User, character.owner_id)
    campaign = ctx.db.get(Campaign, character.campaign_id) if character.campaign_id else None
    gm = ctx.db.get(User, campaign.owner_id) if campaign else None
    if values is None:
        values = sheet_values(character, owner, campaign, gm)
    catalog = load_catalog(ctx.db)
    ability_blocks = sheet_ability_blocks(values, character, catalog)
    response = render(ctx, "character.html", title=character.name, character=character, owner=owner, campaign=campaign,
                      can_delete=can_delete_character(ctx.user, character),
                      portrait_url=portrait_url(ctx.db,character),portrait_endpoint=f"/characters/{character.id}/portrait",
                      header_background_url=header_background_url(ctx.db,character),default_header_background=DEFAULT_HEADER_BACKGROUND,
                      can_edit_header_background=ctx.user.id == character.owner_id,
                      can_level_up=ctx.user.id == character.owner_id and level_up.available(character, campaign, catalog),
                      advancement_history=(character.play_data or {}).get("advancement_history", []),
                      armor_links=sheet_armor_links(values,character,catalog),
                      weapon_links=sheet_weapon_links(values,character,catalog),
                      feature_links=sheet_feature_links(values, character, catalog),
                      ability_blocks=ability_blocks,
                      removable_feats=removable_rows(character, values, catalog, ability_blocks),
                      trait_defenses=trait_defenses(character, values),
                      **view_context(character, owner, campaign, gm, values, errors,deity_catalog=catalog.get('deities',{})))
    if errors:
        response.status_code = 422
    return response


async def read_play_sheet(ctx, character, form=None):
    db = ctx.db
    if form is None:
        form = await read_form(ctx, max_fields=1024)
    verify_version(form, character)
    owner = db.get(User, character.owner_id)
    campaign = db.get(Campaign, character.campaign_id) if character.campaign_id else None
    gm = db.get(User, campaign.owner_id) if campaign else None
    current = sheet_values(character, owner, campaign, gm)
    locked = calculated_fields(character, current)
    values, errors = parse_sheet(form, {key:current[key] for key in locked}, character_catalog(character),load_catalog(db).get('deities',{}),current.get('deity',''))
    if not errors:
        apply_advancement(values, track(campaign))
        sync_equipped(character,values,current)
        from .equipment_effects import validate_armor
        validate_armor(character, values)
        encoded = ctx.request.headers.get('x-equipment-effects')
        keep = [key for key in ('ac.dex', 'speed.armor') if not encoded and values[key] != current[key]]
        if encoded:
            from .equipment_effects import number
            from decimal import Decimal
            try:
                shown = json.loads(encoded)
                actual = contributions(character, current)
                if not isinstance(shown, dict) or set(shown) != set(actual): raise ValueError
                for key, amount in shown.items():
                    value = Decimal(str(amount))
                    if not value.is_finite() or abs(value) > 1000000000: raise ValueError
                    values[key] = format(number(values[key]) - value + number(actual[key]), 'f')
            except (ValueError, TypeError, ArithmeticError):
                raise HTTPException(422, 'Reload the sheet to refresh equipment modifiers.') from None
        recalculate(character, values, equipment_previous=contributions(character, current), equipment_keep=keep)
    return values, errors, baseline(character, owner, campaign, gm)


@router.post("/characters/{character_id}/play-sheet/calculate")
async def character_play_sheet_calculate(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    values, errors, _ = await read_play_sheet(ctx, character)
    if errors:
        return JSONResponse({"errors":errors},status_code=422)
    locked = calculated_fields(character, values)
    return JSONResponse({"values":{key:values[key] for key in locked},"readonly":sorted(locked),"formulas":sheet_formulas(character,values),
                         "trait_defenses":trait_defenses(character,values)},
                        headers={"Cache-Control":"no-store"})


@router.post("/characters/{character_id}/play-sheet")
async def character_play_sheet(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    autosave = 'application/json' in request.headers.get('accept','')
    form = await read_form(ctx, max_fields=1024)
    save_id = request.headers.get('x-sheet-save-id','')
    fingerprint = None
    if autosave:
        if not re.fullmatch(r'[a-f0-9]{32}',save_id):
            raise HTTPException(422,'Enter a valid automatic save identifier.')
        # Serialize retries as well as writes, including a retry whose first
        # response was lost after the transaction committed.
        db.refresh(character,with_for_update=True)
        character = get_character(ctx,character_id)
        fingerprint = digest(json.dumps([sorted((key,value) for key,value in form.multi_items() if key != 'csrf'), request.headers.get('x-equipment-effects','')]))
        previous = (character.play_data or {}).get('autosave',{})
        if previous.get('id') == save_id and previous.get('actor') == ctx.user.id:
            if previous.get('version') != character.version:
                raise HTTPException(409,'The character changed after this automatic save.')
            if previous.get('fingerprint') != fingerprint:
                raise HTTPException(409,'This save identifier was already used for different changes.')
            return autosave_response(ctx,character)
    values, errors, base = await read_play_sheet(ctx, character, form)
    if errors:
        if autosave:
            return JSONResponse({'errors':errors},status_code=422)
        return render_character(ctx, character, values, errors)
    # Store only overrides so untouched wizard values continue to follow their source.
    core = {"name", "ancestry", "class_name", "level", "notes"}
    metadata = {key:character.play_data[key] for key in ("weapon_inventory","weapon_purchase","equipment_disposal","advancement_history") if key in (character.play_data or {})}
    character.play_data = {"calculation_version":1, **metadata, **{key:value for key,value in values.items()
                           if key not in core | {"player", "next_level"} and value != base[key]}, **persist_effects(character, values), "experience": values["experience"]}
    for key in core - {"level"}:
        setattr(character, key, values[key])
    if character.sheet_data:
        character.sheet_data = {**character.sheet_data, "input":{**character.sheet_data["input"],
                                "name":character.name, "notes":character.notes}}
    if autosave:
        character.play_data = {**character.play_data,'autosave':{'id':save_id,'actor':ctx.user.id,'fingerprint':fingerprint,'version':character.version+1}}
    audit(db, ctx.user, "character.play_sheet_saved", f"Updated the deluxe play sheet for {character.name}.")
    if autosave:
        commit(db)
        return autosave_response(ctx,character)
    return redirect(ctx, f"/characters/{character.id}", "Character sheet saved.")


def autosave_response(ctx, character):
    owner = ctx.db.get(User,character.owner_id)
    campaign = ctx.db.get(Campaign,character.campaign_id) if character.campaign_id else None
    gm = ctx.db.get(User,campaign.owner_id) if campaign else None
    values = sheet_values(character,owner,campaign,gm)
    locked = calculated_fields(character,values)
    return JSONResponse({'version':character.version,'name':character.name,
                         'can_level_up':ctx.user.id == character.owner_id and level_up.available(character, campaign, load_catalog(ctx.db)),'equipment_groups':equipment_groups(character,values),'equipment_state':equipped_values(values),
                         'values':{key:values[key] for key in locked},'readonly':sorted(locked),'formulas':sheet_formulas(character,values),
                         'equipment_fields':{key:values[key] for key in contributions(character,values)}, 'equipment_effects':contributions(character,values),
                         'armor_links':sheet_armor_links(values,character,load_catalog(ctx.db)),
                         'weapon_links':sheet_weapon_links(values,character,load_catalog(ctx.db)),
                         'feature_links':sheet_feature_links(values,character,load_catalog(ctx.db)),
                         'trait_defenses':trait_defenses(character,values)},
                        headers={'Cache-Control':'no-store'})


def sheet_feat_rules(ctx, character):
    owner = ctx.db.get(User, character.owner_id)
    campaign = ctx.db.get(Campaign, character.campaign_id) if character.campaign_id else None
    values = sheet_values(character, owner, campaign)
    return values, level_up.sheet_feat_context(character, load_catalog(ctx.db), values)


@router.get("/characters/{character_id}/features")
async def character_feature_options(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    _, rules = sheet_feat_rules(ctx, character)
    return JSONResponse({"options": {"feat": level_up.sheet_feat_options(rules)}, "targets": rules["feat_targets"]},
                        headers={"Cache-Control": "no-store"})


@router.post("/characters/{character_id}/features")
async def character_feature_add(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    character = get_character(ctx, character_id)
    db.refresh(character, with_for_update=True)
    get_character(ctx, character_id)
    verify_version(form, character)
    kind = field(form, "kind", 10)
    name = field(form, "feature", 150)
    if kind != "feat":
        raise HTTPException(422, "Choose an available feat.")
    target = field(form, "target", 100, required=False)
    values, rules = sheet_feat_rules(ctx, character)
    errors = []
    level_up.validate_feats(rules, [{"feature": "feat", "choice": name, "target": target}], "", errors)
    if errors:
        raise HTTPException(422, errors[0])
    if choice := rules["feat_catalog"][name].get("choice"):
        name = f"{name} ({rules['feat_targets'][choice][target]})"
    keys = [f"feature.{row}" for row in range(56)]
    if any(normalized(values[key]) == normalized(name) for key in keys):
        raise HTTPException(409, "That entry is already on the character sheet.")
    key = next((key for key in keys if not values[key]), None)
    if key is None:
        raise HTTPException(422, "The feats and abilities section is full.")
    character.play_data = {**(character.play_data or {}), key: name}
    audit(db, ctx.user, "character.feature_added", f"Added {name} to {character.name}.")
    commit(db)
    return JSONResponse({"location": f"/characters/{character.id}#abilities-skills"}, status_code=201)



@router.post("/characters/{character_id}/features/remove")
async def character_feature_remove(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    form = await read_form(ctx)
    character = get_character(ctx, character_id)
    db.refresh(character, with_for_update=True)
    get_character(ctx, character_id)
    verify_version(form, character)
    row = integer(form, "row", 0, 55)
    owner = db.get(User, character.owner_id)
    campaign = db.get(Campaign, character.campaign_id) if character.campaign_id else None
    values = sheet_values(character, owner, campaign)
    catalog = load_catalog(db)
    name = removable_rows(character, values, catalog, sheet_ability_blocks(values, character, catalog)).get(row)
    if not name:
        raise HTTPException(422, "Choose a removable feat.")
    remove_feat(character, values, catalog, row, name)
    audit(db, ctx.user, "character.feat_removed", f"Removed {name} from {character.name}.")
    commit(db)
    return JSONResponse({"location": f"/characters/{character.id}#abilities-skills"})



def level_up_character(ctx, character_id):
    character = get_character(ctx, character_id)
    if character.owner_id != ctx.user.id:
        raise HTTPException(403, "Only the character's owner can advance their level.")
    return character


def render_level_up(ctx, character, advancement, form=None, errors=()):
    response = render(ctx, "level_up.html", title="Level up", character=character, advancement=advancement,
                      abilities=ABILITIES, class_index=level_up.CLASS_INDEX,
                      feat_options=level_up.feat_options(advancement) if advancement else {},
                      submitted=form or {}, errors=errors)
    if errors:
        response.status_code = 422
    return response


@router.get("/characters/{character_id}/level-up")
async def character_level_up_page(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = level_up_character(ctx, character_id)
    return render_level_up(ctx, character, level_up.plan(ctx, character))


@router.post("/characters/{character_id}/level-up")
async def character_level_up_submit(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = level_up_character(ctx, character_id)
    form = await read_form(ctx, max_fields=200)
    campaign_id = character.campaign_id
    if campaign_id:
        db.get(Campaign, campaign_id, with_for_update=True, populate_existing=True)
    db.refresh(character, with_for_update=True)
    verify_version(form, character)
    if character.campaign_id != campaign_id or character.owner_id != ctx.user.id:
        raise HTTPException(409, "The character's campaign or owner changed. Reload the wizard.")
    advancement = level_up.plan(ctx, character)
    if not advancement or integer(form, "target", 2, 20) != advancement["target"]:
        raise HTTPException(409, "The character is no longer eligible for this level. Reload the wizard.")
    errors = level_up.submit(character, advancement, form)
    if errors:
        return render_level_up(ctx, character, advancement, form, errors)
    audit(db, ctx.user, "character.level_up", f"{character.name} advanced to level {character.level}.")
    location = f"/characters/{character.id}"
    if character.level < advancement["eligible_level"]:
        location += "/level-up"
    return redirect(ctx, location, f"Advanced to level {character.level}.")


@router.get("/characters/{character_id}/edit")
async def character_edit(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    return render(ctx, "character_form.html", title="Edit character", character=character, **character_options(ctx))


@router.post("/characters/{character_id}")
async def character_update(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    form = await read_form(ctx)
    verify_version(form, character)
    values = character_values(ctx, form, character)
    if (character.play_data or {}).get("advancement_history") and values["class_name"] != character.class_name:
        raise HTTPException(422, "The class is fixed after completing a level-up wizard.")
    if character.sheet_data and any(values[key] != getattr(character,key) for key in ("ancestry","class_name")):
        raise HTTPException(422,"Use Edit creation sheet to change race or class.")
    old_speed = track(db.get(Campaign, character.campaign_id)) if character.campaign_id else "slow"
    for key, value in values.items():
        setattr(character, key, value)
    preserve_xp(character, old_speed)
    if character.sheet_data:
        character.sheet_data = {**character.sheet_data,"input":{**character.sheet_data["input"],"name":character.name,
                                "notes":character.notes,"owner_id":character.owner_id,"campaign_id":character.campaign_id}}
    audit(db, ctx.user, "character.updated", f"Updated character {character.name}.")
    return redirect(ctx, f"/characters/{character.id}", "Character saved.")


@router.post("/characters/{character_id}/delete")
async def character_delete(character_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    character = get_character(ctx, character_id)
    if not can_delete_character(ctx.user, character):
        raise HTTPException(403, "Only the character's owner or an Admin can delete it.")
    form = await read_form(ctx)
    verify_version(form, character)
    if field(form, "confirm_name") != character.name:
        raise HTTPException(422, "Type the character's name to confirm deletion.")
    audit(db, ctx.user, "character.deleted", f"Deleted character {character.name}.")
    db.delete(character)
    return redirect(ctx, "/characters", "Character permanently deleted.")

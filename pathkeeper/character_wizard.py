import json
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .character_rules import calculate, clean, defaults
from .database import commit, get_db
from .models import Character, CharacterDraft, DiceRoll, utcnow
from .pf1_data import ABILITIES, ALIGNMENTS, CLASSES, EQUIPMENT, FEATS, MONK_BONUS, OUTLINE, POINT_COST, RACES, SKILLS, SPELL_SUGGESTIONS, STEPS
from .security import audit, authenticated, context, get_campaign, get_character, integer, read_form, throttle
from .ui import redirect, render
from .workspace import character_options, character_values
from .portraits import image_response, portrait_url, uploaded_portrait

router = APIRouter()
DICE = (4,6,8,10,12,20,100)


def get_draft(ctx, draft_id, lock=False):
    authenticated(ctx)
    query = select(CharacterDraft).where(CharacterDraft.id == draft_id)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    draft = ctx.db.scalar(query)
    if not draft or draft.actor_id != ctx.user.id:
        raise HTTPException(404, "Character draft not found.")
    if draft.mode == "edit":
        if not draft.editing_id: raise HTTPException(404, "The character being edited was deleted.")
        get_character(ctx, draft.editing_id)
    return draft


def roll_history(db, draft_id):
    recent = list(db.scalars(select(DiceRoll).where(DiceRoll.draft_id == draft_id).order_by(DiceRoll.created_at.desc()).limit(300)))
    draft = db.get(CharacterDraft,draft_id)
    selected = {draft.data.get("ability_roll"),draft.data.get("wealth_roll")} - {None,""}
    known = {roll.id for roll in recent}
    if selected-known:
        recent += list(db.scalars(select(DiceRoll).where(DiceRoll.draft_id == draft_id,DiceRoll.id.in_(selected-known))))
    return {roll.id:{"id":roll.id,"purpose":roll.purpose,"result":roll.result,"created_at":roll.created_at.isoformat()+"Z"}
            for roll in sorted(recent,key=lambda roll:(roll.created_at,roll.id))}


def display_wizard(ctx, draft):
    options = character_options(ctx,include_owners=False)
    rolls = roll_history(ctx.db, draft.id)
    data = {**draft.data,"owner_id":ctx.user.id} if draft.mode == "create" else draft.data
    image_url = portrait_url(ctx.db,draft)
    boot = {"portrait_url":image_url,"draft_id":draft.id,"version":draft.version,"data":data,"step":draft.step if draft.step in STEPS else next(iter(STEPS)),"rolls":list(rolls.values()),
            "computed":calculate(data,rolls),"mode":draft.mode,"role":ctx.user.role,"user_id":ctx.user.id,
            "steps":STEPS,"step_order":list(STEPS),"abilities":ABILITIES,"ability_order":list(ABILITIES),"races":RACES,
            "classes":CLASSES,"skills":SKILLS,"feats":FEATS,"equipment":EQUIPMENT,"alignments":ALIGNMENTS,
            "point_cost":POINT_COST,"spell_suggestions":SPELL_SUGGESTIONS,"monk_bonus":MONK_BONUS,
            "campaigns":[{"id":campaign.id,"name":campaign.name} for campaign in options["campaigns"]]}
    return render(ctx,"character_wizard.html",title="Character creation",draft=draft,boot=boot,outline=OUTLINE,
                  portrait_url=image_url,portrait_endpoint=f"/api/character-drafts/{draft.id}/portrait")


@router.get("/characters/new")
async def start(request: Request, db: Session = Depends(get_db)):
    ctx = context(request,db)
    account = authenticated(ctx)
    data = defaults(account.id)
    if request.query_params.get("campaign_id"):
        data["campaign_id"] = get_campaign(ctx,integer(request.query_params,"campaign_id",1,2**63-1)).id
    draft = CharacterDraft(id=secrets.token_hex(16),actor_id=account.id,data=data)
    db.add(draft)
    return redirect(ctx,f"/characters/drafts/{draft.id}")


@router.get("/characters/drafts/{draft_id}")
async def resume(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id)
    if draft.finalized_at:
        if not draft.completed_id:
            raise HTTPException(404,"The completed character was deleted.")
        get_character(ctx,draft.completed_id)
        return redirect(ctx,f"/characters/{draft.completed_id}")
    return display_wizard(ctx,draft)


@router.get("/characters/{character_id}/sheet/edit")
async def edit_sheet(character_id: int,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    character = get_character(ctx,character_id)
    if not character.sheet_data or character.level != 1:
        raise HTTPException(422,"This wizard edits first-level creation sheets. Use the basic editor for legacy or higher-level records.")
    draft = db.scalar(select(CharacterDraft).where(CharacterDraft.actor_id == ctx.user.id,CharacterDraft.editing_id == character.id,CharacterDraft.finalized_at.is_(None)).order_by(CharacterDraft.updated_at.desc()).limit(1))
    if not draft:
        data = dict(character.sheet_data["input"])
        data.update(name=character.name,notes=character.notes,owner_id=character.owner_id,campaign_id=character.campaign_id)
        draft = CharacterDraft(id=secrets.token_hex(16),actor_id=ctx.user.id,mode="edit",editing_id=character.id,
                               existing_version=character.version,data=data,portrait=character.portrait)
        db.add(draft)
        db.flush()
        # Preserve provenance by copying only the original sheet's dice records.
        mapping = {}
        for original in character.sheet_data.get("rolls",[]):
            new_id = secrets.token_hex(16)
            mapping[original["id"]] = new_id
            db.add(DiceRoll(id=new_id,draft_id=draft.id,actor_id=ctx.user.id,request_id=secrets.token_hex(16),purpose=original["purpose"],result=original["result"]))
        draft.data = {**draft.data,"ability_roll":mapping.get(data["ability_roll"],""),"wealth_roll":mapping.get(data["wealth_roll"],"")}
        commit(db)
    return display_wizard(ctx,draft)


async def saved_form(ctx,draft):
    if draft.finalized_at: raise HTTPException(409,"This draft has already been finalized.")
    form = await read_form(ctx)
    if integer(form,"version",1,2**31-1) != draft.version:
        raise HTTPException(409,"This draft changed in another window. Reload to continue with the latest version.")
    try: payload = json.loads(str(form.get("payload","")))
    except (ValueError,TypeError): raise HTTPException(422,"The character draft could not be read.") from None
    if draft.mode == "create" and isinstance(payload,dict):
        payload["owner_id"] = ctx.user.id
    return form,clean(payload,ctx.user.id)


@router.post("/api/character-drafts/{draft_id}/save")
async def save(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id,True)
    form,data = await saved_form(ctx,draft)
    draft.data,draft.step,draft.updated_at = data,integer(form,"step",0,max(STEPS)) or next(iter(STEPS)),utcnow()
    commit(db)
    return {"version":draft.version,"computed":calculate(data,roll_history(db,draft.id))}


@router.post("/api/character-drafts/{draft_id}/roll")
async def roll(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id,True)
    if draft.finalized_at: raise HTTPException(409,"This draft has already been finalized.")
    form = await read_form(ctx)
    key = str(form.get("request_id",""))
    if not re.fullmatch(r"[a-f0-9]{32}",key): raise HTTPException(422,"Enter a valid roll request identifier.")
    existing = db.scalar(select(DiceRoll).where(DiceRoll.draft_id == draft.id,DiceRoll.request_id == key))
    if existing: return {"id":existing.id,"purpose":existing.purpose,"result":existing.result}
    throttle("wizard-dice",str(ctx.user.id),120,15)
    purpose = str(form.get("purpose","free"))
    if purpose == "ability":
        method = str(form.get("method","standard"))
        if method not in {"standard","classic","heroic"}: raise HTTPException(422,"Choose a supported rolling method.")
        groups = []
        for _ in range(6):
            dice = [secrets.randbelow(6)+1 for _ in range({"standard":4,"classic":3,"heroic":2}[method])]
            dropped = dice.index(min(dice)) if method == "standard" else None
            kept = [value for index,value in enumerate(dice) if index != dropped]
            groups.append({"dice":dice,"dropped":dropped,"total":sum(kept)+(6 if method == "heroic" else 0)})
        result = {"method":method,"groups":groups,"sides":6}
    elif purpose == "wealth":
        class_id = str(form.get("class_id",""))
        if class_id not in CLASSES: raise HTTPException(422,"Choose a class before rolling wealth.")
        dice = [secrets.randbelow(6)+1 for _ in range(CLASSES[class_id]["wealth_dice"])]
        result = {"dice":dice,"sides":6,"class_id":class_id,"total":sum(dice)*10,"gold_cp":sum(dice)*1000,"modifier":0}
    elif purpose == "free":
        sides,count,modifier = integer(form,"sides",4,100),integer(form,"count",1,20),integer(form,"modifier",-1000,1000)
        if sides not in DICE: raise HTTPException(422,"Choose d4, d6, d8, d10, d12, d20, or d100.")
        values = [secrets.randbelow(sides)+1 for _ in range(count)]
        result = {"dice":values,"sides":sides,"total":sum(values)+modifier,"modifier":modifier}
        if sides == 100: result["percentile"] = [{"tens":value//10*10 if value != 100 else 0,"ones":value%10} for value in values]
    else: raise HTTPException(422,"Choose a supported roll purpose.")
    record = DiceRoll(id=secrets.token_hex(16),draft_id=draft.id,actor_id=ctx.user.id,request_id=key,purpose=purpose,result=result)
    db.add(record)
    commit(db)
    return {"id":record.id,"purpose":purpose,"result":result}


@router.post("/api/character-drafts/{draft_id}/finish")
async def finish(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id,True)
    form = await read_form(ctx)
    if draft.finalized_at:
        if not draft.completed_id: raise HTTPException(409,"The completed character was deleted.")
        get_character(ctx,draft.completed_id)
        return {"location":f"/characters/{draft.completed_id}"}
    if integer(form,"version",1,2**31-1) != draft.version: raise HTTPException(409,"This draft changed. Reload before creating the character.")
    rolls = roll_history(db,draft.id)
    data = clean(draft.data,ctx.user.id)
    computed = calculate(data,rolls)
    if computed["errors"]: return JSONResponse({"detail":"Complete the highlighted steps.","errors":computed["errors"]},422)
    existing = get_character(ctx,draft.editing_id) if draft.mode == "edit" else None
    if existing and existing.version != draft.existing_version: raise HTTPException(409,"The character changed after this draft began. Start a fresh editing draft.")
    values = character_values(ctx,{"name":data["name"],"owner_id":str(data["owner_id"]),"campaign_id":str(data["campaign_id"] or ""),
                                  "ancestry":RACES[data["race"]]["name"],"class_name":CLASSES[data["class_id"]]["name"],"level":"1","notes":data["notes"]},existing)
    data["owner_id"],data["campaign_id"] = values["owner_id"],values["campaign_id"]
    character = existing or Character(**values)
    if existing:
        for key,value in values.items(): setattr(character,key,value)
    active_rolls = set()
    if data["method"] in {"standard","classic","heroic"}: active_rolls.add(data["ability_roll"])
    if data["wealth_method"] == "rolled": active_rolls.add(data["wealth_roll"])
    selected = [item for key,item in rolls.items() if key in active_rolls]
    if not existing or draft.portrait_changed:
        character.portrait = draft.portrait
    draft.portrait = None
    character.sheet_data = {"schema":1,"input":data,"computed":computed,"rolls":selected,"source":OUTLINE}
    db.add(character)
    db.flush()
    draft.finalized_at,draft.completed_id,draft.updated_at = utcnow(),character.id,utcnow()
    audit(db,ctx.user,"character.wizard_saved",f"{'Updated' if existing else 'Created'} {character.name} through the first-level creation wizard.")
    commit(db)
    return {"location":f"/characters/{character.id}"}


@router.post("/api/character-drafts/{draft_id}/discard")
async def discard(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id,True)
    await read_form(ctx)
    if draft.finalized_at: raise HTTPException(409,"A completed character cannot be discarded as a draft.")
    db.delete(draft)
    commit(db)
    return {"location":"/characters"}


@router.get('/api/character-drafts/{draft_id}/portrait')
async def draft_portrait(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id)
    if draft.finalized_at and draft.completed_id:
        character = get_character(ctx,draft.completed_id)
        return image_response(character.portrait)
    return image_response(draft.portrait)


@router.post('/api/character-drafts/{draft_id}/portrait')
async def draft_portrait_upload(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    get_draft(ctx,draft_id)
    content = await uploaded_portrait(ctx)
    draft = get_draft(ctx,draft_id,True)
    if draft.finalized_at: raise HTTPException(409,'This draft has already been finalized.')
    db.execute(update(CharacterDraft).where(CharacterDraft.id == draft.id).values(portrait=content,portrait_changed=True,updated_at=utcnow()))
    commit(db)
    return {'url':f'/api/character-drafts/{draft.id}/portrait?v={secrets.token_hex(8)}'}


@router.post('/api/character-drafts/{draft_id}/portrait/remove')
async def draft_portrait_remove(draft_id: str,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    draft = get_draft(ctx,draft_id,True)
    await read_form(ctx)
    if draft.finalized_at: raise HTTPException(409,'This draft has already been finalized.')
    db.execute(update(CharacterDraft).where(CharacterDraft.id == draft.id).values(portrait=None,portrait_changed=True,updated_at=utcnow()))
    commit(db)
    return {'url':None}

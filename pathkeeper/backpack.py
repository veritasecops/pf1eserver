"""Player-entered inventory carried separately from equipped gear."""
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .character_weapons import character_values, purchase_response
from .gear_backpack import available_slot
from .database import commit, get_db
from .security import audit, context, field, get_character, integer, read_form

router = APIRouter()
ITEM_ID = re.compile(r"[a-f0-9]{32}")


@router.post("/characters/{character_id}/backpack")
async def add_item(character_id: int, request: Request, db: Session = Depends(get_db)):
    from .workspace import verify_version

    ctx = context(request, db)
    form = await read_form(ctx)
    character = get_character(ctx, character_id)
    db.refresh(character, with_for_update=True)
    character = get_character(ctx, character_id)
    item_id = str(form.get("item_id", ""))
    if not ITEM_ID.fullmatch(item_id):
        raise HTTPException(422, "Enter a valid backpack item identifier.")
    data = character.play_data or {}
    entries = data.get("backpack", [])
    previous = next((entry for entry in entries if entry["id"] == item_id), None)
    if form.get("action") == "note":
        verify_version(form, character)
        if previous is None:
            raise HTTPException(409, "This backpack item was removed. Reload the sheet.")
        note = field(form, "notes", 200, required=False)
        character.play_data = {**data, "backpack": [
            {**entry, "notes": note} if entry["id"] == item_id else entry for entry in entries
        ]}
        commit(db)
        return purchase_response(ctx, character)
    name = field(form, "name", 150)
    quantity = integer(form, "quantity", 1, 1000000)
    value = str(form.get("value", "")).strip()
    if not re.fullmatch(r"\d{1,7}(?:\.\d{1,2})?", value) or Decimal(value) > 1000000:
        raise HTTPException(422, "Enter a value from 0 to 1,000,000 gp with up to two decimal places.")
    item = {"id": item_id, "name": name, "quantity": quantity, "unit_cp": int(Decimal(value) * 100)}
    if previous:
        if any(previous.get(key) != value for key, value in item.items()):
            raise HTTPException(409, "This backpack entry changed. Reload the sheet.")
        return purchase_response(ctx, character)
    verify_version(form, character)
    if len(entries) >= 200:
        raise HTTPException(422, "The backpack has reached its 200-entry limit.")
    item["gear_row"] = available_slot(entries, character_values(ctx, character))
    # Manual records have no catalog weight to contribute.
    item["gear_weight"] = "0"
    character.play_data = {**data, "backpack": [*entries, item]}
    audit(db, ctx.user, "character.backpack_added", f"Added {quantity} × {name} to {character.name}'s backpack.")
    commit(db)
    return purchase_response(ctx, character)

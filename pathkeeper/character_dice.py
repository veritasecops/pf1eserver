"""Free dice rolls for the workspace, using the wizard's dice rules."""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .database import get_db
from .security import authenticated, context, get_character, integer, read_form, throttle

router=APIRouter()
DICE=(4,6,8,10,12,20,100)


def free_roll(form):
    sides,count,modifier=integer(form,'sides',4,100),integer(form,'count',1,20),integer(form,'modifier',-1000,1000)
    if sides not in DICE: raise HTTPException(422,'Choose d4, d6, d8, d10, d12, d20, or d100.')
    values=[secrets.randbelow(sides)+1 for _ in range(count)]
    result={'dice':values,'sides':sides,'total':sum(values)+modifier,'modifier':modifier}
    if sides==100: result['percentile']=[{'tens':value//10*10 if value!=100 else 0,'ones':value%10} for value in values]
    return result


@router.post('/characters/{character_id}/roll')
async def roll_character_dice(character_id:int,request:Request,db:Session=Depends(get_db)):
    ctx=context(request,db)
    get_character(ctx,character_id)
    return await roll_for_user(ctx)


@router.post('/dice/roll')
async def roll_workspace_dice(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authenticated(ctx, allow_setup=True)
    return await roll_for_user(ctx)


async def roll_for_user(ctx):
    form=await read_form(ctx)
    throttle('character-dice',str(ctx.user.id),120,15)
    return JSONResponse({'id':secrets.token_hex(16),'purpose':'free','result':free_roll(form)},headers={'Cache-Control':'no-store'})

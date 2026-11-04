"""Private, bounded character portraits, independent of text-sheet revisions."""
from io import BytesIO
import secrets
import warnings

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .database import commit, get_db
from .models import Character
from .security import audit, context, get_character, read_form

router = APIRouter()
MAX_UPLOAD = 220 * 1024
MAX_PIXELS = 16_000_000


def normalize_portrait(content):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=['JPEG','PNG','WEBP']) as image:
                if image.width*image.height > MAX_PIXELS:
                    raise HTTPException(422,'Choose an image with fewer than 16 million pixels.')
                image.load()
                image = ImageOps.exif_transpose(image).convert('RGBA')
                image.thumbnail((768,768),Image.Resampling.LANCZOS)
                rgb = Image.new('RGB',image.size,(255,248,233))
                rgb.paste(image,mask=image.getchannel('A'))
                for quality in (88,75,60,45):
                    output = BytesIO()
                    rgb.save(output,format='JPEG',quality=quality,optimize=True)
                    if output.tell() <= MAX_UPLOAD:
                        return output.getvalue()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombWarning,Image.DecompressionBombError):
        raise HTTPException(422,'Choose a valid JPG, PNG, or WebP image.') from None
    raise HTTPException(422,'The image could not be resized. Try another image.')


async def uploaded_portrait(ctx):
    if not ctx.request.headers.get('content-length'):
        raise HTTPException(411,'The image upload must specify its length.')
    form = await read_form(ctx,max_fields=4,max_files=1)
    upload = form.get('portrait')
    if not isinstance(upload,UploadFile):
        raise HTTPException(422,'Choose a character image.')
    try:
        content = await upload.read(MAX_UPLOAD+1)
    finally:
        await upload.close()
    if not content or len(content) > MAX_UPLOAD:
        raise HTTPException(413,'Resize the image before uploading. The image limit is 220 KB.')
    return await run_in_threadpool(normalize_portrait,content)


def portrait_url(db, record):
    model = type(record)
    exists = db.scalar(select(model.id).where(model.id == record.id,model.portrait.is_not(None)))
    if exists is None: return None
    prefix = f'/characters/{record.id}' if isinstance(record,Character) else f'/api/character-drafts/{record.id}'
    return f'{prefix}/portrait'


def image_response(content):
    if not content: raise HTTPException(404,'Character image not found.')
    return Response(content,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})


@router.get('/characters/{character_id}/portrait')
async def character_portrait(character_id: int,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    character = get_character(ctx,character_id)
    return image_response(character.portrait)


@router.post('/characters/{character_id}/portrait')
async def character_portrait_upload(character_id: int,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    character = get_character(ctx,character_id)
    content = await uploaded_portrait(ctx)
    db.refresh(character,with_for_update=True)
    get_character(ctx,character_id)
    # Portrait changes are independent of text autosaves: update only this blob,
    # leaving the text revision and any in-flight text edits intact.
    db.execute(update(Character).where(Character.id == character.id).values(portrait=content))
    audit(db,ctx.user,'character.portrait_updated',f'Updated the portrait for {character.name}.')
    commit(db)
    return {'url':f'/characters/{character_id}/portrait?v={secrets.token_hex(8)}'}


@router.post('/characters/{character_id}/portrait/remove')
async def character_portrait_remove(character_id: int,request: Request,db: Session = Depends(get_db)):
    ctx = context(request,db)
    character = get_character(ctx,character_id)
    await read_form(ctx)
    db.refresh(character,with_for_update=True)
    get_character(ctx,character_id)
    db.execute(update(Character).where(Character.id == character.id).values(portrait=None))
    audit(db,ctx.user,'character.portrait_removed',f'Removed the portrait for {character.name}.')
    commit(db)
    return {'url':None}

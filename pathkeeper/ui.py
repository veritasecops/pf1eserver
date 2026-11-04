from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from .config import ROOT
from .database import commit
from .security import ROLES, flash

templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.globals.update(roles=ROLES)
templates.env.filters["initials"] = lambda value: "".join(word[0] for word in value.split()[:2]).upper()
templates.env.filters["date"] = lambda value: value.strftime("%b %d, %Y") if value else "Never"


def render(ctx, template, **values):
    message = ctx.session.flash
    if message:
        ctx.session.flash = None
        commit(ctx.db)
    user = ctx.user if ctx.session.phase == "authenticated" else None
    return templates.TemplateResponse(request=ctx.request, name=template, context={
        "user": user, "csrf": ctx.session.csrf, "flash": message,
        "limited": bool(user and (user.must_change_password or (user.totp_required and not user.totp_enabled))),
        "path": ctx.request.url.path, "next_path": ctx.session.next_path, **values})


def redirect(ctx, path, message=None):
    if message:
        flash(ctx, message)
    commit(ctx.db)
    return RedirectResponse(path, status_code=303)

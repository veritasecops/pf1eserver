from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .database import commit, get_db
from .models import AuditEvent, Campaign, Character, Guard, RecoveryCode, User
from .notifications import account_email, email_ready, invalidate_tokens
from .security import (ROLES, administrator, audit, context, email_field, field, hash_password,
                       protect_last_admin, read_form, reauthenticate, revoke_sessions)
from .ui import redirect, render

router = APIRouter(prefix="/administration")


@router.get("/permissions")
async def permissions_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return render(ctx, "permissions.html", title="Roles & permissions")


@router.get("")
async def administration(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    query = select(User)
    search = request.query_params.get("q", "")[:100].strip()
    role = request.query_params.get("role", "")
    status = request.query_params.get("status", "")
    if search:
        query = query.where(or_(User.name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
    if role in ROLES:
        query = query.where(User.role == role)
    if status in {"active", "disabled"}:
        query = query.where(User.active.is_(status == "active"))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    try:
        page = max(1, min(int(request.query_params.get("page", 1)), max(1, (total + 24) // 25)))
    except ValueError:
        page = 1
    users = list(db.scalars(query.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * 25).limit(25)))
    stats = {
        "total": db.scalar(select(func.count()).select_from(User)),
        "active": db.scalar(select(func.count()).select_from(User).where(User.active.is_(True))),
        "admins": db.scalar(select(func.count()).select_from(User).where(User.role == "admin")),
        "mfa": db.scalar(select(func.count()).select_from(User).where(User.totp_enabled.is_(True))),
    }
    return render(ctx, "administration.html", title="Administration", users=users, stats=stats,
                  search=search, role_filter=role, status_filter=status, total=total, page=page, pages=max(1, (total + 24) // 25))


@router.get("/users/new")
async def new_user(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    return render(ctx, "user_form.html", title="Create user", target=None)


@router.post("/users")
async def create_user(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    admin = administrator(ctx)
    form = await read_form(ctx)
    role = field(form, "role", 10)
    if role not in ROLES:
        raise HTTPException(422, "Choose Player, Game Master, or Admin.")
    account = User(name=field(form, "name", 100), email=email_field(form), role=role,
                   password_hash=await run_in_threadpool(hash_password, str(form.get("password", ""))),
                   active=form.get("active") == "on", must_change_password=True,
                   email_verification_required=email_ready(db),
                   totp_required=role == "admin" or form.get("totp_required") == "on")
    db.add(account)
    audit(db, admin, "user.created", f"Created {account.email} as {ROLES[role]}.")
    db.flush()
    emailed = account_email(db, account, "setup", admin.id)
    commit(db)
    return redirect(ctx, f"/administration/users/{account.id}", "Account created. A password setup email has been queued." if emailed else "Account created. Share the temporary password privately; the user must replace it at sign-in.")


@router.get("/users/{user_id}")
async def user_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    counts = {"characters": db.scalar(select(func.count()).select_from(Character).where(Character.owner_id == target.id)),
              "campaigns": db.scalar(select(func.count()).select_from(Campaign).where(Campaign.owner_id == target.id))}
    return render(ctx, "user_form.html", title="Manage user", target=target, counts=counts)


@router.post("/users/{user_id}")
async def update_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    form = await read_form(ctx)
    db.execute(select(Guard).where(Guard.id == 1).with_for_update())
    await reauthenticate(ctx, form)
    administrator(ctx)
    target = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if not target:
        raise HTTPException(404, "User not found.")
    role = field(form, "role", 10)
    if role not in ROLES:
        raise HTTPException(422, "Choose a valid role.")
    active = form.get("active") == "on"
    protect_last_admin(db, target, role, active)
    if role == "player" and db.scalar(select(func.count()).select_from(Campaign).where(Campaign.owner_id == target.id)):
        raise HTTPException(409, "Transfer or delete this user's campaigns before changing their role to Player.")
    target.name = field(form, "name", 100)
    new_email = email_field(form)
    email_changed = new_email != target.email
    target.email = new_email
    target.role = role
    target.active = active
    target.totp_required = role == "admin" or form.get("totp_required") == "on"
    if email_changed:
        target.email_verified_at = None
        target.email_verification_required = email_ready(db)
        invalidate_tokens(db, target.id)
        account_email(db, target, actor_id=ctx.user.id)
    if not active:
        invalidate_tokens(db, target.id)
    revoke_sessions(db, target.id, ctx.session.token_hash if target.id == ctx.user.id and active else None)
    audit(db, ctx.user, "user.updated", f"Updated {target.email}: {ROLES[role]}, {'active' if active else 'disabled'}.")
    if target.id == ctx.user.id and not active:
        commit(db)
        request.state.clear_cookie = True
        return RedirectResponse("/login", 303)
    return redirect(ctx, "/administration" if target.id != ctx.user.id else "/", "User updated. Previous sessions have been revoked.")


@router.post("/users/{user_id}/password")
async def reset_password(user_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    form = await read_form(ctx)
    db.execute(select(Guard).where(Guard.id == 1).with_for_update())
    await reauthenticate(ctx, form)
    administrator(ctx)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    target.password_hash = await run_in_threadpool(hash_password, str(form.get("new_password", "")))
    target.must_change_password = True
    invalidate_tokens(db, target.id, ("reset", "setup"))
    account_email(db, target, "reset", ctx.user.id)
    revoke_sessions(db, target.id)
    audit(db, ctx.user, "user.password_reset", f"Reset the password for {target.email}; their authenticator remains enabled if previously configured.")
    if target.id == ctx.user.id:
        commit(db)
        request.state.clear_cookie = True
        return RedirectResponse("/login", 303)
    return redirect(ctx, f"/administration/users/{user_id}", "Temporary password saved. The user must change it at sign-in.")


@router.post("/users/{user_id}/totp-reset")
async def reset_totp(user_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    form = await read_form(ctx)
    db.execute(select(Guard).where(Guard.id == 1).with_for_update())
    await reauthenticate(ctx, form)
    administrator(ctx)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if field(form, "confirm_email", 190).lower() != target.email:
        raise HTTPException(422, "Type the target user's email to confirm the reset.")
    target.totp_secret = None
    target.pending_totp = None
    target.pending_totp_at = None
    target.totp_enabled = False
    target.last_totp_counter = -1
    target.totp_required = True
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    revoke_sessions(db, user_id)
    audit(db, ctx.user, "user.mfa_reset", f"Reset the authenticator for {target.email}; enrollment is required at next sign-in.")
    if user_id == ctx.user.id:
        commit(db)
        request.state.clear_cookie = True
        return RedirectResponse("/login", 303)
    return redirect(ctx, f"/administration/users/{user_id}", "Authenticator reset. The user must enroll again at sign-in.")


@router.post("/users/{user_id}/delete")
async def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    form = await read_form(ctx)
    db.execute(select(Guard).where(Guard.id == 1).with_for_update())
    await reauthenticate(ctx, form)
    administrator(ctx)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    protect_last_admin(db, target, deleting=True)
    if field(form, "confirm_email", 190).lower() != target.email:
        raise HTTPException(422, "Type the target user's email to confirm deletion.")
    own = target.id == ctx.user.id
    audit(db, None if own else ctx.user, "user.deleted", f"Admin {ctx.user.name} deleted {target.email}, their owned characters, and owned campaigns.")
    from .advancement import detach_characters
    for campaign in db.scalars(select(Campaign).where(Campaign.owner_id == target.id).order_by(Campaign.id).with_for_update()):
        detach_characters(db, campaign)
    db.delete(target)
    if own:
        commit(db)
        request.state.clear_cookie = True
        return RedirectResponse("/login", 303)
    return redirect(ctx, "/administration", "User permanently deleted.")


@router.get("/audit")
async def audit_page(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    administrator(ctx)
    events = db.execute(select(AuditEvent, User.name).outerjoin(User, User.id == AuditEvent.actor_id).order_by(AuditEvent.id.desc()).limit(100)).all()
    return render(ctx, "audit.html", title="Activity log", events=events)

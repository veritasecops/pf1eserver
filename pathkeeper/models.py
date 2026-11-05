from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.dialects.mysql import MEDIUMBLOB

LONG_TEXT = Text().with_variant(MEDIUMTEXT(), "mysql")
PORTRAIT = LargeBinary().with_variant(MEDIUMBLOB(), "mysql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(190), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="player", index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_required: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_totp: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_totp_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_totp_counter: Mapped[int] = mapped_column(BigInteger, default=-1)
    bio: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_verification_required: Mapped[bool] = mapped_column(Boolean, default=False)


class WebSession(Base):
    __tablename__ = "web_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(20), default="anonymous")
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    next_path: Mapped[str] = mapped_column(String(300), default="/")
    flash: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(LONG_TEXT, default="")
    setting: Mapped[str] = mapped_column(String(150), default="")
    xp_speed: Mapped[str] = mapped_column(String(6), default="slow", server_default="slow")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __mapper_args__ = {"version_id_col": version}


class Membership(Base):
    __tablename__ = "memberships"
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    ancestry: Mapped[str] = mapped_column(String(100), default="")
    class_name: Mapped[str] = mapped_column(String(100), default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(LONG_TEXT, default="")
    sheet_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    play_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    portrait: Mapped[bytes | None] = mapped_column(PORTRAIT, nullable=True, deferred=True)
    header_background: Mapped[bytes | None] = mapped_column(PORTRAIT, nullable=True, deferred=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __mapper_args__ = {"version_id_col": version}


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    email: Mapped[str] = mapped_column(String(190))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    bucket: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Guard(Base):
    __tablename__ = "transaction_guards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class EmailConfiguration(Base):
    __tablename__ = "email_configuration"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(10), default="brevo")
    public_base_url: Mapped[str] = mapped_column(String(300), default="")
    sender_name: Mapped[str] = mapped_column(String(100), default="Pathkeeper")
    sender_email: Mapped[str] = mapped_column(String(190), default="")
    reply_to: Mapped[str] = mapped_column(String(190), default="")
    brevo_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_host: Mapped[str] = mapped_column(String(253), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_security: Mapped[str] = mapped_column(String(10), default="starttls")
    smtp_username: Mapped[str] = mapped_column(String(254), default="")
    smtp_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    __mapper_args__ = {"version_id_col": version}


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recipient: Mapped[str] = mapped_column(String(190))
    provider: Mapped[str] = mapped_column(String(10))
    configuration_version: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(30), default="test")
    status: Mapped[str] = mapped_column(String(15), default="pending")
    detail: Mapped[str] = mapped_column(String(300), default="")
    message_id: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccountToken(Base):
    __tablename__ = "account_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(190))
    purpose: Mapped[str] = mapped_column(String(15))
    password_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    delivery_id: Mapped[int] = mapped_column(ForeignKey("email_deliveries.id", ondelete="CASCADE"), primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    encrypted_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str | None] = mapped_column(ForeignKey("account_tokens.token_hash", ondelete="SET NULL"), nullable=True)
    invitation_id: Mapped[int | None] = mapped_column(ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True)


class CharacterDraft(Base):
    __tablename__ = "character_drafts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(10), default="create")
    editing_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    existing_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict] = mapped_column(JSON)
    portrait_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    portrait: Mapped[bytes | None] = mapped_column(PORTRAIT, nullable=True, deferred=True)
    step: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    completed_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __mapper_args__ = {"version_id_col": version}


class DiceRoll(Base):
    __tablename__ = "dice_rolls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("character_drafts.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(10))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("draft_id", "request_id", name="uq_draft_roll_request"),)


class RuleCatalog(Base):
    __tablename__ = "rule_catalog"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    __mapper_args__ = {"version_id_col": version}

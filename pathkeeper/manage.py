"""Local, trusted administration. Passwords are entered at a hidden terminal prompt."""
import argparse
import getpass
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import tarfile
import tempfile

from cryptography.fernet import Fernet
import pymysql
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from .config import ROOT, settings
from .models import Base, Guard, RecoveryCode, User, utcnow


def require_root():
    if os.geteuid() != 0:
        raise SystemExit("Run this management command with sudo on the application server.")


def initialize():
    require_root()
    path = ROOT / ".env"
    if not path.exists():
        password = secrets.token_hex(32)
        url = URL.create("mysql+pymysql", username="pf1eserver", password=password, host="localhost", database="pf1eserver", query={"unix_socket": "/run/mysqld/mysqld.sock", "charset": "utf8mb4"})
        path.write_text(f'PF_DATABASE_URL="{url.render_as_string(hide_password=False)}"\nPF_ENCRYPTION_KEY="{Fernet.generate_key().decode()}"\nPF_SECURE_COOKIES=false\n')
    account = pwd.getpwnam("pf1eserver")
    os.chown(path, 0, account.pw_gid)
    path.chmod(0o640)
    settings.cache_clear()
    from sqlalchemy.engine import make_url
    url = make_url(settings().database_url)
    with pymysql.connect(user="root", unix_socket="/run/mysqld/mysqld.sock", autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS pf1eserver CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.execute("CREATE USER IF NOT EXISTS 'pf1eserver'@'localhost' IDENTIFIED BY %s", (url.password,))
            cursor.execute("ALTER USER 'pf1eserver'@'localhost' IDENTIFIED BY %s", (url.password,))
            cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pf1eserver.* TO 'pf1eserver'@'localhost'")
    admin_engine = create_engine(URL.create("mysql+pymysql", username="root", host="localhost", database="pf1eserver", query={"unix_socket": "/run/mysqld/mysqld.sock"}), hide_parameters=True)
    Base.metadata.create_all(admin_engine)
    with Session(admin_engine) as db:
        if not db.get(Guard, 1):
            db.add(Guard(id=1))
        db.commit()
    from .migrations import migrate
    migrate(admin_engine)
    admin_engine.dispose()
    settings().storage.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(settings().storage, account.pw_uid, account.pw_gid)
    print("MariaDB schema and restricted application account initialized.")
    print("No default user or password was created. Use create-admin to add the first Admin.")


def hidden_password():
    from .security import hash_password
    first = getpass.getpass("Password (12–128 characters): ")
    if first != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")
    return hash_password(first)


def manage_user(command, email=None, name=None, generate_password=False):
    require_root()
    from .database import engine
    from .security import audit, email_field, revoke_sessions
    email = email_field({"email": email or input("Email: ")})
    temporary_password = None
    with Session(engine()) as db:
        db.execute(select(Guard).where(Guard.id == 1).with_for_update())
        account = db.scalar(select(User).where(User.email == email).with_for_update())
        if command == "create-admin":
            if account:
                raise SystemExit("An account already uses this email.")
            name = (name or input("Display name: ")).strip()
            if not 1 <= len(name) <= 100:
                raise SystemExit("Use a display name between 1 and 100 characters.")
            if generate_password:
                from .security import hash_password
                temporary_password = secrets.token_urlsafe(24)
                encoded = hash_password(temporary_password)
            else:
                encoded = hidden_password()
            account = User(email=email, name=name, role="admin", active=True,
                           password_hash=encoded, totp_required=True, must_change_password=generate_password)
            db.add(account)
            audit(db, None, "local.admin_created", f"A server administrator created Admin {email}.")
        elif not account:
            raise SystemExit("Account not found.")
        elif command == "reset-password":
            account.password_hash = hidden_password()
            account.must_change_password = True
            revoke_sessions(db, account.id)
            audit(db, None, "local.password_reset", f"A server administrator reset the password for {email}.")
        elif command == "reset-totp":
            if input(f"Type {email} to confirm authenticator reset: ").strip().lower() != email:
                raise SystemExit("Reset cancelled.")
            account.totp_enabled = False
            account.totp_secret = None
            account.pending_totp = None
            account.pending_totp_at = None
            account.last_totp_counter = -1
            account.totp_required = True
            db.query(RecoveryCode).filter_by(user_id=account.id).delete()
            revoke_sessions(db, account.id)
            audit(db, None, "local.mfa_reset", f"A server administrator reset the authenticator for {email}.")
        db.commit()
    if temporary_password:
        print(json.dumps({"email": email, "temporary_password": temporary_password,
                          "must_change_password": True, "totp_required": True}))
    else:
        print("Account updated. Sign in through the normal login page.")


def backup(destination):
    require_root()
    destination = Path(destination).resolve()
    if destination.is_relative_to(ROOT):
        raise SystemExit("Store backups outside /opt/pf1eserver.")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = destination / f"pathkeeper-{utcnow():%Y%m%d-%H%M%S}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="pathkeeper-backup-") as temporary:
        dump = Path(temporary) / "database.sql"
        with dump.open("wb") as output:
            subprocess.run(["mariadb-dump", "--user=root", "--socket=/run/mysqld/mysqld.sock", "--single-transaction", "--skip-lock-tables", "pf1eserver"], stdout=output, check=True)
        # Exclusive creation and mode 0600 protect the encryption key from the first byte.
        descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            with tarfile.open(fileobj=output, mode="w:gz") as tar:
                tar.add(dump, arcname="database.sql")
                for name in (".env", "pyproject.toml", "uv.lock", ".python-version", "storage"):
                    if (ROOT / name).exists():
                        tar.add(ROOT / name, arcname=name)
    print(f"Backup saved to {archive}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("migrate")
    for name in ("create-admin", "reset-password", "reset-totp"):
        command = commands.add_parser(name)
        command.add_argument("--email")
        if name == "create-admin":
            command.add_argument("--name")
            command.add_argument("--generate-password", action="store_true", help="Print a generated temporary password once; force replacement at sign-in.")
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--destination", default="/var/backups/pf1eserver")
    args = parser.parse_args()
    if args.command == "init":
        initialize()
    elif args.command == "migrate":
        require_root()
        from .migrations import migrate
        admin_engine = create_engine(URL.create("mysql+pymysql", username="root", database="pf1eserver",
                                    query={"unix_socket": "/run/mysqld/mysqld.sock"}), hide_parameters=True)
        try:
            migrate(admin_engine)
        finally:
            admin_engine.dispose()
    elif args.command == "backup":
        backup(args.destination)
    else:
        manage_user(args.command, args.email, getattr(args, "name", None), getattr(args, "generate_password", False))


if __name__ == "__main__":
    main()

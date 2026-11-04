"""Disposable browser QA. No production configuration or user data is used."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

from cryptography.fernet import Fernet
import pymysql
import pyotp
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from pathkeeper.config import ROOT, settings
from pathkeeper.models import Base, Campaign, Character, EmailConfiguration, Guard, Membership, User, utcnow


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo using the project's Python.")
    suffix = secrets.token_hex(5)
    database, db_user, password = f"pf1e_qa_{suffix}", f"pfq_{suffix}", secrets.token_hex(24)
    root = pymysql.connect(user="root", unix_socket="/run/mysqld/mysqld.sock", autocommit=True)
    server = None
    admin_engine = None
    log = None
    with tempfile.TemporaryDirectory(prefix="pathkeeper-qa-") as temporary:
        try:
            with root.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                cursor.execute(f"CREATE USER '{db_user}'@'localhost' IDENTIFIED BY %s", (password,))
                cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {database}.* TO '{db_user}'@'localhost'")
            admin_engine = create_engine(URL.create("mysql+pymysql", username="root", database=database, query={"unix_socket": "/run/mysqld/mysqld.sock"}))
            Base.metadata.create_all(admin_engine)
            url = URL.create("mysql+pymysql", username=db_user, password=password, database=database, query={"unix_socket": "/run/mysqld/mysqld.sock", "charset": "utf8mb4"})
            os.environ.update(PF_DATABASE_URL=url.render_as_string(hide_password=False), PF_ENCRYPTION_KEY=Fernet.generate_key().decode(), PF_SECURE_COOKIES="false", PF_STORAGE=temporary)
            settings.cache_clear()
            from pathkeeper.security import PASSWORDS, encrypt, make_recovery_codes
            encoded = PASSWORDS.hash("Fixture-password-2026!")
            with Session(admin_engine, expire_on_commit=False) as db:
                db.add(Guard(id=1))
                db.add(EmailConfiguration(id=1))
                admin = User(name="QA Administrator", email="admin@qa.example.com", role="admin", password_hash=encoded,
                             totp_required=True, totp_enabled=True, totp_secret=encrypt(pyotp.random_base32()), last_login=utcnow())
                gm = User(name="Elara Voss", email="elara@qa.example.com", role="gm", password_hash=encoded, last_login=utcnow())
                player = User(name="Lyra Moonwhisper", email="lyra@qa.example.com", role="player", password_hash=encoded)
                player2 = User(name="Kaelen Ashford", email="kaelen@qa.example.com", role="player", password_hash=encoded, last_login=utcnow())
                disabled = User(name="Bramble Underhill", email="bramble@qa.example.com", role="player", password_hash=encoded, active=False)
                db.add_all([admin, gm, player, player2, disabled])
                db.flush()
                recovery = make_recovery_codes(db, admin.id)
                campaign = Campaign(owner_id=gm.id, name="The Shattered Crown", setting="The Northern Marches", description="An ancient oath, a missing heir, and a kingdom at the edge of winter.")
                db.add(campaign)
                db.flush()
                db.add_all([Membership(campaign_id=campaign.id, user_id=player.id), Membership(campaign_id=campaign.id, user_id=player2.id),
                            Character(owner_id=player.id, campaign_id=campaign.id, name="Lyra Moonwhisper", ancestry="Elf", class_name="Wizard", level=5, notes="A scholar drawn north by an unfinished promise."),
                            Character(owner_id=player2.id, campaign_id=campaign.id, name="Kaelen Ashford", ancestry="Human", class_name="Fighter", level=5)])
                db.commit()
            log = open(Path(temporary) / "server.log", "w+")
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "pathkeeper.main:app", "--host", "127.0.0.1", "--port", "8091", "--no-access-log"], cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", 8091), timeout=0.2):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError("The QA server failed to start.")
                    time.sleep(0.1)
            else:
                raise RuntimeError("The QA server did not become ready.")
            print("QA ready on 127.0.0.1:8091. This is a temporary database.", flush=True)
            print("Synthetic login: admin@qa.example.com / Fixture-password-2026!", flush=True)
            print(f"One-use QA recovery code: {recovery[0]}", flush=True)
            input("Press Enter to stop QA and remove its data.\n")
        finally:
            if server:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            if log:
                log.close()
            if admin_engine:
                admin_engine.dispose()
            with root.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS {database}")
                cursor.execute(f"DROP USER IF EXISTS '{db_user}'@'localhost'")
            root.close()


if __name__ == "__main__":
    main()

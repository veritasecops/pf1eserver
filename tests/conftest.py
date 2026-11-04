import os
import secrets
from types import SimpleNamespace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pymysql
import pyotp
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from pathkeeper.config import settings
from pathkeeper.database import engine
from pathkeeper.models import Base, EmailConfiguration, Guard, User, WebSession
from pathkeeper.security import COOKIE, PASSWORDS, digest, encrypt, make_recovery_codes

PASSWORD = "Testing-passphrase-2026!"


@pytest.fixture(scope="session", autouse=True)
def isolated_database():
    if os.geteuid() != 0:
        pytest.exit("Run tests with sudo using the project's managed Python; a temporary MariaDB database is required.")
    suffix = secrets.token_hex(5)
    database, user, password = f"pf1e_test_{suffix}", f"pft_{suffix}", secrets.token_hex(24)
    root = pymysql.connect(user="root", unix_socket="/run/mysqld/mysqld.sock", autocommit=True)
    admin_engine = None
    old = {key: os.environ.get(key) for key in ("PF_DATABASE_URL", "PF_ENCRYPTION_KEY", "PF_SECURE_COOKIES")}
    try:
        with root.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.execute(f"CREATE USER '{user}'@'localhost' IDENTIFIED BY %s", (password,))
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {database}.* TO '{user}'@'localhost'")
        admin_url = URL.create("mysql+pymysql", username="root", database=database, query={"unix_socket": "/run/mysqld/mysqld.sock"})
        admin_engine = create_engine(admin_url, hide_parameters=True)
        Base.metadata.create_all(admin_engine)
        url = URL.create("mysql+pymysql", username=user, password=password, database=database, query={"unix_socket": "/run/mysqld/mysqld.sock", "charset": "utf8mb4"})
        os.environ.update(PF_DATABASE_URL=url.render_as_string(hide_password=False), PF_ENCRYPTION_KEY=Fernet.generate_key().decode(), PF_SECURE_COOKIES="false")
        settings.cache_clear()
        engine.cache_clear()
        yield admin_engine
    finally:
        if engine.cache_info().currsize:
            engine().dispose()
        engine.cache_clear()
        settings.cache_clear()
        if admin_engine:
            admin_engine.dispose()
        with root.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS {database}")
            cursor.execute(f"DROP USER IF EXISTS '{user}'@'localhost'")
        root.close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="session")
def encoded_password():
    return PASSWORDS.hash(PASSWORD)


@pytest.fixture
def env(isolated_database, encoded_password):
    with isolated_database.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))
        connection.execute(Guard.__table__.insert().values(id=1))
        connection.execute(EmailConfiguration.__table__.insert().values(id=1))
    clients = []

    def add_user(role="player", email=None, mfa=False, required=False, change=False, active=True):
        with Session(engine(), expire_on_commit=False) as db:
            secret = pyotp.random_base32() if mfa else None
            user = User(name=f"Test {role.title()}", email=email or f"{secrets.token_hex(4)}@example.com", role=role,
                        password_hash=encoded_password, active=active, totp_required=required or role == "admin",
                        totp_enabled=mfa, totp_secret=encrypt(secret) if secret else None, must_change_password=change)
            db.add(user)
            db.flush()
            codes = make_recovery_codes(db, user.id) if mfa else []
            db.commit()
            return SimpleNamespace(id=user.id, email=user.email, role=role, secret=secret, codes=codes, password=PASSWORD)

    def client():
        from pathkeeper.main import app
        c = TestClient(app, follow_redirects=False)
        c.get("/login")
        clients.append(c)
        return c

    def csrf(c):
        with Session(engine()) as db:
            return db.get(WebSession, digest(c.cookies[COOKIE])).csrf

    def post(c, path, data=None, use_csrf=True):
        values = dict(data or {})
        if use_csrf:
            values["csrf"] = csrf(c)
        return c.post(path, data=values)

    def login(user, complete=True):
        c = client()
        response = post(c, "/login", {"email": user.email, "password": user.password})
        assert response.status_code == 303
        if user.secret and complete:
            response = post(c, "/login/totp", {"code": user.codes.pop()})
            assert response.status_code == 303
        return c

    def confirmation(user):
        return {"current_password": user.password, "code": user.codes.pop() if user.codes else ""}

    result = SimpleNamespace(add=add_user, client=client, post=post, csrf=csrf, login=login, confirm=confirmation)
    result.admin = add_user("admin", "admin@example.com", mfa=True)
    result.gm = add_user("gm", "gm@example.com")
    result.gm2 = add_user("gm", "gm2@example.com")
    result.player = add_user("player", "player@example.com")
    result.player2 = add_user("player", "player2@example.com")
    yield result
    for c in clients:
        c.close()

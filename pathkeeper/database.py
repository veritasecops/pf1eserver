from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .config import settings


@lru_cache
def engine():
    # Fresh statement snapshots avoid MariaDB 11.8 error 1020 when a locking read
    # follows a concurrent update. Explicit row locks still serialize MFA use.
    return create_engine(settings().database_url, pool_pre_ping=True, pool_recycle=1800,
                         hide_parameters=True, isolation_level="READ COMMITTED")


def get_db():
    with Session(engine(), expire_on_commit=False) as db:
        yield db


def commit(db):
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "This record changed in another window. Reload before editing again.") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with that email or a conflicting record already exists.") from None

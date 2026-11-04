"""Explicit additive migrations for existing MariaDB instances."""
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .models import AccountToken, EmailConfiguration, EmailDelivery, EmailOutbox, SchemaMigration


def migrate(admin_engine):
    # MariaDB DDL commits separately. Complete all DDL before opening a read
    # transaction, so snapshot isolation cannot retain pre-DDL table definitions.
    for model in (SchemaMigration, EmailConfiguration, EmailDelivery, AccountToken, EmailOutbox):
        model.__table__.create(admin_engine, checkfirst=True)
    additions = {
        "users": {"email_verified_at": "DATETIME NULL", "email_verification_required": "BOOLEAN NOT NULL DEFAULT 0"},
        "email_configuration": {"public_base_url": "VARCHAR(300) NOT NULL DEFAULT ''"},
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in inspect(admin_engine).get_columns(table)}
        for name, definition in columns.items():
            if name not in existing:
                with admin_engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {definition}"))
    with Session(admin_engine) as db:
        if not db.get(SchemaMigration, 1):
            if not db.get(EmailConfiguration, 1):
                db.add(EmailConfiguration(id=1))
            db.add(SchemaMigration(version=1, name="email_configuration_and_delivery_history"))
            db.commit()
        if not db.get(SchemaMigration, 2):
            db.add(SchemaMigration(version=2, name="account_email_workflows_and_outbox"))
            db.commit()
    print("Database migrations applied through 002 (account email workflows and outbox).")

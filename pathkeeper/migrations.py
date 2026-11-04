"""Explicit additive migrations for existing MariaDB instances."""
from sqlalchemy.orm import Session

from .models import EmailConfiguration, EmailDelivery, SchemaMigration


def migrate(admin_engine):
    # MariaDB DDL commits separately. Complete all DDL before opening a read
    # transaction, so snapshot isolation cannot retain pre-DDL table definitions.
    for model in (SchemaMigration, EmailConfiguration, EmailDelivery):
        model.__table__.create(admin_engine, checkfirst=True)
    with Session(admin_engine) as db:
        if not db.get(SchemaMigration, 1):
            if not db.get(EmailConfiguration, 1):
                db.add(EmailConfiguration(id=1))
            db.add(SchemaMigration(version=1, name="email_configuration_and_delivery_history"))
            db.commit()
    print("Database migrations applied (001: email configuration and delivery history).")

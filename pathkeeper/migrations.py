"""Explicit versioned schema and data migrations for MariaDB instances."""
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .models import AccountToken, Character, CharacterDraft, DiceRoll, EmailConfiguration, EmailDelivery, EmailOutbox, RuleCatalog, SchemaMigration


def remove_manual_class_fields(db):
    from .character_rules import calculate, clean

    removed = {"class_notes", "extra_class_skills"}
    changed_characters = {}
    for character in db.scalars(select(Character).where(Character.sheet_data.is_not(None)).with_for_update()):
        sheet = character.sheet_data
        inputs = clean({key:value for key,value in sheet["input"].items() if key not in removed},character.owner_id)
        rolls = {roll["id"]:roll for roll in sheet.get("rolls",[])}
        changed_characters[character.id] = (character.version,character)
        character.sheet_data = {**sheet,"input":inputs,"computed":calculate(inputs,rolls)}
    db.flush()
    for draft in db.scalars(select(CharacterDraft).with_for_update()):
        draft.data = {key:value for key,value in draft.data.items() if key not in removed}
        # Preserve editing drafts that were current before this migration;
        # drafts that already conflicted with another edit must remain stale.
        if draft.mode == "edit" and draft.editing_id in changed_characters:
            previous,character = changed_characters[draft.editing_id]
            if draft.existing_version == previous:
                draft.existing_version = character.version


def remove_automatic_racial_summaries(db):
    from .pf1_data import RACES

    summaries = {race['traits'] for race in RACES.values() if race.get('traits')}
    changed = {}
    for character in db.scalars(select(Character).where(Character.play_data.is_not(None)).with_for_update()):
        saved = character.play_data
        cleaned = {key:value for key,value in saved.items()
                   if not (key.startswith('feature.') and isinstance(value,str) and value in summaries)}
        if cleaned != saved:
            changed[character.id] = (character.version,character)
            character.play_data = cleaned
    db.flush()
    for draft in db.scalars(select(CharacterDraft).where(CharacterDraft.mode == 'edit').with_for_update()):
        if draft.editing_id in changed:
            previous,character = changed[draft.editing_id]
            if draft.existing_version == previous:
                draft.existing_version = character.version


def migrate(admin_engine):
    # MariaDB DDL commits separately. Complete all DDL before opening a read
    # transaction, so snapshot isolation cannot retain pre-DDL table definitions.
    for model in (SchemaMigration, EmailConfiguration, EmailDelivery, AccountToken, EmailOutbox, CharacterDraft, DiceRoll, RuleCatalog):
        model.__table__.create(admin_engine, checkfirst=True)
    additions = {
        "users": {"email_verified_at": "DATETIME NULL", "email_verification_required": "BOOLEAN NOT NULL DEFAULT 0"},
        "email_configuration": {"public_base_url": "VARCHAR(300) NOT NULL DEFAULT ''"},
        "characters": {"sheet_data": "JSON NULL", "play_data": "JSON NULL", "portrait": "MEDIUMBLOB NULL", "header_background": "MEDIUMBLOB NULL"},
        "character_drafts": {"portrait": "MEDIUMBLOB NULL", "portrait_changed": "BOOLEAN NOT NULL DEFAULT 0"},
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
        if not db.get(SchemaMigration, 3):
            db.add(SchemaMigration(version=3, name="character_wizard_drafts_sheets_and_dice"))
            db.commit()
        if not db.get(SchemaMigration, 4):
            remove_manual_class_fields(db)
            db.add(SchemaMigration(version=4, name="fixed_class_skills_and_removed_class_notes"))
            db.commit()
        if not db.get(SchemaMigration, 5):
            db.add(SchemaMigration(version=5, name="editable_deluxe_character_play_records"))
            db.commit()
        if not db.get(SchemaMigration, 6):
            remove_automatic_racial_summaries(db)
            db.add(SchemaMigration(version=6, name="remove_automatic_racial_trait_summaries"))
            db.commit()
        if not db.get(SchemaMigration, 7):
            db.add(SchemaMigration(version=7, name="character_and_draft_portrait_images"))
            db.commit()
        if not db.get(SchemaMigration, 8):
            db.add(SchemaMigration(version=8, name="owner_editable_character_header_backgrounds"))
            db.commit()
        if not db.get(SchemaMigration, 9):
            from .rule_catalog import default_catalog
            if not db.get(RuleCatalog, 1):
                db.add(RuleCatalog(id=1, data=default_catalog()))
            db.add(SchemaMigration(version=9, name="editable_feat_skill_and_weapon_catalog"))
            db.commit()
        if not db.get(SchemaMigration, 10):
            from copy import deepcopy
            from .weapons import merge_weapon_tables
            record = db.get(RuleCatalog, 1)
            updated = deepcopy(record.data)
            updated['weapons'] = merge_weapon_tables(updated['weapons'])
            record.data = updated
            db.add(SchemaMigration(version=10, name="simple_martial_exotic_weapon_tables_and_links"))
            db.commit()
        if not db.get(SchemaMigration, 11):
            from copy import deepcopy
            from .rule_catalog import default_catalog
            record=db.get(RuleCatalog,1)
            updated=deepcopy(record.data)
            updated['armor']={**default_catalog()['armor'],**updated.get('armor',{})}
            record.data=updated
            db.add(SchemaMigration(version=11,name="armor_shield_catalog_and_equipment_picker"))
            db.commit()
        if not db.get(SchemaMigration, 12):
            from copy import deepcopy
            from .deities import table_deities
            record=db.get(RuleCatalog,1)
            updated=deepcopy(record.data)
            updated['deities']={**deepcopy(table_deities()),**updated.get('deities',{})}
            record.data=updated
            db.add(SchemaMigration(version=12,name="deity_and_belief_catalog"))
            db.commit()
    print("Database migrations applied through 012 (deity and belief catalog).")

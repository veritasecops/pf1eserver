## Inspect the running application

```sh
sudo systemctl status pf1eserver --no-pager
sudo journalctl -u pf1eserver -n 100 --no-pager
curl --fail http://127.0.0.1:8080/health
```

The health endpoint checks MariaDB connectivity and identifies the running application version. It does not verify a user's password or TOTP device. Check the Admin activity log for account actions; do not paste passwords or recovery codes into support logs.

## Full backups

Run the trusted local management command:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage backup
```

It creates a root-only archive under `/var/backups/pf1eserver` containing a consistent SQL dump, `.env`, dependency lock/pin files, and storage. The archive includes the encryption key and database credential, so keep it private and copy it off-server. No recurring backup schedule is installed automatically.

Database rows alone are insufficient for TOTP or email credential recovery: preserve the matching `.env` encryption key. Password hashes remain verifiable without the encryption key, but enrolled authenticator secrets and saved provider credentials do not.

## Restore or migrate

Prefer restoring into a separate instance before replacing a live system. Use source and dependency versions compatible with the saved database. Stop Uvicorn on the target, inspect the trusted backup's file list, and extract it into a private staging directory. Import `database.sql` into the target `pf1eserver` database with MariaDB administrative access. Restore the matching `.env` and storage, applying root/service-group permissions to `.env` and service-user ownership to storage.

On the target, run `manage init` with the restored configuration to recreate/synchronize the restricted database account. It preserves the existing encryption key and does not clear existing records. Restart Uvicorn, check health, and test an existing password and authenticator through the intended HTTPS address. Restore the Secure-cookie flag appropriate to that address.

Restoring over an existing database replaces its saved account and campaign state and can discard newer changes. Back up that target first. Do not extract an untrusted archive as root. There is no in-app selective undelete or import workflow.

## Local account recovery

A trusted operator with sudo can add another Admin, reset a password, or reset a lost authenticator:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage create-admin
sudo .venv/bin/python -m pathkeeper.manage reset-password --email USER_EMAIL
sudo .venv/bin/python -m pathkeeper.manage reset-totp --email USER_EMAIL
```

Replace USER_EMAIL before running a reset. Password prompts are hidden. Authenticator reset requires typing the target email again, revokes sessions and recovery codes, and forces new enrollment. Password reset leaves existing TOTP in place. These commands are audited and require local root access; they are not unauthenticated web endpoints.

## Source updates

Back up first. Preserve `.env`, storage, and their permissions. Deploy reviewed source and lockfile changes, run `uv sync --locked --managed-python` with the project's managed-Python/cache paths, run `sudo .venv/bin/python -m pathkeeper.manage migrate`, run the isolated tests, and restart the service. The migrate command applies explicit versioned additive migrations. Do not overwrite the encryption key or assume create_all applies future schema changes. Rollback requires compatible source, dependencies, database state, and encryption key together.

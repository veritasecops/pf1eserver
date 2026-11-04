# Pathkeeper 0.2

Python administration and identity foundation for a Pathfinder First Edition platform. FastAPI + Uvicorn + MariaDB. Python 3.13.18 is installed by uv under `.python`; dependencies live in `.venv` and are locked by `uv.lock`. The service never uses the operating system's Python. No nginx, Apache, PHP, Docker, Node.js, or Homebrew dependency exists.

## Implemented

- MariaDB users with Argon2 passwords and public Player sign-up; no server key or default password. Public registration cannot grant privileged roles.
- Revocable server-side sessions, rotated opaque cookies, CSRF protection, throttling, and immediate disabled-account enforcement.
- TOTP enrollment with QR/manual entry, encrypted secrets, replay prevention, one-time hashed recovery codes, and Admin-controlled resets.
- Admin-only user creation, editing, disable/enable, deletion, role assignment, password resets, and activity log. Admins require TOTP. The last active Admin is protected.
- Player: full CRUD on owned characters. Game Master: full CRUD on owned campaigns, owned characters, and joined members' characters assigned to owned campaigns. Admin: all users, campaigns, and characters.
- Email-bound, single-use, seven-day invitations; revocation and member removal. A GM can create a joined member's character in that GM's campaign. Removing membership detaches the member's characters.
- Basic campaign/character records with version-based edit-conflict protection. Detailed PF1e sheets, dice, encounters, spells, maps, and inventory are outside this foundation release.
- Searchable public help, printable articles/full manual, and downloadable manual. Help does not query the database.
- Administration → Email Configuration: Brevo HTTPS API or SMTP relay, encrypted write-only credentials, verified TLS, sender/reply-to identity, enable/disable, explicit test sending, and persisted delivery history. No automatic account or invitation emails, background queue, retries, or bounce webhooks yet. See `/help/email`.

## Server

Source: `/opt/pf1eserver`. Origin: `http://10.0.0.154:8080`. Unit: `pf1eserver.service`. Uvicorn runs two workers as the unprivileged `pf1eserver` account. MariaDB listens locally. TLS belongs on the existing external reverse proxy.

Create the first Admin interactively on the server:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage create-admin
```

Sign in through `/login` and enroll TOTP. The installer creates no default credentials. Users created through Administration receive temporary passwords and must replace them at sign-in. Public `/signup` creates an active Player with their chosen password and signs them in immediately. Email is sent only through the explicit Admin test action; account emails and invitation emails are not sent automatically. Mailbox ownership is not verified.

For a generated temporary Admin password, use `create-admin --email EMAIL --name NAME --generate-password`. The command prints the password once after saving its hash and requires a password change and TOTP enrollment at first sign-in. Keep that output private.

## Installation and operation

See `/help/installation`, `/help/hosting`, and `/help/maintenance` in the app, or their source files in `docs/`. They cover clean installation, the managed runtime, service-account permissions, proxy trust, Secure cookies, backup/restore, and local recovery. General official references: [uv Python management](https://docs.astral.sh/uv/guides/install-python/), [Uvicorn settings](https://uvicorn.dev/settings/), and [PyOTP](https://pyauth.github.io/pyotp/).

`.env` contains the database credential and the Fernet key that encrypts TOTP secrets. It is generated locally with root/service-group access, excluded from source, and must be preserved with backups. Changing that encryption key makes existing authenticator secrets unreadable. Set `PF_SECURE_COOKIES=true` after connecting the HTTPS proxy. Configure the unit's trusted forwarded IPs to the actual reverse proxy rather than a wildcard.

```sh
sudo systemctl status pf1eserver --no-pager
sudo journalctl -u pf1eserver -n 100 --no-pager
curl --fail http://127.0.0.1:8080/health
sudo /opt/pf1eserver/.venv/bin/python -m pathkeeper.manage backup
```

## Verification

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pytest -q
```

Tests create a temporary MariaDB database/user and seed synthetic accounts, then clean them up. They do not use the production user store. Run as root on the server to permit temporary database provisioning. Browser QA likewise uses a separate, loopback-only temporary instance.

The supplied `manage init` creates the database/tables and a DML-only runtime user using local MariaDB root socket authentication. Existing installations run `sudo .venv/bin/python -m pathkeeper.manage migrate` to apply explicit additive migrations. Migration 001 introduces email configuration and delivery history, starts delivery disabled, and preserves existing accounts and campaigns.

Email adapters use Python's standard `smtplib` and `urllib` libraries without an additional provider SDK. `pathkeeper.email_delivery.send_email` takes an immutable settings snapshot and returns accepted/failed/unknown; application callers commit attempt state before running it in a worker thread and persist the result afterward. Brevo endpoint and authentication follow the [official API guide](https://developers.brevo.com/docs/send-a-transactional-email). SMTP TLS modes follow the [Python documentation](https://docs.python.org/3.13/library/smtplib.html).

Pathfinder is a trademark of Paizo Inc. Pathkeeper is an independent project.

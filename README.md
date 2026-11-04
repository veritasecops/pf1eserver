# Pathkeeper 0.2

Python administration and identity foundation for a Pathfinder First Edition platform. FastAPI + Uvicorn + MariaDB. Python 3.13.18 is installed by uv under `.python`; dependencies live in `.venv` and are locked by `uv.lock`. The service never uses the operating system's Python. No nginx, Apache, PHP, Docker, Node.js, or Homebrew dependency exists.

## Implemented

- MariaDB users with Argon2 passwords and public Player sign-up; no server key or default password. Public registration cannot grant privileged roles.
- Revocable server-side sessions, rotated opaque cookies, CSRF protection, throttling, and immediate disabled-account enforcement.
- TOTP enrollment with QR/manual entry, encrypted secrets, replay prevention, one-time hashed recovery codes, and Admin-controlled resets.
- Admin-only user creation, editing, disable/enable, deletion, role assignment, password resets, and activity log. Admins require TOTP. The last active Admin is protected.
- Player: full CRUD on owned characters. Game Master: full CRUD on owned campaigns and characters; can view and edit joined members' characters assigned to owned campaigns. Only a character's owner or an Admin can delete it. Admin: all users, campaigns, and characters.
- Email-bound, single-use, seven-day invitations; revocation and member removal. A GM can create a joined member's character in that GM's campaign. Removing membership detaches the member's characters.
- Basic campaigns and a first-level character wizard with private resumable drafts, server-generated visual d4/d6/d8/d10/d12/d20/d100 rolls, ability generation, core races, core/base/alternate classes, skill budgets, feats, maximum starting HP, starting wealth, starter gear, combat values, descriptions, and spell choices. Third-party class links are excluded. See `/help/character-wizard` for calculations and GM-reviewed choices.
- Searchable public help, printable articles/full manual, and downloadable manual. Help does not query the database.
- Administration → Email Configuration: Application Base URL for all emailed links, Brevo HTTPS API or SMTP relay, encrypted write-only credentials, verified TLS, sender/reply-to identity, enable/disable, explicit test sending, and persisted delivery history. See `/help/email`.
- Automatic welcome/verification, Admin-created account setup, password recovery/change notices, and campaign invitations. One-use expiring account links, unchanged TOTP requirements, session revocation on reset, and an encrypted durable outbox served by `pf1eserver-mail.service`. Queued bodies are erased after the attempt. Ambiguous sends are not retried automatically; no bounce webhook or bulk sending is installed.

## Server

Source: `/opt/pf1eserver`. Origin: `http://10.0.0.154:8080`. Unit: `pf1eserver.service`. Uvicorn runs two workers as the unprivileged `pf1eserver` account. MariaDB listens locally. TLS belongs on the existing external reverse proxy.

Create the first Admin interactively on the server:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage create-admin
```

Sign in through `/login` and enroll TOTP. The installer creates no default credentials. With email configured, Admin-created users receive password setup links and public sign-ups verify their address through a welcome email before opening the workspace. `/forgot-password` provides email recovery while retaining existing MFA. Existing accounts keep their prior access after migration. Without email, account creation retains the private temporary-password/immediate-access fallback.

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

The supplied `manage init` creates the database/tables and a DML-only runtime user using local MariaDB root socket authentication. Existing installations run `sudo .venv/bin/python -m pathkeeper.manage migrate` to apply explicit versioned schema and data migrations. Migration 001 introduces email configuration and delivery history, starts delivery disabled, and preserves existing accounts and campaigns.

Migration 002 adds the Application Base URL, account verification fields, account tokens, and the encrypted outbox. Install `deploy/pf1eserver-mail.service`, reload systemd, and enable `pf1eserver-mail` after migrating. Set the canonical address under Administration → Email Configuration. Link creation does not trust the incoming Host header. Web access logs are disabled; keep tokens out of external proxy logs too. See `/help/account-email` for operation and recovery.

Migration 003 adds structured first-level sheets, character drafts, and dice history while preserving legacy characters. The visual dice renderer uses local canvas code, no graphics service or new runtime dependency. The server owns random results and final calculations. This builder does not automate all archetype/class-feature effects, every feat/spell prerequisite, proficiency, encumbrance, advancement, or multiclassing; those boundaries are visible in the wizard and manual.

Email adapters use Python's standard `smtplib` and `urllib` libraries without an additional provider SDK. `pathkeeper.email_delivery.send_email` takes an immutable settings snapshot and returns accepted/failed/unknown; application callers commit attempt state before running it in a worker thread and persist the result afterward. Brevo endpoint and authentication follow the [official API guide](https://developers.brevo.com/docs/send-a-transactional-email). SMTP TLS modes follow the [Python documentation](https://docs.python.org/3.13/library/smtplib.html).

Pathfinder is a trademark of Paizo Inc. Pathkeeper is an independent project.

Migration 004 removes the retired class-notes and additional-class-skill fields from stored drafts and sheets, and recalculates sheets using each class’s fixed skill list. Any catalog skill can receive ranks; a trained class skill gains +3. Back up, stop the web and mail services, run `sudo .venv/bin/python -m pathkeeper.manage migrate`, then start the services. Draft progress, rank assignments, dice history, and unrelated character data are preserved.

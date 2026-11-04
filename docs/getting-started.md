## What this build includes

Pathkeeper includes MariaDB-backed accounts, authenticator two-factor authentication, Administration, three roles, campaign invitations, automatic account emails, and a guided first-level character wizard. The wizard saves ability scores, race, class, skills, feats, HP, gear, combat values, descriptions, and starting spells, with visual polyhedral dice and resumable drafts. Encounter tools, maps, advancement, multiclassing, and full automation of every class feature remain future work. See the [character wizard guide](/help/character-wizard).

Use the same instance address and account each time. Your saved records live on that server. Accounts on different instances are independent.

## First Admin, without a server key

There is no server-key screen or default password. Public sign-up always creates a Player. A trusted server operator creates the first Admin at an SSH terminal:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage create-admin
```

Enter an email, display name, and password at the prompts. Password entry is hidden and never becomes a command-line argument. Open the normal login page, sign in, and enroll your authenticator. Admins must complete two-factor setup before accessing Administration or campaign data.

## Other users

Select **Create a Player account** on the login page to register. With email configured, confirm your address through the welcome email before opening the workspace. See [sign-up help](/help/signup). Admin-created accounts receive password setup links; if email is unavailable, the Admin shares a temporary password privately. Required authenticator setup still applies. See [account emails and recovery](/help/account-email).

- **Overview** shows your workspace and accessible campaigns.
- **Characters** lists records you are allowed to manage.
- **Campaigns** lists owned or joined campaigns; Admins see all.
- **Administration** is available only to Admins.
- **My profile** manages your display information.
- **Account security** manages passwords, TOTP, and recovery codes.

## Help and saving

Help is available before login and without a database connection. Search all guides, print an article or the full manual, or download the Markdown manual for offline use. Press `/` on a help page to focus search.

Forms save only when submitted. A success message confirms a saved change. Conflicting edits are rejected so a stale window does not silently overwrite a newer campaign or character record.

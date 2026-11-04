## What this build includes

Pathkeeper's Python foundation includes MariaDB-backed accounts, password login, authenticator two-factor authentication, account Administration, three roles, invitations, and basic campaign and character records. Detailed Pathfinder sheets, combat tools, spells, inventory, maps, and dice animation are future work in this rebuild.

Use the same instance address and account each time. Your saved records live on that server. Accounts on different instances are independent.

## First Admin, without a server key

There is no server-key screen or default password. Public sign-up always creates a Player. A trusted server operator creates the first Admin at an SSH terminal:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage create-admin
```

Enter an email, display name, and password at the prompts. Password entry is hidden and never becomes a command-line argument. Open the normal login page, sign in, and enroll your authenticator. Admins must complete two-factor setup before accessing Administration or campaign data.

## Other users

Select **Create a Player account** on the login page to register and sign in immediately. See [sign-up help](/help/signup). An Admin can also create an account and share a temporary password privately. Admin-created accounts must replace that password at sign-in and enroll an authenticator if required. Account emails are not sent automatically. Admins can configure and test [email delivery](/help/email).

- **Overview** shows your workspace and accessible campaigns.
- **Characters** lists records you are allowed to manage.
- **Campaigns** lists owned or joined campaigns; Admins see all.
- **Administration** is available only to Admins.
- **My profile** manages your display information.
- **Account security** manages passwords, TOTP, and recovery codes.

## Help and saving

Help is available before login and without a database connection. Search all guides, print an article or the full manual, or download the Markdown manual for offline use. Press `/` on a help page to focus search.

Forms save only when submitted. A success message confirms a saved change. Conflicting edits are rejected so a stale window does not silently overwrite a newer campaign or character record.

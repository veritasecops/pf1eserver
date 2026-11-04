## Open Administration

Only an active Admin who has completed TOTP enrollment can open Administration. The directory supports name/email search, role and status filters, and pages of 25 users. Counts show total users, active accounts, Admins, and enabled authenticators.

Use the **Email Configuration** tab to connect Brevo or an SMTP relay and send a test. See [email setup](/help/email) for credentials, sender identity, test results, and delivery troubleshooting.

## Create a user

Public sign-up creates Player accounts only. An Admin can promote a registered Player by editing their role, or create an account directly below.

Select **Create user**. Enter display name, unique email, temporary password, and Player, Game Master, or Admin role. Choose whether the account is enabled and whether TOTP is required. Admins always require TOTP, regardless of the checkbox.

With email configured, enabled new accounts receive a one-use password setup link and choose their own password. Temporary passwords are never emailed. If delivery is unavailable, share the temporary password privately; the user must replace it at sign-in. The temporary password is not displayed again after saving. See [account email and recovery](/help/account-email).

## Edit, disable and enable

Open **Manage** next to a user. Edit their details, role, Account enabled setting, or TOTP requirement. Confirm your own Admin password and a fresh authenticator or unused recovery code before saving.

Disabling the account revokes every session immediately. Re-enabling permits a new login with the existing password and authenticator. It does not restore old sessions or erase campaign data. Normal edits revoke the target's other sessions so changed access takes effect promptly.

At least one active Admin must remain. The last active Admin cannot be disabled, deleted, or demoted. Before changing a campaign owner to Player, transfer or delete their owned campaigns; Players cannot own campaigns through normal management.

## Password and authenticator recovery

**Reset password** sets a temporary password, forces a change at sign-in, and revokes sessions. It preserves any existing TOTP authenticator.

**Reset a lost authenticator** removes that authenticator, all recovery codes, and sessions. Type the target email and confirm your own password and second factor. The user must enroll a new authenticator next time. This process does not reveal the old secret.

Each accepted authenticator code works once. Wait for another code or use an unused recovery code for the next sensitive action.

## Delete a user

Deletion requires the target email, your current Admin password, and a fresh factor. It permanently removes the account, its owned characters, and its owned campaigns. Other users' characters in deleted campaigns survive but become unassigned. Memberships and invitations belonging to deleted campaigns disappear.

There is no in-app undo. Disabling is the appropriate choice when you want to suspend access while retaining the user's records.

## Activity log

The Admin-only Activity log shows the latest 100 security and management events. It records actions without passwords, TOTP secrets, recovery codes, or readable invitation tokens. Deleting an account retains audit descriptions while removing the deleted actor reference.

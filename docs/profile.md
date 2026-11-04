## Login and account access

Sign in with the email and password for this instance. Display names are not login names. New users can [create a Player account](/help/signup); an Admin can also create accounts and grant other roles. Disabled accounts cannot sign in, and their existing sessions are revoked.

Passwords use Argon2 hashing. The database stores an irreversible password hash, never the original password. Sessions use random opaque cookies backed by database records. The browser does not store your role as an editable authority.

## Temporary passwords

Accounts created or password-reset through Administration must replace their temporary password at sign-in. Use 12–128 characters and enter the same new password twice. If TOTP is already enabled, confirm a fresh authenticator or recovery code as well.

Changing your password signs out other devices. Your current session is rotated so you can continue without reusing the previous session identifier.

## Profile details

Select your name in the sidebar or open **My profile**. You can edit display name, email address, time zone, and About you. Changing your email requires your current password and, when enabled, a fresh authenticator or recovery code. A new email must be unique. Other sessions are revoked after an email change.

Your role is controlled by an Admin. Profile forms cannot promote you or modify another account. The time zone is saved as a profile preference; activity-log timestamps in this foundation are explicitly shown in UTC.

## Sessions and signing out

Sessions expire after twelve hours or sixty minutes of inactivity by default. Pending second-factor sessions last five minutes. Select Sign out in the header when leaving a shared computer. Session identifiers are rotated at password login, completed MFA, password changes, and enrollment changes.

If your email changes, ask a Game Master to replace invitations sent to the previous email. Invitations match the account's current email exactly after normalization.

Use **Forgot your password?** on the login page to request a reset email. One-use links expire in one hour and retain existing TOTP requirements. Contact an Admin for lost authenticator recovery, or use the server recovery process if you are the only Admin. See [account email and recovery](/help/account-email).

## Enroll your authenticator

Open **Account security**. Enter your current password and select **Set up authenticator**. Scan the QR code with a TOTP-compatible authenticator app. If scanning is unavailable, add a time-based, six-digit account using the displayed manual secret. Confirm the current six-digit code to enable it.

Setup expires after ten minutes. Starting again replaces the pending secret. Two-factor authentication is not enabled until a code is confirmed. Confirming enrollment also signs out other devices and shows ten recovery codes once.

Admins always require two-factor authentication. Players and Game Masters can enroll voluntarily, and an Admin can require it for any account. A required account cannot reach campaign or Administration data until enrollment is complete.

## Sign in with two factors

Enter your email and password on the login page. If TOTP is enabled, the next screen asks for an authenticator or recovery code. Password verification alone does not grant workspace access for an enrolled account. The second-factor step expires after five minutes.

Authenticator codes refresh every 30 seconds. The server tolerates one time step of clock drift in either direction. Each accepted time step can be used only once per account, even across different sessions. If a code was just used, wait for the next one or use an unused recovery code. Keep your phone and server clocks synchronized.

## Recovery codes

Recovery codes replace a TOTP code, not your password. Save the ten codes in a private location when shown; only hashes are stored, so existing codes cannot be displayed again. Each works once. Downloading them creates a local text file on your own computer.

Use **Replace recovery codes** to generate a new set. Confirm your password and a fresh authenticator code or unused recovery code. All old recovery codes stop working after replacement.

## Lost phone or codes

Use a recovery code with your password to sign in, then contact an Admin to reset the authenticator if needed. An Admin's reset removes the old authenticator, recovery codes, and sessions, and requires fresh enrollment at the next sign-in.

If every Admin is locked out, a server operator can use the local recovery commands in [maintenance](/help/maintenance). Resetting a password alone does not remove two-factor authentication.

Optional two-factor authentication can be disabled from Account security with your password and a fresh factor. Required accounts, including all Admins, cannot disable it themselves.

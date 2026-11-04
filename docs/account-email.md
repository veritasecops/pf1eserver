## Automatic account emails

When email delivery is enabled and **Application Base URL** is saved, public sign-up sends a combined welcome and verification email. New registrations must verify their address before opening the workspace. Open the email link, then select **Verify email address**. Simply opening a link does not consume it, which avoids accidental verification by mail scanners.

Verification links expire after 24 hours and work once. **Account → Email verification** lets you request another; the new link invalidates previous verification links. Three resend requests are allowed per account every fifteen minutes. Existing accounts retain access after this upgrade, without being marked verified automatically.

Changing an account email clears verification and sends a new verification link when delivery is available. Old account links stop working. Changing an email still requires the current password and existing authenticator. If a pending address is wrong, contact an Admin to correct it.

## Admin-created accounts

Creating an enabled account in Administration sends a password setup email. The user chooses their own password through the emailed link, which also confirms email ownership. Setup links expire after 24 hours. Temporary passwords are never sent by email. New Admins still enroll TOTP after choosing a password and signing in.

If email delivery is disabled or the Application Base URL is missing, the Admin-created account uses the previous private temporary-password handoff. Disabled accounts receive no setup email.

## Forgot password

Select **Forgot your password?** on the login page and enter your account email. The same response appears whether an active account exists or not. An active matching account receives a one-use reset link valid for one hour. Requests are limited per email address and per IP to prevent abuse.

Open the link, choose and confirm a password of 12–128 characters, and enter a fresh authenticator or unused recovery code if two-factor authentication is enabled. Resetting a password preserves TOTP and does not replace authenticator recovery. Contact an Admin if you have lost both your authenticator and recovery codes.

Completing a reset signs out all existing sessions, invalidates outstanding reset/setup links, confirms ownership of the current email, and sends a password-change notice. Sign in normally afterward; recovery does not sign you in automatically. Changing a password normally or through Administration also invalidates older reset links. Admin password resets send a new reset link when email is available.

## Links and delivery

All emailed links use **Administration → Email Configuration → Application Base URL**, never the incoming browser Host header. Use the address people actually open, such as `https://table.example.com`, without a path, query, or fragment. A trailing slash is removed. Set the external HTTPS origin when the reverse proxy is ready.

The background mail service sends queued messages after the account or invitation is saved. Queued message bodies are encrypted, then erased after the attempt. Account token tables store hashes, not readable tokens. Link expiry, account status, changed email/password, and invitation revocation are checked before sending.

An Admin can check the recipient, purpose, and outcome in Email Configuration. Accepted means the provider accepted the handoff, not confirmed inbox delivery. Unknown or interrupted sends are not retried automatically. Request a fresh account link or create a replacement invitation after checking provider activity.

## Server operations

The worker runs as the unprivileged application service account with the managed Python:

```sh
sudo systemctl status pf1eserver-mail --no-pager
sudo journalctl -u pf1eserver-mail -n 50 --no-pager
```

Migration 002 adds account token and outbox tables, email verification fields, and the Application Base URL. It preserves current email credentials, users, campaigns, and existing access. Apply it with `sudo .venv/bin/python -m pathkeeper.manage migrate` before restarting the app and enabling the worker. Install `deploy/pf1eserver-mail.service` in `/etc/systemd/system`, reload systemd, then enable it with `sudo systemctl enable --now pf1eserver-mail`.

Keep the database and matching instance encryption key in backups. Web access logging is disabled in the supplied Uvicorn unit. Configure the external proxy to keep account-link tokens out of its logs and avoid sharing account links through support logs.

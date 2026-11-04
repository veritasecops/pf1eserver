## Email or password is incorrect

Check that you are using the intended instance and account email. Disabled accounts receive the same generic login error as invalid credentials. New users can [create a Player account](/help/signup). Use **Forgot your password?** to request a reset email. Ask an Admin about disabled accounts or lost authenticators. There is no server key. For missing messages, check spam, the Application Base URL, delivery history, and the mail worker service.

Repeated failures are throttled. Password login allows ten attempts per account and thirty per source address in fifteen minutes. Second-factor and sensitive-action attempts are limited to eight per account in five minutes, independently of source-address changes. A reverse proxy must be trusted explicitly for the application to distinguish real client addresses.

## Authenticator code does not work

Use the correct Pathkeeper entry in your authenticator, retain leading zeros, and keep device/server time synchronized. Codes are six ASCII digits. The same accepted time step cannot be reused, including for another sensitive action. Wait for the next code or use an unused recovery code.

Pending login verification expires after five minutes; enrollment expires after ten. Restart the appropriate flow if expired. If a restore changed `.env` to a different encryption key, enrolled secrets cannot be decrypted; restore the matching key or perform controlled local/Admin recovery.

## Access denied or missing records

Players manage only their own characters. GMs manage their own campaigns and joined members' characters assigned to those campaigns. A membership does not expose all that person's characters. Admins see all records. A removed member's characters detach and become inaccessible to the former GM.

Role changes are server enforced. Disabled users lose all sessions. A forced password change or required authenticator setup redirects to Account security before allowing workspace access. See [roles](/help/roles) for the complete boundaries.

## Invitation fails

Sign in with the exact invited email. Expired, used, and revoked links cannot be accepted. Ask the GM for a replacement. If you have no account, ask an Admin to create one first. Invitations grant membership, not user registration or a global role.

## Session or save error

“Your session changed” means a form's CSRF token no longer matches, commonly after login/logout or a security change in another window. Reload before retrying. A record conflict means another save changed its version; reload and reapply your edit. Copy important unsaved text before reloading.

## Service will not start

Check `systemctl status pf1eserver`, the service journal, `.env` permissions, the managed Python/virtual-environment paths, and MariaDB availability. The service user must be able to traverse the source directory. The storage path must exist because the hardened unit lists it as writable. Port 8080 must be free.

If HTTPS login immediately returns to the login page, verify cookie configuration and the proxy address. A Secure cookie is not sent over direct HTTP. Verify the reverse proxy targets Uvicorn rather than a removed nginx or PHP service.

Help pages work without querying MariaDB. If help loads but login does not, inspect the database URL, socket, restricted database account, and schema initialization before changing frontend files.

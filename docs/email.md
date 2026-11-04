## Open Email Configuration

Sign in as an Admin and open **Administration → Email Configuration**. Only Admins who have completed required password changes and authenticator setup can view settings or send tests.

Choose **Brevo API** or **SMTP Relay**. One provider is active at a time. Both providers' settings remain saved when switching. Delivery starts disabled on a new instance.

This integration supplies a shared delivery service and an explicit test-email action. Sign-up, password recovery, and campaign invitations do not automatically send email in this release. Existing account recovery and invitation-sharing steps still apply.

## Sender identity

Enter the name and email recipients should see. Use an address your provider permits you to send from. Optionally set a Reply-to address for replies. The sender email is required before enabling delivery.

Providers may require sender verification, domain authentication, or account approval. Configure those in your provider account. Provider acceptance does not prove that a message reached an inbox.

## Brevo API

Create an API key in your Brevo account and approve your sender or sending domain for transactional email. Select **Brevo API**, enter the API key, enable delivery, and save.

Use a Brevo API key, not an SMTP key. The application sends over HTTPS to Brevo's fixed transactional endpoint. It does not import contacts, subscribe recipients, or send marketing campaigns.

## Standard SMTP relay

Enter the relay's hostname or IP address and port. Enter the host without a URL, path, or port suffix. Private network relays are supported.

- **STARTTLS** upgrades the connection before authentication or sending. Port 587 is common. Failure to negotiate TLS stops the send.
- **TLS from connection** starts with encryption, commonly on port 465.
- **None** supports a trusted relay without authentication, commonly authorized by this server's IP. The message travels without application-level encryption on that connection.

Enter the username and password or relay key supplied by your provider. Leave the username blank for a relay that authorizes the server by IP. Password authentication requires STARTTLS or TLS. TLS verifies the relay's certificate and hostname; there is no certificate-verification bypass.

Brevo can also be used through the SMTP Relay option with its SMTP settings and SMTP key. API and SMTP keys are different credentials.

## Save, replace, remove, or disable

Saving requires your current Admin password and a fresh authenticator code or unused recovery code. Credentials are encrypted in MariaDB with the instance encryption key. Existing values never appear in the browser, manual, activity log, or delivery history.

Leave a credential field blank to retain its saved value. Enter a new value to replace it. Select the corresponding **Remove saved** checkbox to erase it. Replacing and removing the same credential in one save is rejected.

Clear **Enable email delivery** and save to stop sending while retaining settings. Removing a credential required by the active provider also requires disabling delivery or supplying a replacement. Changes in another window cause a conflict instead of silently overwriting newer settings.

## Send a test

Save and enable the provider, then enter an address in **Test recipient** and select **Send test email**. This sends one fixed message to that address. Unsaved form edits are not used. The test contains no account credentials or authenticator data. An Admin can submit up to five tests every fifteen minutes.

Check **Recent email activity**, the recipient's inbox and spam folder, and the provider's own activity log. Refresh results to see updated history. The page shows the latest 25 attempts; history records the provider, recipient, configuration version, result, and message ID when available. It never stores message bodies or credentials.

- **Accepted** means Brevo or the relay accepted the message. Inbox delivery and later bounces are not tracked here.
- **Failed** means configuration, authentication, connection setup, or a provider rejection prevented an accepted handoff.
- **Unknown** means the connection failed or the provider returned an ambiguous response during delivery. The message may have sent.
- **Pending** means an attempt was recorded but has no final result yet. A service interruption can leave this state behind.

Unknown and pending attempts are not retried automatically. Check provider activity before resending to avoid duplicates. Provider requests have a ten-second timeout for network operations. No background queue, automatic retries, bounce webhooks, or bulk-send feature is installed.

## Upgrade an existing instance

Back up first. Deploy this release's source, apply the additive migration with the managed Python, then restart Uvicorn:

```sh
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage backup
sudo .venv/bin/python -m pathkeeper.manage migrate
sudo systemctl restart pf1eserver
```

Migration 001 adds email settings, delivery history, and migration tracking without altering existing accounts or campaigns. Repeating it preserves settings. Fresh installations apply it during `manage init`. The runtime MariaDB user retains only SELECT, INSERT, UPDATE, and DELETE permissions; schema changes require the trusted server operator.

## Backup and troubleshooting

Back up the database and matching `.env` together. The encryption key protects both authenticator secrets and email credentials. If a credential cannot be decrypted, restore the matching key or re-enter the provider credential. Restart after changing environment configuration.

For Brevo errors, check API key permissions, transactional sending approval, verified sender, and quota. For SMTP errors, check DNS or IP, firewall access from the application server, relay IP authorization, port, TLS mode, certificate, username, and relay key. Provider response bodies are intentionally excluded from application messages because they can contain private information.

If the configuration page says initialization is missing, the server operator must run `manage migrate`. Do not grant schema-changing permissions to the web application's database user.

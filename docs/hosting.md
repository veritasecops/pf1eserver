## Request path

```text
Browser → your existing HTTPS reverse proxy → Uvicorn on port 8080 → MariaDB
```

There is no origin nginx or PHP service. The systemd unit runs the virtual environment's Python directly with Uvicorn. The working directory is `/opt/pf1eserver`, so the application uses that directory's configuration and source.

## Reverse proxy and TLS

Point a dedicated hostname at the existing proxy and forward its root to `http://YOUR_APP_SERVER:8080`. Preserve Host and forward the scheme and client-address headers. Serving this build below a URL subdirectory is not supported.

Uvicorn trusts forwarded headers only from `127.0.0.1` in the supplied unit. For a proxy on another machine, replace `--forwarded-allow-ips=127.0.0.1` with that proxy's actual trusted IP or a narrow trusted range. Do not use an unrestricted wildcard for an origin reachable by other clients.

After browser access uses HTTPS, set `PF_SECURE_COOKIES=true` in `.env` and restart the service. Secure cookies will then stop working over direct plain HTTP, as intended. The default is false to permit initial access to the LAN origin before the proxy is connected. Restrict origin port 8080 to the proxy and trusted administration networks through your network firewall.

## Configuration

`/opt/pf1eserver/.env` contains the database URL and Fernet encryption key. It is owned by root and readable by the service group. Do not publish, commit, paste, or regenerate it during an update. Losing its encryption key prevents decryption of enrolled TOTP secrets.

- `PF_DATABASE_URL` selects the database and connection method. The installer uses the local MariaDB socket and a DML-only account.
- `PF_ENCRYPTION_KEY` encrypts authenticator secrets at rest.
- `PF_SECURE_COOKIES` controls the Secure cookie flag.
- `PF_SESSION_HOURS` defaults to 12 hours of absolute session lifetime.
- `PF_IDLE_MINUTES` defaults to 60 minutes of inactivity.
- `PF_STORAGE` can select a storage directory; the default is `/opt/pf1eserver/storage`.

Restart the service after changing configuration. Keep session-lifetime values positive. If changing the storage path, update systemd's ReadWritePaths and directory ownership too.

## Runtime and filesystem access

Source, `.venv`, and `.python` need read/execute access for the service user but should not be writable by it. The supplied service grants writes only to storage, uses a private temporary directory, and enables systemd filesystem protections. MariaDB writes are handled by MariaDB itself.

Uvicorn access logging is disabled so personal invitation tokens do not enter a routine URL access log. Security-relevant application actions appear in the Admin activity log, while service errors go to the system journal.

The application uses READ COMMITTED database transactions with explicit row locks for one-time factor consumption and administrative safeguards. This avoids stale-snapshot conflicts under MariaDB 11.8's snapshot checking while keeping code use and invitation acceptance atomic. It does not alter the server-wide database isolation setting.

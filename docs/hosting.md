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

Rulebook uploads accept PDFs up to 500 MB. Allow a 501 MB multipart request at `/rulebooks/upload` in the reverse proxy. The application keeps the normal request limit on other routes. Install `poppler-utils` on the application server to render first-page covers. PDFs and covers are kept under `PF_STORAGE/rulebooks`. The reader serves rendered page images through authenticated routes. Original PDF files stay in private server storage.

Landscape first pages containing facing covers use the right-hand front cover
for their thumbnail. Portrait covers keep the whole page. Original PDFs and
reader pages remain unchanged. Run `sudo .venv/bin/python -m pathkeeper.manage
refresh-rulebook-covers` to rebuild existing thumbnails; previous PNGs are saved
under `/var/backups/pf1eserver/covers-<timestamp>` before replacement.

Restart the service after changing configuration. Keep session-lifetime values positive. If changing the storage path, update systemd's ReadWritePaths and directory ownership too.

## Runtime and filesystem access

Source, `.venv`, and `.python` need read/execute access for the service user but should not be writable by it. The supplied service grants writes only to storage, uses a private temporary directory, and enables systemd filesystem protections. MariaDB writes are handled by MariaDB itself.

Uvicorn access logging is disabled so personal invitation tokens do not enter a routine URL access log. Security-relevant application actions appear in the Admin activity log, while service errors go to the system journal.

The application uses READ COMMITTED database transactions with explicit row locks for one-time factor consumption and administrative safeguards. This avoids stale-snapshot conflicts under MariaDB 11.8's snapshot checking while keeping code use and invitation acceptance atomic. It does not alter the server-wide database isolation setting.

## Rulebook search worker

Install English OCR with `sudo apt-get install tesseract-ocr tesseract-ocr-eng`.
Install `deploy/mariadb-rulebook-search.cnf` under
`/etc/mysql/mariadb.conf.d/` before creating the search tables. Restart MariaDB,
then start its dependent Pathkeeper web and mail services. The configuration
indexes two-character terms such as AC and DR and retains rules terms such as
Will. Existing full-text indexes require rebuilding if their token settings change.

Run the database migration, install `deploy/pf1eserver-indexer.service`, then run
`sudo systemctl daemon-reload` and
`sudo systemctl enable --now pf1eserver-indexer`. The service queues existing
rulebooks and processes new uploads in the background. It uses two extraction
slots, up to two CPUs, and a 4 GB memory limit. English OCR runs on pages with
little embedded text. Admins can request OCR of every page when a text layer
produces poor search results.

Use Rulebooks search across accessible files, or the search field in a reader
to search one file. Quoted phrases and two-character terms are supported.
Results link to physical PDF pages. Role and category changes apply immediately.

Admins can view indexing progress and retry or reindex under
`/rulebooks/upload`. Admins can delete a PDF from its library card or management entry after confirming deletion. The database removes its library record, indexing job, and searchable text together. File cleanup removes the PDF and cover immediately when possible and uses a durable worker queue for retry. A partial index includes successfully extracted text and
reports pages that need attention. Reindexing publishes a replacement only
after the run finishes. Queue leases recover interrupted work, with three
attempts before a failure requires an Admin retry.

The database backup includes page text and indexing jobs. The existing storage
backup includes the source PDFs. After restoration, the worker resumes pending
jobs. Stop the indexer alongside the web service when deploying schema changes.

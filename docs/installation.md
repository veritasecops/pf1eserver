## Requirements

This instance uses Python 3.13 managed by uv, a project-local virtual environment, FastAPI, Uvicorn, and MariaDB. It does not use nginx, Apache, PHP, Docker, Node.js, Homebrew, or the operating system's Python interpreter. A separate reverse proxy can terminate TLS.

The supplied installer and service target a Linux server with systemd, MariaDB root socket authentication, and the application installed at `/opt/pf1eserver`. Ubuntu 26.04 is the tested base. On another distribution, adapt package installation, the MariaDB socket, and the service account commands.

## Copy clean source

Obtain the source containing `pathkeeper`, `templates`, `static`, `docs`, `deploy`, `tests`, `pyproject.toml`, `uv.lock`, and `.python-version`. Do not copy a live `.env`, `.venv`, `.python`, database, or storage directory when creating a separate empty instance. A migration of existing users requires both the database and its encryption key; see [maintenance](/help/maintenance).

Prepare the destination, copy source into it, and install MariaDB if needed:

```sh
sudo apt-get update
sudo apt-get install mariadb-server curl ca-certificates poppler-utils
sudo install -d -o "$USER" -m 0750 /opt/pf1eserver
sudo systemctl enable --now mariadb
```

## Install uv and managed Python

Run the following in the source directory as the deployment user, not the service user:

```sh
cd /opt/pf1eserver
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/pathkeeper-uv-install.sh
env UV_INSTALL_DIR=/opt/pf1eserver/.tools UV_NO_MODIFY_PATH=1 sh /tmp/pathkeeper-uv-install.sh
env UV_PYTHON_INSTALL_DIR=/opt/pf1eserver/.python UV_CACHE_DIR=/opt/pf1eserver/.cache/uv .tools/uv python install 3.13.18
env UV_PYTHON_INSTALL_DIR=/opt/pf1eserver/.python UV_CACHE_DIR=/opt/pf1eserver/.cache/uv .tools/uv sync --locked --managed-python
```

The project pins Python 3.13.18 and resolves dependencies through `uv.lock`. Its Python preference permits only managed interpreters. `.venv/bin/python` points to the managed runtime beneath `.python`, independently of `/usr/bin/python3`.

## Create the service account and database

Create the account if it does not already exist, then grant it read access to application source and runtime files:

```sh
sudo useradd --system --user-group --home-dir /opt/pf1eserver --no-create-home --shell /usr/sbin/nologin pf1eserver
sudo chgrp -R pf1eserver /opt/pf1eserver
sudo chmod -R g-w,o-w /opt/pf1eserver
sudo chmod g+rx /opt/pf1eserver
sudo chmod -R g+rX /opt/pf1eserver/.python /opt/pf1eserver/.venv /opt/pf1eserver/pathkeeper /opt/pf1eserver/templates /opt/pf1eserver/static /opt/pf1eserver/docs
cd /opt/pf1eserver
sudo .venv/bin/python -m pathkeeper.manage init
```

Initialization generates `.env`, creates the MariaDB database and restricted application account, creates tables and the administrative transaction guard, and creates writable storage. It creates no user account or default password. Repeating init preserves the encryption key and existing data; it is not a general schema-migration engine.

## Start Uvicorn and create the first Admin

```sh
sudo install -m 0644 deploy/pf1eserver.service /etc/systemd/system/pf1eserver.service
sudo install -m 0644 deploy/pf1eserver-mail.service /etc/systemd/system/pf1eserver-mail.service
sudo systemctl daemon-reload
sudo systemctl enable --now pf1eserver
sudo systemctl enable --now pf1eserver-mail
curl --fail http://127.0.0.1:8080/health
sudo .venv/bin/python -m pathkeeper.manage create-admin
```

Enter the Admin's email, display name, and password at the hidden prompts. Visit `http://YOUR_SERVER:8080/login`, or the configured HTTPS proxy hostname. Sign in normally and complete TOTP enrollment. No server key is used.

## Verify the installation

```sh
cd /opt/pf1eserver
.venv/bin/python -c 'import sys; print(sys.version); print(sys.base_prefix)'
sudo systemctl status pf1eserver --no-pager
sudo .venv/bin/python -m pytest -q
```

The tests use a separate temporary MariaDB database and user, then remove them. They do not seed the live database. Uvicorn listens on port 8080 with two workers and runs as the unprivileged `pf1eserver` user.

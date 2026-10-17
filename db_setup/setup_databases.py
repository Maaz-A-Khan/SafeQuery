"""Create the app database and the Chinook test databases.

    python db_setup/setup_databases.py sqlite      # Chinook in SQLite, no server needed
    python db_setup/setup_databases.py postgres    # app database + Chinook + read-only user

`postgres` connects as a PostgreSQL superuser (default `postgres`; password from
PGPASSWORD or a prompt) and reads the app database name, user and password from
DATABASE_URL in `.env`. Both commands are safe to re-run.
"""

from __future__ import annotations

import argparse
import getpass
import glob
import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"     # downloads and local databases; git-ignored
SQL = HERE / "sql"

RELEASE = "https://github.com/lerocha/chinook-database/releases/download/v1.4.5/"
DOWNLOADS = {
    "Chinook_PostgreSql.sql": "e3fde5c1a5b51a2a91429a702c9ca6e69ba56e6c7f5e112724d70c3d03db695e",
    "Chinook_Sqlite.sqlite": "bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a",
}
RO_USER = "agent_ro"


def download(name: str) -> Path:
    """Fetch a Chinook release file once and check it against the pinned hash."""
    DATA.mkdir(exist_ok=True)
    path = DATA / name
    if not path.exists():
        print(f"Downloading {name} ...")
        urllib.request.urlretrieve(RELEASE + name, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != DOWNLOADS[name]:
        path.unlink()
        sys.exit(f"{name} does not match the expected checksum; deleted it. Re-run to download again.")
    return path


# --- SQLite -------------------------------------------------------------------


def setup_sqlite(args) -> None:
    target = DATA / "chinook.sqlite"
    shutil.copyfile(download("Chinook_Sqlite.sqlite"), target)
    with sqlite3.connect(target) as conn:
        conn.executescript((SQL / "seed_sensitive.sql").read_text(encoding="utf-8"))
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    conn.close()
    print(f"\nChinook (SQLite) ready: {target} ({tables} tables)")
    print("Connection string (read-only file mode):")
    print(f"  sqlite:///file:{target.as_posix()}?mode=ro&uri=true")


# --- PostgreSQL ---------------------------------------------------------------


def find_psql(explicit: str | None) -> str:
    candidates = [explicit, shutil.which("psql")]
    candidates += sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\psql.exe"), reverse=True)
    for c in candidates:
        if c and Path(c).exists():
            return c
    sys.exit("psql not found. Add PostgreSQL's bin folder to PATH or pass --psql.")


class Psql:
    def __init__(self, exe: str, host: str, port: str, user: str, password: str):
        self.exe, self.base = exe, ["-h", host, "-p", port, "-U", user, "-v", "ON_ERROR_STOP=1", "-q"]
        self.env = {**os.environ, "PGPASSWORD": password}

    def run(self, db: str, *, file: Path | None = None, sql: str | None = None,
            variables: dict | None = None, capture: bool = False) -> str:
        cmd = [self.exe, *self.base, "-d", db]
        for key, value in (variables or {}).items():
            cmd += ["-v", f"{key}={value}"]
        cmd += ["-f", str(file)] if file else ["-tAc", sql]
        done = subprocess.run(cmd, env=self.env, text=True, capture_output=capture)
        if done.returncode != 0:
            sys.exit(f"psql failed ({done.returncode}): {(done.stderr or '').strip()}")
        return (done.stdout or "").strip()


def setup_postgres(args) -> None:
    import dj_database_url
    from dotenv import load_dotenv

    load_dotenv(HERE.parent / ".env")
    if not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL is missing. Copy .env.example to .env and fill it in first.")
    app = dj_database_url.parse(os.environ["DATABASE_URL"])
    host, port = app.get("HOST") or "localhost", str(app.get("PORT") or 5432)

    admin_password = os.environ.get("PGPASSWORD") or getpass.getpass(f"Password for PostgreSQL user {args.admin}: ")
    psql = Psql(find_psql(args.psql), host, port, args.admin, admin_password)

    print(f"1/4 App database {app['NAME']} owned by {app['USER']}")
    psql.run("postgres", file=SQL / "app_database.sql",
             variables={"app_user": app["USER"], "app_password": app["PASSWORD"], "app_db": app["NAME"]})

    exists = psql.run("postgres", sql="SELECT 1 FROM pg_database WHERE datname = 'chinook'", capture=True)
    if exists and not args.reload:
        print("2/4 Chinook already loaded (use --reload to drop and reload it)")
    else:
        print("2/4 Loading Chinook (drops and recreates the `chinook` database) ...")
        psql.run("postgres", file=download("Chinook_PostgreSql.sql"), capture=True)

    print("3/4 Seeding the user_credentials table")
    psql.run("chinook", file=SQL / "seed_sensitive.sql")

    ro_password = args.ro_password or secrets.token_urlsafe(18)
    print(f"4/4 Read-only user {RO_USER}")
    psql.run("chinook", file=SQL / "readonly_user.sql",
             variables={"ro_user": RO_USER, "ro_password": ro_password})

    ro = Psql(psql.exe, host, port, RO_USER, ro_password)
    tracks = ro.run("chinook", sql="SELECT COUNT(*) FROM track", capture=True)
    write = subprocess.run([ro.exe, *ro.base, "-d", "chinook", "-tAc", "DELETE FROM genre WHERE false"],
                           env=ro.env, text=True, capture_output=True)
    if write.returncode == 0:
        sys.exit(f"STOP: {RO_USER} was able to write. Do not use this account.")
    print(f"\nChecked: {RO_USER} reads {tracks} tracks and its write was refused.")
    print("Connection string for the Connect page:")
    print(f"  postgresql+psycopg://{RO_USER}:{quote(ro_password, safe='')}@{host}:{port}/chinook")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sqlite", help="Chinook as a local SQLite file").set_defaults(func=setup_sqlite)
    pg = sub.add_parser("postgres", help="app database, Chinook and the read-only user")
    pg.add_argument("--admin", default="postgres", help="PostgreSQL superuser (default: postgres)")
    pg.add_argument("--psql", help="path to psql if it is not on PATH")
    pg.add_argument("--reload", action="store_true", help="drop and reload Chinook")
    pg.add_argument("--ro-password", help=f"password for {RO_USER} (default: generated)")
    pg.set_defaults(func=setup_postgres)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

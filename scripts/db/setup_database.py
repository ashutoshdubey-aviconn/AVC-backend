#!/usr/bin/env python
"""Create the local PostgreSQL database and user for development.

    python scripts/db/setup_database.py

Reads DB_HOSTNAME (database name), DB_USERNAME and DB_PASSWORD from
warehouse/.env (see warehouse/.env.example). Connects as the ``postgres``
superuser, with PGPASSWORD from the environment if set, else trust auth.
Drops and recreates the database and user, so run it only on a dev machine.
"""

import os
import sys
from pathlib import Path

import psycopg2
from decouple import Config, RepositoryEnv
from psycopg2 import sql

ENV_FILE = Path(__file__).resolve().parents[2] / "warehouse" / ".env"


def connect(database):
    params = dict(host="localhost", port=5432, database=database, user="postgres")
    try:
        return psycopg2.connect(password=os.environ.get("PGPASSWORD", ""), **params)
    except psycopg2.OperationalError:
        return psycopg2.connect(**params)  # trust auth


def main():
    config = Config(RepositoryEnv(str(ENV_FILE)))
    db_name = config("DB_HOSTNAME", default="warehouse")
    db_user = config("DB_USERNAME")
    db_password = config("DB_PASSWORD")

    conn = connect("postgres")
    conn.autocommit = True
    cur = conn.cursor()
    print("Connected to PostgreSQL as postgres")
    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {};").format(sql.Identifier(db_name)))
    cur.execute(sql.SQL("DROP USER IF EXISTS {};").format(sql.Identifier(db_user)))
    cur.execute(
        sql.SQL("CREATE USER {} WITH PASSWORD %s CREATEDB;").format(sql.Identifier(db_user)),
        (db_password,),
    )
    cur.execute(
        sql.SQL("CREATE DATABASE {} WITH OWNER {};").format(
            sql.Identifier(db_name), sql.Identifier(db_user)
        )
    )
    cur.close()
    conn.close()

    conn = connect(db_name)
    conn.autocommit = True
    cur = conn.cursor()
    user = sql.Identifier(db_user)
    for statement in (
        "GRANT ALL PRIVILEGES ON SCHEMA public TO {};",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {};",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {};",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO {};",
    ):
        cur.execute(sql.SQL(statement).format(user))
    cur.close()
    conn.close()
    print(f"Database '{db_name}' and user '{db_user}' created (password from {ENV_FILE}).")


if __name__ == "__main__":
    try:
        main()
    except psycopg2.OperationalError as error:
        print(f"Connection failed: {error}")
        print("Make sure PostgreSQL is running and accessible at localhost:5432")
        sys.exit(1)

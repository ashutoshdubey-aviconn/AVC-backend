-- Create the local development database and user.
-- The password is passed in, never stored here:
--   sudo -u postgres psql -v db_password="$DB_PASSWORD" -f scripts/db/setup_db.sql
-- (DB_PASSWORD from warehouse/.env; scripts/db/setup_database.py does the same.)

CREATE USER aviconn WITH PASSWORD :'db_password' CREATEDB;
CREATE DATABASE warehouse WITH OWNER aviconn;
GRANT ALL PRIVILEGES ON DATABASE warehouse TO aviconn;

\c warehouse

GRANT ALL PRIVILEGES ON SCHEMA public TO aviconn;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO aviconn;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO aviconn;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO aviconn;

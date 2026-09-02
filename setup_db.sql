-- Create the database user
CREATE USER aviconn WITH PASSWORD '1V3asem2025';

-- Create the database
CREATE DATABASE warehouse WITH OWNER aviconn;

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE warehouse TO aviconn;

-- Connect to the database and set permissions
\c warehouse

-- Grant schema permissions
GRANT ALL PRIVILEGES ON SCHEMA public TO aviconn;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO aviconn;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO aviconn;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO aviconn;

-- Ensure user can create tables
ALTER ROLE aviconn CREATEDB;

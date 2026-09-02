#!/usr/bin/env python
import psycopg2
from psycopg2 import sql
import sys

# Try to connect to the default database first
try:
    # Connect as postgres (with password)
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="postgres",
            user="postgres",
            password="postgres"
        )
    except:
        # Try without password (trust auth)
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="postgres",
            user="postgres"
        )
    conn.autocommit = True
    cur = conn.cursor()
    
    print("Connected to PostgreSQL as postgres")
    
    # Drop existing user and database if they exist (for idempotency)
    try:
        cur.execute("DROP DATABASE IF EXISTS warehouse;")
        print("Dropped existing 'warehouse' database")
    except Exception as e:
        print(f"Note: {e}")
    
    try:
        cur.execute("DROP USER IF EXISTS aviconn;")
        print("Dropped existing 'aviconn' user")
    except Exception as e:
        print(f"Note: {e}")
    
    # Create the user
    cur.execute(sql.SQL("CREATE USER {} WITH PASSWORD %s;").format(
        sql.Identifier("aviconn")
    ), ("1V3asem2025",))
    print("Created user 'aviconn'")
    
    # Create the database
    cur.execute(sql.SQL("CREATE DATABASE {} WITH OWNER {};").format(
        sql.Identifier("warehouse"),
        sql.Identifier("aviconn")
    ))
    print("Created database 'warehouse'")
    
    # Grant privileges
    cur.execute("GRANT ALL PRIVILEGES ON DATABASE warehouse TO aviconn;")
    print("Granted privileges to aviconn")
    
    # Connect to the warehouse database and set more permissions
    cur.close()
    conn.close()
    
    # Connect to warehouse database
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="warehouse",
            user="postgres",
            password="postgres"
        )
    except:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="warehouse",
            user="postgres"
        )
    conn.autocommit = True
    cur = conn.cursor()
    
    cur.execute("GRANT ALL PRIVILEGES ON SCHEMA public TO aviconn;")
    cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO aviconn;")
    cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO aviconn;")
    cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO aviconn;")
    print("Set schema permissions")
    
    cur.close()
    conn.close()
    
    print("\n✓ Database setup completed successfully!")
    print("Database: warehouse")
    print("User: aviconn")
    print("Password: 1V3asem2025")
    
except psycopg2.OperationalError as e:
    print(f"✗ Connection failed: {e}")
    print("\nMake sure PostgreSQL service is running and accessible at localhost:5432")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

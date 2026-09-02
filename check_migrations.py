#!/usr/bin/env python
import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
sys.path.insert(0, 'c:\\Users\\dubey\\Downloads\\AVC-backend-DgFuel-v1.0')
django.setup()

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# Get the migration executor
executor = MigrationExecutor(connection)

# Print the current migration state
print("=== Current Migration State ===")
print("\nApplied Migrations:")
for app, migrations in executor.applied_migrations.items():
    if app.startswith('wareApp'):
        print(f"{app}: {len(migrations)} migrations")
        for migration in list(migrations)[-5:]:  # Show last 5
            print(f"  - {migration}")

print("\nUnapplied Migrations:")
unapplied = executor.migration_plan(executor.loader.graph.leaf_nodes())
for app, migration in unapplied:
    print(f"{app}: {migration}")

print("\n=== Attempting to reset and reapply migrations ===")
# Try to mark migrations as applied without running them
from django.core.management import call_command
try:
    call_command('migrate', 'wareApp', '0003_auto_20221216_1108', verbosity=2)
    print("\nMigrations up to 0003_auto_20221216_1108 applied")
except Exception as e:
    print(f"Error: {e}")

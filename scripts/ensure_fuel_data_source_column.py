#!/usr/bin/env python3
import os
import sys

proj_root = "/home/ashutosh-dubey/django_project"
sys.path.insert(0, proj_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()

from django.db import connection

TABLE = "wareApp_dgfuelconsumptiondata"
COLUMN = "fuel_data_source"

with connection.cursor() as cursor:
    # Check if column exists
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        [TABLE.lower(), COLUMN],
    )
    row = cursor.fetchone()
    if row:
        print("Column already exists:", COLUMN)
    else:
        print("Adding column", COLUMN, "to", TABLE)
        try:
            cursor.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN {COLUMN} varchar(32);')
            print("Column added successfully")
        except Exception as e:
            print("Failed to add column:", e)

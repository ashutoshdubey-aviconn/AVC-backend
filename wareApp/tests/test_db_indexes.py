"""Index changes of 2026-11-06 (migrations 0111, 0112): a site lookup is still
served by an index on every table, and hourly readings are indexed by aisle +
time."""

from django.db import connection
from django.test import TestCase

SITE_COLUMNS = (
    ("wareApp_rawloaddata", "site_id"),
    ("wareApp_hourlyloaddata", "site_id"),
    ("wareApp_hourlysitereading", "associated_Site_id"),
    ("wareApp_dgfuelconsumptiondata", "site_id"),
)


def indexes(table):
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table)


class IndexTests(TestCase):
    def test_every_site_column_still_leads_an_index(self):
        for table, column in SITE_COLUMNS:
            with self.subTest(table=table):
                leading = [
                    name for name, info in indexes(table).items()
                    if info["index"] and info["columns"] and info["columns"][0] == column
                ]
                self.assertTrue(leading, f"{table}.{column} has no index starting with it")

    def test_single_site_index_dropped_where_covered(self):
        for table, column in SITE_COLUMNS:
            with self.subTest(table=table):
                found = indexes(table).values()
                covered = any(i["index"] and len(i["columns"]) >= 2 and i["columns"][0] == column for i in found)
                single = any(i["index"] and not i["unique"] and not i["primary_key"] and i["columns"] == [column]
                             for i in found)
                if covered:
                    self.assertFalse(single, f"{table}.{column}: redundant single index still there")

    def test_hourly_readings_indexed_by_aisle_and_time(self):
        found = indexes("wareApp_hourlysitereading")
        self.assertEqual(found["idx_hourly_aisle_reading_from"]["columns"], ["aisle_group_id", "reading_from"])
        self.assertFalse(any(i["index"] and i["columns"] == ["aisle_group_id"] for i in found.values()))

"""Index and foreign-key changes of 2026-11-06 (migrations 0111-0113): a site lookup is still
served by an index on every table, and hourly readings are indexed by aisle +
time."""

from datetime import datetime

from django.db import connection
from django.test import TestCase

from wareApp.models import AisleGroup, DgFuelConsumptionData, HourlySiteReading, RawLoadData, Site

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


TELEMETRY_TABLES = (
    "wareApp_rawloaddata", "wareApp_hourlyloaddata", "wareApp_dailyloaddata",
    "wareApp_mainsdgloaddata", "wareApp_dgfuelconsumptiondata",
)


class TelemetryForeignKeyTests(TestCase):
    """Telemetry tables have no database-level foreign keys (migration 0113);
    business tables keep theirs; Django still cascades deletes."""

    def test_no_database_foreign_keys_on_telemetry_tables(self):
        for table in TELEMETRY_TABLES:
            with self.subTest(table=table):
                self.assertFalse([n for n, i in indexes(table).items() if i["foreign_key"]])
        self.assertTrue([n for n, i in indexes("wareApp_hourlysitereading").items() if i["foreign_key"]])

    def test_columns_still_indexed(self):
        for table in ("wareApp_rawloaddata", "wareApp_mainsdgloaddata"):
            with self.subTest(table=table):
                columns = {tuple(i["columns"][:1]) for i in indexes(table).values() if i["index"]}
                self.assertIn(("aisle_group_id",), columns)
                self.assertIn(("site_id",), columns)

    def test_django_still_cascades_and_sets_null(self):
        site = Site.objects.create(site_name="FK site", site_type=2)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="A1")
        RawLoadData.objects.create(site=site, aisle_group=aisle, load_data=1.0, created=datetime(2026, 11, 6))
        fuel = DgFuelConsumptionData.objects.create(site=site, aisle_group=aisle, epoch_time="1")
        HourlySiteReading.objects.create(associated_Site=site, aisle_group=aisle, leg_id="1",
                                         reading_from=datetime(2026, 11, 6), reading_to=datetime(2026, 11, 6, 0, 59))
        aisle.delete()
        self.assertFalse(RawLoadData.objects.exists())  # CASCADE, done by Django
        fuel.refresh_from_db()
        self.assertIsNone(fuel.aisle_group_id)  # SET_NULL, done by Django

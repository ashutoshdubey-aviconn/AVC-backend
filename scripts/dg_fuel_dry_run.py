#!/usr/bin/env python3
"""Run one read-only DG-fuel level collection cycle.

Set LOCONAV_API_KEY, ROADCAST_USERNAME, and ROADCAST_PASSWORD in the service
environment before running this script. It never creates or updates database
records.
"""

import os
import sys

import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")

import django

django.setup()

from wareApp.dg_fuel.poller import collect_level_cycle
from wareApp.models import Site


def required_environment(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def fetch_loconav(vehicle_number):
    response = requests.get(
        "https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels",
        params={"vehicle_number": vehicle_number},
        headers={"User-Authentication": required_environment("LOCONAV_API_KEY")},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_roadcast():
    response = requests.get(
        "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api",
        params={
            "username": required_environment("ROADCAST_USERNAME"),
            "password": required_environment("ROADCAST_PASSWORD"),
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    required_environment("LOCONAV_API_KEY")
    required_environment("ROADCAST_USERNAME")
    required_environment("ROADCAST_PASSWORD")
    sites = Site.objects.filter(dg_fuel_system_installed=True).order_by("id")
    print(collect_level_cycle(sites, fetch_loconav, fetch_roadcast, dry_run=True))
#!/usr/bin/env python3
"""Run project unit tests and Django app tests sequentially.

This avoids the unittest/Django discovery collision by running unit tests
(in `unit_tests/`) separately from Django app tests.
"""

import os
import subprocess
import sys

venv_python = "./virtualwarehouse/bin/python3"
if not os.path.exists(venv_python):
    venv_python = sys.executable


def run(cmd, env=None):
    print(f">>> {cmd}")
    rc = subprocess.call(cmd, shell=True, env=env)
    if rc != 0:
        raise SystemExit(rc)


if __name__ == "__main__":
    # Run unit tests
    run(f"{venv_python} -m unittest discover -v unit_tests")

    # Run Django tests (limit to wareApp to avoid discovery issues)
    env = os.environ.copy()
    env["ENV"] = "CI"
    env["DJANGO_SETTINGS_MODULE"] = "warehouse.test_settings"
    run(f"{venv_python} manage.py test wareApp.tests -v 2", env=env)

    print("All tests passed.")

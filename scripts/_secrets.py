"""Third-party API credentials for the helper scripts.

Read from warehouse/.env (the same keys the app uses); nothing secret is
stored in the scripts themselves.
"""

import base64
from pathlib import Path

from decouple import Config, RepositoryEnv

_config = Config(RepositoryEnv(str(Path(__file__).resolve().parents[1] / "warehouse" / ".env")))

ROADCAST_PULL_API_URL = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api"


def loconav_auth_headers():
    return {"User-Authentication": _config("LOCONAV_API_TOKEN", default="")}


def roadcast_pull_params():
    return {
        "username": _config("ROADCAST_PULL_USERNAME", default=""),
        "password": _config("ROADCAST_PULL_PASSWORD", default=""),
    }


def roadcast_auth_headers():
    params = roadcast_pull_params()
    token = base64.b64encode(f"{params['username']}:{params['password']}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

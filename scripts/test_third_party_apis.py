import os, sys, time

package_path = os.path.join(os.path.dirname(__file__), "..")
sys.path.append(package_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()
import requests
from datetime import datetime, timedelta
from wareApp.models import Site


def request_json(url, headers=None, params=None, timeout=10):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        try:
            return r.status_code, r.json(), r.text[:1000]
        except Exception:
            return r.status_code, None, r.text[:1000]
    except Exception as e:
        return None, None, str(e)


def sample_sites(limit=5):
    qs = Site.objects.filter(partner_dg_fuel_id__isnull=False).exclude(
        partner_dg_fuel_id=""
    )[:limit]
    return list(qs)


def test_loconav(vehicle):
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    now = datetime.now()
    start = int((now - timedelta(hours=24)).timestamp())
    end = int(now.timestamp())
    urls = {
        "current_levels": f"https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels?vehicle_number={vehicle}",
        "alerts": f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle}&start_time={start}&end_time={end}",
        "interval": f"https://marketplace.loconav.com/api/v1/vehicles/fuel/interval_data?start_time={start}&end_time={end}&interval=5&vehicle_number={vehicle}",
    }
    out = {}
    for k, u in urls.items():
        status, j, raw = request_json(u, headers=headers)
        out[k] = {
            "status": status,
            "has_json": j is not None,
            "sample": (
                j
                if isinstance(j, dict) and len(str(j)) < 400
                else (j[:1] if isinstance(j, list) else None)
            ),
            "raw": raw,
        }
    return out


def test_roadcast(device_imei):
    # uses two endpoints seen in code
    headers1 = {
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3bHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.Fwn08jciwxlm659ZYEfq1LpQBAf2fddUZ9zrjmrzcmU"
    }
    url_pull = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234"
    status_p, j_p, raw_p = request_json(url_pull, headers=headers1)
    # pull_fuel_report may require vehicle and date range
    headers2 = {"Authorization": "Basic QXZpY29ubjpBYmNAMTIzNA=="}
    now = datetime.now()
    start_date = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    end_date = now.strftime("%Y-%m-%dT%H:%M:%S")
    url_report = "https://test-track.roadcast.net/api/v1/auth/pull_fuel_report"
    params = {"device_imei": device_imei, "from_time": start_date, "to_time": end_date}
    status_r, j_r, raw_r = request_json(url_report, headers=headers2, params=params)
    return {
        "pull_api": {
            "status": status_p,
            "has_json": j_p is not None,
            "sample": j_p if isinstance(j_p, dict) and len(str(j_p)) < 400 else None,
            "raw": raw_p,
        },
        "pull_fuel_report": {
            "status": status_r,
            "has_json": j_r is not None,
            "sample": j_r if isinstance(j_r, dict) and len(str(j_r)) < 400 else None,
            "raw": raw_r,
        },
        "params": params,
    }


if __name__ == "__main__":
    sites = sample_sites(6)
    if not sites:
        print("No sites with partner_dg_fuel_id found")
        sys.exit(0)
    for s in sites:
        vid = s.partner_dg_fuel_id
        print("\n=== Site:", s.id, "vehicle:", vid, "name:", s.site_name)
        loc = test_loconav(vid)
        print(
            "Loconav current_levels status:",
            loc["current_levels"]["status"],
            "has_json:",
            loc["current_levels"]["has_json"],
        )
        print(
            "Loconav alerts status:",
            loc["alerts"]["status"],
            "has_json:",
            loc["alerts"]["has_json"],
        )
        print(
            "Loconav interval status:",
            loc["interval"]["status"],
            "has_json:",
            loc["interval"]["has_json"],
        )
        ro = test_roadcast(vid)
        print(
            "Roadcaste pull_api status:",
            ro["pull_api"]["status"],
            "has_json:",
            ro["pull_api"]["has_json"],
        )
        print(
            "Roadcaste pull_fuel_report status:",
            ro["pull_fuel_report"]["status"],
            "has_json:",
            ro["pull_fuel_report"]["has_json"],
        )
        # print small raw samples
        print(
            "Loconav current_levels sample/raw:",
            loc["current_levels"]["sample"] or loc["current_levels"]["raw"],
        )
        print("Roadcaste pull_api raw snippet:", ro["pull_api"]["raw"][:300])
        time.sleep(0.2)

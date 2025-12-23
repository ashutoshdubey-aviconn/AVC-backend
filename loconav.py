import requests, time
from datetime import datetime, timedelta

def fetch_loconav_fuel_data_for_date(vehicle_number, date, token=None):
    # Convert the start and end time to Unix timestamp for the given date
    start_dt = datetime.strptime(date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    start_timestamp = int(start_dt.timestamp())
    end_timestamp = int(end_dt.timestamp())

    url = "https://marketplace.loconav.com/api/v1/vehicles/fuel/interval_data"
    params = {
        'vehicle_number': vehicle_number,
        'start_time': start_timestamp,
        'end_time': end_timestamp
    }
    headers = {
        'Content-Type': 'application/json'
    }
    if token:
        headers['User-Authentication'] = f'51uKh_YaL72s7zhx6bwZ'

    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching for {date}: {response.status_code}")
        return None

# Example Usage:
vehicle_number = "DCGenerator-01"
start_date = datetime(2025, 6, 1)
end_date = datetime(2025, 6, 4)  # inclusive of 3 days
token = True  # put your token here if needed

date = start_date
while date <= end_date:
    date_str = date.strftime("%Y-%m-%d")
    data = fetch_loconav_fuel_data_for_date(vehicle_number, date_str, token)
    print(f"Data for {date_str}:", data)
    date += timedelta(days=1)
    time.sleep(3)


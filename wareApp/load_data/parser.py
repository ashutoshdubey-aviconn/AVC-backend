from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LoadReading:
    load_value: float
    leg_id: str
    meter_number: str
    created: datetime
    epoch_time: str


def parse_load_data_message(message: str) -> LoadReading:
    load_data = message.split("'")[1].split(",")
    load_value = float(load_data[0].split(":")[1])
    leg_id = load_data[1].split(":")[1]
    meter_number = load_data[2].split(":")[1]
    created = datetime.strptime(
        ":".join(load_data[3].split(":")[1:]), "%Y-%m-%d %H:%M:%S.%f"
    )
    epoch_time = load_data[4].split(":")[1]

    return LoadReading(
        load_value=load_value,
        leg_id=leg_id,
        meter_number=meter_number,
        created=created,
        epoch_time=epoch_time,
    )

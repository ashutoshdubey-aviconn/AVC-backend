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
    payload = message.strip()
    if payload.startswith("b'") and payload.endswith("'"):
        payload = payload[2:-1]

    fields = {}
    for field in payload.split(","):
        key, separator, value = field.partition(":")
        if not separator:
            raise ValueError(f"Invalid LoadData field: {field!r}")
        fields[key.strip().lower().replace("_", "")] = value.strip()

    def value_for(*keys):
        for key in keys:
            value = fields.get(key)
            if value is not None:
                return value
        raise ValueError(f"Missing LoadData field: {keys[0]}")

    load_value = float(value_for("loadvalue"))
    leg_id = value_for("legid")
    meter_number = value_for("meternumber")
    created = datetime.fromisoformat(value_for("datetime", "date"))
    epoch_time = value_for("epochtime", "epoch")

    return LoadReading(
        load_value=load_value,
        leg_id=leg_id,
        meter_number=meter_number,
        created=created,
        epoch_time=epoch_time,
    )

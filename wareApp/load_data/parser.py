from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LoadReading:
    """One parsed LoadData packet: load value, leg, meter number, time and epoch.

    Origin: Ashu
    """
    load_value: float
    leg_id: str
    meter_number: str
    created: datetime
    epoch_time: str


def parse_load_data_message(message: str) -> LoadReading:
    """Parses a LoadData MQTT payload (key:value pairs separated by commas) into a LoadReading; raises
    ValueError for a missing field.

    Origin: Ashu
    """
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
        """First of the given keys that is present in the packet; ValueError when none is.

        Origin: Ashu
        """
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

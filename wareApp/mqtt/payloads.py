"""Shared helpers for parsing gateway MQTT payloads."""


def split_paired_lists(slots_text, values_text, payload_kind):
    """Split the comma-separated slot and value lists of a recovery payload.

    Gateways send lists such as ``"t1,t2,"`` / ``"1.0,ERROR404,"``. Empty items
    (trailing commas) are dropped. The two lists must line up one-to-one: a
    length mismatch means the payload is corrupt, and silently truncating it
    with ``zip`` would store values against the wrong hours.
    """
    slots = [value for value in slots_text.split(",") if value]
    values = [value for value in values_text.split(",") if value]
    if len(slots) != len(values):
        raise ValueError(
            f"{payload_kind} recovery payload has {len(slots)} slots "
            f"but {len(values)} values"
        )
    return slots, values

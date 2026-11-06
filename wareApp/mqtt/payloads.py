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


def _payload_text(message):
    """Return the payload as text, unwrapping a ``str(bytes)`` artefact (``b'...'``)."""
    payload = message.decode("utf-8") if isinstance(message, bytes) else str(message)
    payload = payload.strip()
    if payload.startswith("b'") and payload.endswith("'"):
        payload = payload[2:-1]
    return payload


def _normalized_key(key):
    return key.strip().lower().replace("_", "").replace("-", "")


class KeyValuePayload:
    """A gateway ``key:value,key:value`` payload (consumption, load, FIREALARM, SupplyTime).

    Keys are matched case-insensitively and without ``_`` / ``-``, so
    ``Meter_Number`` and ``meternumber`` are the same field. Errors are
    ``ValueError`` with ``Invalid <kind> field`` / ``Missing <kind> field``
    messages, which the handlers store as dead letters.
    """

    def __init__(self, fields, kind):
        self.fields = fields
        self.kind = kind

    @classmethod
    def parse(cls, message, kind, *, strip_value_quotes=False):
        fields = {}
        for field in _payload_text(message).split(","):
            key, separator, value = field.partition(":")
            if not separator:
                raise ValueError(f"Invalid {kind} field: {field!r}")
            value = value.strip()
            fields[_normalized_key(key)] = value.strip("'") if strip_value_quotes else value
        return cls(fields, kind)

    def __contains__(self, key):
        return key in self.fields

    def get(self, *keys):
        """Return the value of the first key present; ``keys`` are aliases."""
        for key in keys:
            if key in self.fields:
                return self.fields[key]
        raise ValueError(f"Missing {self.kind} field: {keys[0]}")

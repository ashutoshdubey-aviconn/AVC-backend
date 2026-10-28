"""Batched writes for recovery payloads (many hours/days in one message).

A recovery message can carry dozens of slots. Writing them one ``UPDATE`` /
``INSERT`` at a time, each in its own autocommit transaction, cost ~2-3 ms
per slot on main (one WAL flush per row). Here a whole message is one
``SELECT``, at most one ``bulk_update`` and one ``bulk_create`` per 500 rows,
inside the caller's transaction (a single commit).

Slots whose stored values are already identical are left untouched
(``unchanged``): a gateway that re-sends the same recovery (site 125 re-sent
26 days every ~40 s) then costs one SELECT instead of ~600 row updates.
"""

import time
from collections import defaultdict
from typing import NamedTuple

BULK_BATCH_SIZE = 500


class SlotWriteResult(NamedTuple):
    """Slot keys per outcome (used for counts and for the log line)."""

    updated: list
    created: list
    skipped: list
    update_ms: float = 0.0
    create_ms: float = 0.0
    unchanged: tuple = ()

    @property
    def changed(self):
        """Keys of slots that were created or updated."""
        return [*self.created, *self.updated]


def upsert_slots(queryset, key_of, slots, update_fields, build_row, should_update=None):
    """Update existing rows or create new ones for every slot.

    ``queryset``      rows that may match a slot (already narrowed to the slots).
    ``key_of(row)``   slot key of an existing row.
    ``slots``         ordered ``{key: {field: value}}``; a later duplicate key
                      wins, matching the old one-row-at-a-time behaviour.
    ``build_row``     ``build_row(key, values)`` -> unsaved model instance.
    ``should_update`` optional ``should_update(existing_rows, values)`` guard;
                      when it returns False the slot is left untouched.

    Returns a ``SlotWriteResult`` with the slot keys that were updated,
    created, skipped (guard) and unchanged (values already stored).
    """
    model = queryset.model
    existing = defaultdict(list)
    for row in queryset:
        existing[key_of(row)].append(row)

    to_update, to_create = [], []
    updated, created, skipped, unchanged = [], [], [], []
    for key, values in slots.items():
        rows = existing.get(key)
        if not rows:
            to_create.append(build_row(key, values))
            created.append(key)
            continue
        if should_update is not None and not should_update(rows, values):
            skipped.append(key)
            continue
        if all(
            getattr(row, field) == value
            for row in rows
            for field, value in values.items()
        ):
            unchanged.append(key)
            continue
        for row in rows:
            for field, value in values.items():
                setattr(row, field, value)
            to_update.append(row)
        updated.append(key)

    update_ms = create_ms = 0.0
    if to_update:
        started = time.perf_counter()
        model.objects.bulk_update(to_update, update_fields, batch_size=BULK_BATCH_SIZE)
        update_ms = (time.perf_counter() - started) * 1000
    if to_create:
        started = time.perf_counter()
        model.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
        create_ms = (time.perf_counter() - started) * 1000
    return SlotWriteResult(updated, created, skipped, update_ms, create_ms, tuple(unchanged))

"""Batched writes for recovery payloads (many hours/days in one message).

A recovery message can carry dozens of slots. Writing them one ``UPDATE`` /
``INSERT`` at a time, each in its own autocommit transaction, cost ~2-3 ms
per slot on main (one WAL flush per row). Here a whole message is one
``SELECT``, at most one ``bulk_update`` and one ``bulk_create`` per 500 rows,
inside the caller's transaction (a single commit).
"""

from collections import defaultdict

BULK_BATCH_SIZE = 500


def upsert_slots(queryset, key_of, slots, update_fields, build_row, should_update=None):
    """Update existing rows or create new ones for every slot.

    ``queryset``      rows that may match a slot (already narrowed to the slots).
    ``key_of(row)``   slot key of an existing row.
    ``slots``         ordered ``{key: {field: value}}``; a later duplicate key
                      wins, matching the old one-row-at-a-time behaviour.
    ``build_row``     ``build_row(key, values)`` -> unsaved model instance.
    ``should_update`` optional ``should_update(existing_rows, values)`` guard;
                      when it returns False the slot is left untouched.

    Returns ``(updated, created, skipped)`` slot counts.
    """
    model = queryset.model
    existing = defaultdict(list)
    for row in queryset:
        existing[key_of(row)].append(row)

    to_update, to_create = [], []
    updated = created = skipped = 0
    for key, values in slots.items():
        rows = existing.get(key)
        if not rows:
            to_create.append(build_row(key, values))
            created += 1
            continue
        if should_update is not None and not should_update(rows, values):
            skipped += 1
            continue
        for row in rows:
            for field, value in values.items():
                setattr(row, field, value)
            to_update.append(row)
        updated += 1

    if to_update:
        model.objects.bulk_update(to_update, update_fields, batch_size=BULK_BATCH_SIZE)
    if to_create:
        model.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
    return updated, created, skipped

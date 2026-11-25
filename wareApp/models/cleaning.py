"""Reading clean-up: the 10,000 kWh cap and CleanReadingMixin."""

import math


def clean_reading_float(value, default=0):
    """NaN, inf, negative or non-numeric readings become ``default`` / 0.

    Origin: Ashu
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return max(value, 0)


# A reading above MAX_READING_KWH is a meter glitch and is stored as 0 - only on
# energy-saving (2) and submetering (5) sites, which meter aisles. WH-metering
# (1) measures the whole warehouse: its values can genuinely be far above it and
# are never capped (decided 2026-11-03). Every write path uses this rule.
MAX_READING_KWH = 10000


CAPPED_SITE_TYPES = frozenset({2, 5})


def reading_capped(site):
    """True when ``site``'s readings are capped at MAX_READING_KWH.

    Origin: Ashu
    """
    return getattr(site, "site_type", None) in CAPPED_SITE_TYPES


def cap_reading(site, value):
    """``value``, or 0 when it is a glitch on a capped site.

    Origin: Ashu
    """
    return 0.0 if value > MAX_READING_KWH and reading_capped(site) else value


def hour_counts_in_day(site, kwh, daily_baseline):
    """False for a spike hour left out of the aisle's day total (decided
    2026-11-05): on saving / submetering sites, an hour above the aisle's whole
    daily baseline - impossible in one hour, a meter jump (the same test as the
    Consumption Spike alarm). The hour row itself is kept; the day total and
    saving use the other hours. Without a baseline every hour counts; on
    WH-metering every hour counts (big values are genuine there).

    Origin: Ashu
    """
    return not (
        reading_capped(site) and daily_baseline and kwh is not None and kwh > daily_baseline
    )


def cap_reading_row(row, site):
    """Apply only the glitch cap to an hourly / daily row (unit 0, saving =
    baseline), for rows written without save() (bulk_update).

    Origin: Ashu
    """
    if row.unit_consumption is not None and row.unit_consumption > MAX_READING_KWH and reading_capped(site):
        row.unit_consumption = 0
        row.energy_saved = getattr(row, row.baseline_field)
    return row


class CleanReadingMixin:
    """save() cleaning shared by HourlySiteReading and DailySiteReading.

    Consumption over MAX_READING_KWH on a saving / submetering site is treated
    as a meter glitch: stored as 0 with saving = baseline (see reading_capped).
    bulk_create / bulk_update skip save(); the batch path calls
    clean_reading_values itself (wareApp/mqtt/consumption_batch.py).

    Origin: Ashu
    """

    baseline_field = None

    def clean_reading_values(self, site=None):
        """``site``: the row's site when already loaded (saves a query).

        Origin: Ashu
        """
        self.unit_consumption = clean_reading_float(self.unit_consumption)
        setattr(self, self.baseline_field, clean_reading_float(getattr(self, self.baseline_field)))
        self.energy_saved = clean_reading_float(self.energy_saved)
        if self.unit_consumption > MAX_READING_KWH:
            cap_reading_row(self, site or self.associated_Site)

    def save(self, *args, **kwargs):
        """Cleans the reading values (NaN, negative, 10,000 kWh cap) before saving.

        Origin: Ashu
        """
        self.clean_reading_values()
        super().save(*args, **kwargs)

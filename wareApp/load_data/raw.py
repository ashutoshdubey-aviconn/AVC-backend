from wareApp.models import RawLoadData

from wareApp.load_data.parser import LoadReading


def save_raw_load_reading(site, aisle_group, reading: LoadReading):
    return RawLoadData.objects.create(
        site=site,
        aisle_group=aisle_group,
        load_data=reading.load_value,
        created=reading.created,
        epoch_time=reading.epoch_time,
    )

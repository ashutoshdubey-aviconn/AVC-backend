import logging

from wareApp.load_data.monthly import update_monthly_min_max_load
from wareApp.load_data.parser import parse_load_data_message
from wareApp.load_data.raw import save_raw_load_reading
from wareApp.load_data.rollups import roll_up_load_data_if_due
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.models import AisleGroup

logger = logging.getLogger(__name__)


def handle_load_data_message(client, site, location_id, gw_id, message, msg_type):
    if "LoadData" not in msg_type:
        logger.warning("Ignoring unexpected LoadData message type: %s", msg_type)
        return

    try:
        reading = parse_load_data_message(message)
        aisle_group = AisleGroup.objects.get(
            site=site, attached_leg_id=str(reading.leg_id)
        )
        save_raw_load_reading(site, aisle_group, reading)

        if site.is_loadGraph_visible:
            update_monthly_min_max_load(site, aisle_group, reading)
        roll_up_load_data_if_due(
            site,
            reading.created,
            home_gateway_id=home_gateway_id_for(location_id, gw_id),
        )
        logger.info(
            "Saved LoadData for site %s, leg %s, value %s, epoch %s",
            location_id,
            reading.leg_id,
            reading.load_value,
            reading.epoch_time,
        )
    except Exception:
        logger.exception("LoadData message skipped for site %s", location_id)

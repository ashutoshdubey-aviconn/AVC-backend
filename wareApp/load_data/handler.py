import logging

from django.core.exceptions import ObjectDoesNotExist

from wareApp.load_data.monthly import update_monthly_min_max_load
from wareApp.load_data.parser import parse_load_data_message
from wareApp.load_data.raw import save_raw_load_reading
from wareApp.load_data.rollups import roll_up_load_data_if_due
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter
from wareApp.models import AisleGroup

logger = logging.getLogger(__name__)


# Errors that repeat on every packet until the configuration or the gateway
# is fixed: one dead letter per error and gateway every few minutes is enough.
CONFIGURATION_ERRORS = (ObjectDoesNotExist, ValueError)


def handle_load_data_message(client, site, location_id, gw_id, message, msg_type):
    """Store one LoadData packet; return an outcome text like the queue-1 handlers.

    Transient database errors are re-raised so the processing task retries the
    packet in place. Every other failure becomes an MqttDeadLetter
    (``message_type="LoadData"``) that ``manage.py replay_dead_letters`` can
    process again; unexpected errors keep every packet, configuration/payload
    errors one per gateway and error every DEAD_LETTER_DEDUPE_SECONDS.
    """
    if "LoadData" not in msg_type:
        logger.warning("Ignoring unexpected LoadData message type: %s", msg_type)
        return f"skipped: unexpected message type {msg_type}"

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
        return f"stored: LoadData leg {reading.leg_id} at {reading.created:%Y-%m-%d %H:%M:%S}"
    except TRANSIENT_DB_ERRORS:
        raise
    except Exception as error:
        logger.exception(
            "LoadData message failed (dead letter): site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id_for(location_id, gw_id),
        )
        record_dead_letter(
            "LoadData",
            location_id,
            gw_id,
            message,
            error,
            dedupe=isinstance(error, CONFIGURATION_ERRORS),
        )
        return f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)"

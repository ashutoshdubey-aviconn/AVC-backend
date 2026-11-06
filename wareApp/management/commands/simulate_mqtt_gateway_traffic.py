import random
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand, CommandError

from wareApp.models import AisleGroup, Site


class Command(BaseCommand):
    help = (
        "Publish randomized gateway MQTT traffic to exercise queue1 and queue2 workers."
    )

    def add_arguments(self, parser):
        parser.add_argument("--site-id", type=int, required=True)
        parser.add_argument("--leg-id", type=str)
        parser.add_argument("--gateway-id", default="simulation-gateway-01")
        parser.add_argument("--cycles", type=int, default=1)
        parser.add_argument("--interval", type=float, default=0.2)
        parser.add_argument(
            "--load-data-only",
            action="store_true",
            help="Publish only LoadData messages to queue2.",
        )
        parser.add_argument(
            "--all-topics",
            action="store_true",
            help="Include FIREALARM, recovery, sync, and remoteAccess traffic.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            help="Actually publish state-changing test payloads. Without this flag, only preview them.",
        )

    def handle(self, *args, **options):
        site = Site.objects.filter(id=options["site_id"]).first()
        if site is None:
            raise CommandError(f"Unknown site ID: {options['site_id']}")

        leg = self._find_leg(site, options["leg_id"])
        messages = self._messages(
            site.id,
            str(leg.attached_leg_id),
            options["gateway_id"],
            options["all_topics"],
            options["load_data_only"],
        )
        if not options["write"]:
            self.stdout.write(
                self.style.WARNING("Preview only; no MQTT messages published.")
            )
            for topic, payload in messages:
                self.stdout.write(f"{topic} -> {payload}")
            self.stdout.write("Re-run with --write to publish this simulation batch.")
            return

        client = mqtt.Client(client_id=f"mqtt-simulator-{int(time.time())}")
        client.connect("127.0.0.1", 1883, 60)
        client.loop_start()
        try:
            cycle = 0
            while options["cycles"] == 0 or cycle < options["cycles"]:
                cycle += 1
                for topic, payload in self._messages(
                    site.id,
                    str(leg.attached_leg_id),
                    options["gateway_id"],
                    options["all_topics"],
                    options["load_data_only"],
                ):
                    result = client.publish(topic, payload, qos=0)
                    result.wait_for_publish()
                    self.stdout.write(f"cycle={cycle} published {topic}")
                    time.sleep(options["interval"])
        finally:
            client.loop_stop()
            client.disconnect()

    def _find_leg(self, site, leg_id):
        legs = AisleGroup.objects.filter(site=site)
        if leg_id:
            leg = legs.filter(attached_leg_id=leg_id).first()
        else:
            leg = legs.first()
        if leg is None:
            raise CommandError(f"No configured leg found for site ID {site.id}")
        return leg

    def _messages(self, site_id, leg_id, gateway_id, all_topics, load_data_only=False):
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")
        epoch_millis = int(now.timestamp() * 1000)
        prefix = f"/Acclivate/iOmniControl/{site_id}/{gateway_id}/in"
        cumulative = round(random.uniform(10000, 90000), 3)
        hourly = round(random.uniform(0.1, 5.0), 3)
        load_value = round(random.uniform(1000, 50000), 3)

        messages = [
            (
                f"{prefix}/consumption/state",
                "Consumption_time_in_sec :30.0,Unit_consumption :0.25,saving :0.0,"
                f"Message_time :{timestamp},Leg_Meter_Reading :L{leg_id}_{cumulative},"
                f"Current_Hour_total_consumption :{hourly},AisleGrp_id :{leg_id},"
                f"GW_Total_Cumulative :{cumulative},"
                f"Previous_hour_total_consumption :{max(hourly - 0.1, 0.0)},Rc :1",
            ),
            (
                f"{prefix}/load/state",
                "Load_power :2500.0,R_volt :230.0,Y_volt :231.0,B_volt :229.0,"
                "R_current :4.0,Y_current :4.2,B_current :3.9,Power_source :0,"
                f"Status :1,Meter_number :1,Message_time :{timestamp}",
            ),
            (
                f"{prefix}/SupplyTime/state",
                "Supply_Source :0,Runtime :30.0,Last_runtime_cumulative :10000.0,"
                f"Message_time :{timestamp}",
            ),
            (
                f"{prefix}/LoadData/state",
                f"LoadValue :{load_value},leg_id :{leg_id},Meter_Number :1,"
                f"Datetime :{timestamp},epochTime :{epoch_millis}",
            ),
        ]
        if load_data_only:
            return [messages[3]]
        if all_topics:
            messages.extend(
                [
                    (
                        f"{prefix}/FIREALARM/state",
                        "Meter_Number :1,R_volt :230.0,Y_volt :231.0,"
                        "B_volt :229.0,Power_status :0",
                    ),
                    (
                        f"{prefix}/recovery/dailyConsumption",
                        f"Aisle_group_id : {leg_id}; Recovery_Dates : {now:%Y-%m-%d},; "
                        f"Unit_consumptions : {hourly},; GW_Total_cumulative : {cumulative}",
                    ),
                    (f"{prefix}/sync/state", "simulation-sync"),
                    (f"{prefix}/remoteAccess/state", "simulation-remote-access"),
                ]
            )
        return messages

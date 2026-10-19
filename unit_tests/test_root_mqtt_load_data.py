from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

import tasks as root_tasks
from wareApp.mqtt.routing import QUEUE_ONE_SUBSCRIPTIONS, QUEUE_TWO_SUBSCRIPTIONS


class FakeMqttClient:
    def __init__(self, message=None):
        self.message = message
        self.subscriptions = []
        self.on_connect = None
        self.on_message = None

    def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)

    def connect(self, *_args):
        return 0

    def connect_async(self, *_args):
        return 0

    def reconnect_delay_set(self, **_kwargs):
        pass

    def loop_forever(self, **_kwargs):
        self.on_connect(self, None, None, 0)
        if self.message is not None:
            self.on_message(self, None, self.message)


class RootMqttLoadDataTests(SimpleTestCase):
    def test_root_listeners_subscribe_to_separate_topic_sets(self):
        queue_one_client = FakeMqttClient()
        queue_two_client = FakeMqttClient()

        with patch(
            "tasks.mqtt.Client", side_effect=[queue_one_client, queue_two_client]
        ):
            root_tasks.mqtt_client1.run()
            root_tasks.mqtt_client2.run()

        self.assertEqual(queue_one_client.subscriptions, list(QUEUE_ONE_SUBSCRIPTIONS))
        self.assertEqual(queue_two_client.subscriptions, list(QUEUE_TWO_SUBSCRIPTIONS))

    def test_root_queue_two_queues_load_data_for_processing(self):
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/LoadData/state",
            payload=b"Load_Power:12.5,Leg_Id:967,Meter_Number:M-1,Time:2026-10-08 12:00:00,Epoch:1791450600000",
        )
        queue_two_client = FakeMqttClient(message)

        # The root listener delegates to wareApp.mqtt.consumers, which hands the
        # packet to the queue2 processing task instead of handling it inline.
        with (
            patch("tasks.mqtt.Client", return_value=queue_two_client),
            patch("wareApp.tasks.process_load_data_message.apply_async") as enqueue,
        ):
            root_tasks.mqtt_client2.run()

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", message.payload.decode("utf-8")),
            queue="queue2_processing",
        )

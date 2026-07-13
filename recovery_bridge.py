#!/usr/bin/env python3

import json
import logging
import os

import paho.mqtt.client as mqtt
import requests

BROKER = "127.0.0.1"
PORT = 1883

API_URL = "http://127.0.0.1:8000/api/recovery/upload/"

LOG_DIR = "logs"

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "recovery_bridge.log")),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("RecoveryBridge")


def on_connect(client, userdata, flags, rc):

    logger.info("Connected : %s", rc)

    client.subscribe("/Acclivate/iOmniControl/+/+/in/recovery/#")


def on_message(client, userdata, msg):

    try:

        payload = msg.payload.decode()

        logger.info("Message Received")
        logger.info("Topic: %s", msg.topic)
        logger.info("Payload: %s", payload)

        body = {"topic": msg.topic, "payload": payload}

        r = requests.post(API_URL, json=body, timeout=30)

        logger.info("Response Status Code: %s", r.status_code)
        logger.info("Response Text: %s", r.text)

    except Exception as e:

        print(e)


client = mqtt.Client("RecoveryBridge")

client.on_connect = on_connect

client.on_message = on_message

client.connect(BROKER, PORT)

client.loop_forever()

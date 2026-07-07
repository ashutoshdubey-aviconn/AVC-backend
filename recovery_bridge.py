#!/usr/bin/env python3

import json
import logging

import paho.mqtt.client as mqtt
import requests

BROKER = "127.0.0.1"
PORT = 1883

API_URL = "http://127.0.0.1:8000/api/recovery/upload/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def on_connect(client, userdata, flags, rc):

    print("Connected :", rc)

    client.subscribe("/Acclivate/iOmniControl/+/+/in/recovery/#")


def on_message(client, userdata, msg):

    try:

        payload = msg.payload.decode()

        print("\n------------------------------------")
        print(msg.topic)
        print(payload)

        body = {"topic": msg.topic, "payload": payload}

        r = requests.post(API_URL, json=body, timeout=30)

        print(r.status_code)

        print(r.text)

    except Exception as e:

        print(e)


client = mqtt.Client("RecoveryBridge")

client.on_connect = on_connect

client.on_message = on_message

client.connect(BROKER, PORT)

client.loop_forever()

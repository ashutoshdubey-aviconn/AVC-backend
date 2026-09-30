from warehouse.celery import app
from wareApp.mqtt.consumers import run_mqtt_client1, run_mqtt_client2


@app.task(queue="queue1")
def mqtt_client1():
    return run_mqtt_client1()


@app.task(queue="queue2")
def mqtt_client2():
    return run_mqtt_client2()

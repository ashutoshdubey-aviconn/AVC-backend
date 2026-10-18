# MQTT and Celery Queue Architecture

```mermaid
flowchart LR
    Broker[MQTT broker<br/>Mosquitto :1883]

    subgraph Q1[Queue 1: business and recovery messages]
        Listener1[Celery listener worker<br/>root-mqtt-queue1]
        Queue1[(RabbitMQ queue1)]
        MQTT1[mqtt_client1]
        ProcessQueue1[(RabbitMQ queue1_processing)]
        Processor1[Celery processing worker<br/>root-mqtt-queue1-processing]
        Tasks1[SupplyTime<br/>Load / loadRuntime recovery<br/>consumption / hourly and daily recovery<br/>FIREALARM]
    end

    subgraph Q2[Queue 2: LoadData only]
        Listener2[Celery listener worker<br/>root-mqtt-queue2]
        Queue2[(RabbitMQ queue2)]
        MQTT2[mqtt_client2]
        ProcessQueue2[(RabbitMQ queue2_processing)]
        Processor2[Celery processing worker<br/>root-mqtt-queue2-processing]
        Tasks2[process_load_data_message]
    end

    Database[(PostgreSQL warehouse)]

    Queue1 --> MQTT1
    MQTT1 --> Listener1
    Broker --> Listener1
    Listener1 --> ProcessQueue1
    ProcessQueue1 --> Processor1
    Processor1 --> Tasks1
    Tasks1 --> Database

    Queue2 --> MQTT2
    MQTT2 --> Listener2
    Broker --> Listener2
    Listener2 --> ProcessQueue2
    ProcessQueue2 --> Processor2
    Processor2 --> Tasks2
    Tasks2 --> Database
```

## Listener Health

Each listener worker must remain a RabbitMQ consumer for `queue1` or `queue2`.
Each processing worker must remain a consumer for `queue1_processing` or
`queue2_processing`. A systemd unit reporting `active` alone does not establish
that its Celery worker is connected to RabbitMQ.

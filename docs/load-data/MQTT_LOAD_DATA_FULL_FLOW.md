# MQTT, LoadData, and Gateway Control Flow

## Scope

This document describes the active local architecture for gateway MQTT traffic:

- Queue 1 business telemetry and recovery processing
- Queue 2 `LoadData` processing
- Consumption and SupplyTime gap recovery
- Remote-access command publishing
- Listener and database failure boundaries

The diagrams describe the local optimized code. They do not represent a deployment, migration, worker restart, or broker configuration change.

## Queue Ownership

| Queue | MQTT subscriptions | Processing queue | Responsibility |
| --- | --- | --- | --- |
| `queue1` | `consumption`, `FIREALARM`, `load`, `SupplyTime`, `recovery` | `queue1_processing` | Business telemetry and recovered readings |
| `queue2` | `LoadData` only | `queue2_processing` | Load graph raw data, monthly extrema, and rollups |

`sync` and `remoteAccess` are outbound gateway commands. They are recognized topic names but are not subscribed as inbound listener traffic.

## Full System Flow

```mermaid
flowchart TB
    Gateway[Gateway agent] <--> Broker[Mosquitto broker]

    Broker --> Q1Listener[Queue 1 Paho listener\nserver_paho_client_1]
    Broker --> Q2Listener[Queue 2 Paho listener\nserver_paho_client_2]

    Q1Listener --> Q1Dispatch[Validate topic and enqueue\nqueue1_processing]
    Q2Listener --> Q2Dispatch[Validate topic and enqueue\nqueue2_processing]

    Q1Dispatch --> Q1Worker[Queue 1 processing worker]
    Q2Dispatch --> Q2Worker[Queue 2 processing worker]

    Q1Worker --> BusinessDB[(Business telemetry tables)]
    Q2Worker --> LoadDB[(Raw, hourly, daily, monthly load tables)]

    Q1Worker -->|Gap detected| SyncRequest[Publish sync command]
    SyncRequest --> Broker
    Broker --> Gateway

    Operator[Authorized API or backend action] --> RemoteAccess[Publish remote-access command]
    RemoteAccess --> Broker
    Broker --> Gateway
```

## Queue 1 Business Telemetry

```mermaid
flowchart LR
    Gateway -->|consumption, load, SupplyTime, FIREALARM| Broker
    Broker --> Listener[Queue 1 listener]
    Listener --> Parse[Parse topic\nand decode payload]
    Parse -->|Valid supported type| Enqueue[Celery apply_async\nqueue1_processing]
    Parse -->|Malformed or unsupported| Log[Log and continue listener]

    Enqueue --> Worker[Processing task]
    Worker --> Connections[Close stale DB connections\nbefore ORM work]
    Connections --> Site[Resolve Site]
    Site -->|Missing| Missing[Warning and return]
    Site -->|Found| Handler[Family-specific handler]
    Handler --> DB[(Business tables)]
    DB --> Cleanup[Close stale DB connections\nafter ORM work]
```

Message-family handlers:

| Message type | Processing task | Handler |
| --- | --- | --- |
| `consumption` | `process_consumption_message` | `handle_consumption_message` |
| `load` | `process_load_message` | `handle_load_message` |
| `SupplyTime` | `process_supply_time_message` | `handle_supply_time_message` |
| `FIREALARM` | `process_fire_alarm_message` | `handle_fire_alarm_message` |

## Queue 2 LoadData

```mermaid
flowchart LR
    Gateway -->|LoadData/state| Broker
    Broker --> Listener[Queue 2 listener]
    Listener --> Topic[Parse LoadData topic\nand decode payload]
    Topic -->|Valid| Enqueue[Celery apply_async\nqueue2_processing]
    Topic -->|Invalid| Log[Log and continue listener]

    Enqueue --> Worker[process_load_data_message]
    Worker --> Connections[Close stale DB connections]
    Connections --> Site[Resolve Site]
    Site -->|Missing| Missing[Warning and return]
    Site -->|Found| Parse[Parse field-based payload]
    Parse --> Aisle[AisleGroup lookup\nsite plus leg]
    Aisle --> Raw[Insert RawLoadData]
    Raw --> Graph{Load graph enabled?}
    Graph -->|Yes| Monthly[Update monthly min/max\nonly when extrema change]
    Graph -->|No| Rollup
    Monthly --> Rollup[Schedule per-site rollup]
    Rollup --> Hourly[Create missing minute extrema\nin HourlyLoadData and MainsDgLoadData]
    Hourly --> Daily{Daily rollup due\nfor this site/hour?}
    Daily -->|Yes| DailyWrite[Create missing hour extrema\nin DailyLoadData]
    Daily -->|No| Complete[Complete]
    DailyWrite --> Complete
```

Rollup safeguards:

- Raw and materialized data are streamed in chunks with only required columns.
- Each bucket retains only minimum and maximum readings.
- Inserts use batched `bulk_create` operations.
- A per-site lock prevents concurrent rollups for different minutes of the same site.
- Duplicate observed-minute rollups are skipped.
- Daily rollups are limited to one scan per completed hour per site.

## Consumption Gap Recovery

```mermaid
sequenceDiagram
    participant G as Gateway
    participant B as Mosquitto
    participant L as Queue 1 listener
    participant W as Queue 1 processing worker
    participant D as Database

    G->>B: consumption/state
    B->>L: consumption/state
    L->>W: process_consumption_message
    W->>D: Update current hour

    alt Previous hour exists
        W->>D: Reconcile previous and daily data
    else Older hourly records exist but previous hour is missing
        W->>B: Publish sync/consumption/state
        B->>G: Sync request with aisle group and last synced hour
        G->>B: recovery/hourlyConsumption
        G->>B: recovery/dailyConsumption when applicable
        B->>L: recovery payloads
        L->>W: Recovery processing tasks
        W->>D: Persist recovered hourly and daily readings
    else First reading for aisle group
        W->>D: Create initial hourly and daily readings
    end
```

`sync` is not an inbound response. It is the server-to-gateway request. The gateway response must use `recovery` topics, which Queue 1 subscribes to.

## SupplyTime Gap Recovery

```mermaid
sequenceDiagram
    participant G as Gateway
    participant B as Mosquitto
    participant W as Queue 1 processing worker
    participant D as Database

    G->>B: SupplyTime/state
    B->>W: Process queued SupplyTime message
    W->>D: Update current runtime hour

    alt Missing prior runtime hour
        W->>B: Publish sync/loadTime/state
        B->>G: Runtime recovery request
        G->>B: recovery/loadRuntime
        B->>W: Process queued recovery message
        W->>D: Persist recovered runtime data
    end
```

## Recovery Topic Dispatch

```mermaid
flowchart LR
    Gateway -->|recovery/dailyConsumption| Broker
    Gateway -->|recovery/hourlyConsumption| Broker
    Gateway -->|recovery/loadRuntime| Broker

    Broker --> Listener[Queue 1 listener]
    Listener --> Parse[Parse topic]
    Parse --> Daily[process_daily_consumption_recovery_message]
    Parse --> Hourly[process_hourly_consumption_recovery_message]
    Parse --> Runtime[process_load_runtime_recovery_message]

    Daily --> DB[(Database)]
    Hourly --> DB
    Runtime --> DB
```

Unknown recovery subtypes are logged and stopped at the dispatcher. They do not enter legacy callback behavior.

## Remote Access

```mermaid
sequenceDiagram
    participant A as Authorized API or backend action
    participant R as request_remote_access
    participant B as Mosquitto
    participant G as Gateway agent

    A->>R: site ID, gateway ID, action, retry count
    R->>R: Validate values
    R->>B: Publish QoS 1 remoteAccess/state command
    B->>G: Deliver command
    G->>G: Execute start, stop, or restart
```

```text
Topic:   /Acclivate/iOmniControl/<site_id>/<gateway_id>/in/remoteAccess/state
Payload: <start|stop|restart>_<retry_count>
QoS:     1
Retain:  false
```

The backend publishes this command but does not execute gateway shell commands. Queue 1 does not subscribe to inbound `remoteAccess` traffic.

## Resilience Boundaries

```mermaid
flowchart TB
    Callback[Paho callback] --> Parse[Topic and payload decode]
    Parse --> Enqueue[Celery enqueue]
    Parse -->|Topic error| CallbackLog[Warning log]
    Enqueue -->|Unexpected error| CallbackError[Exception log]
    CallbackLog --> Continue[Continue loop_forever]
    CallbackError --> Continue

    Worker[Celery processing task] --> DBStart[Close stale DB connections]
    DBStart --> Process[Resolve site and process message]
    Process --> DBEnd[Close stale DB connections]
    DBEnd --> Done[Task complete]

    Listener[Long-running listener task] -->|Non-success exit| Retry[Celery retry with bounded backoff]
    Retry --> Listener
```

The listeners use Paho reconnect delays from one to thirty seconds. Callback code does not access Django models; ORM work begins only in Celery processing tasks.

## Worker Layout

```text
celery -A warehouse worker --queues=queue1 --hostname=worker.queue1@%h --concurrency=1 --loglevel=INFO
celery -A warehouse worker --queues=queue2 --hostname=worker.queue2@%h --concurrency=1 --loglevel=INFO
celery -A warehouse worker --queues=queue1_processing --concurrency=1 --loglevel=INFO
celery -A warehouse worker --queues=queue2_processing --concurrency=1 --loglevel=INFO
```

Run one listener per listener queue. Processing queues may be scaled only after confirming database capacity, ordering requirements, and idempotency behavior for the relevant message family.

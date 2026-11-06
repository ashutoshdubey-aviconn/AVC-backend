# Gateway pings from main for the test server

Since 2026-11-06. Code: `fetch_remote_pings` in
`wareApp/mqtt/services/gateway_health.py`, called by the Celery beat task
`check_gateway_health` (every 5 min) before the alarms are evaluated.

## Why

The gateway alarms tell **Gateway Disconnected (15)** (no pings, no data: power
or network gone) from **Gateway Service / Modbus Issue (16)** (pings, but no
data: service or meters down) by the gateway's MQTT pings. Gateways connect and
ping only main's broker; the test server receives their data through main's
bridge but never their pings. Without ping data test may not say
"disconnected" (rule of 2026-11-02), so every outage showed as 16, e.g. the
Purplle power cut (sites 133 / 135, 4 Nov) and site 53 (6 Nov).

Using "any message from the gateway" as the alive signal was rejected: most
gateways send only consumption / LoadData, so a gateway with a Modbus fault
sends nothing either and would be called disconnected.

## How

```
test server (Celery beat, every 5 min)
  ssh -i ~/.ssh/main_pings_ed25519 ubuntu@asem.aviconncorp.com
        │   key locked on main to ONE forced command (read-only):
        │   sudo tail -c 4 MB of /var/log/mosquitto/mosquitto.log
        │        | grep "Received PINGREQ from odroid." / "New (client|bridge) connected ... as odroid."
        ▼
  ping / connect lines (~last 20 min)  →  last ping per gateway (HomeGatewayStatus.last_ping_at)
                                        →  ping data marked fresh (MonitoringMarker broker_log_read_at)
  gateway check:  no data ≥ 1 h + no ping ≥ 1 h  → 15 Gateway Disconnected
                  no data ≥ 1 h + recent ping    → 16 Gateway Service / Modbus Issue
```

- If the fetch fails (main down, key removed, timeout), a warning is logged and
  ping data goes stale after 15 min; the check then falls back to the old rule
  (16, "ping status unknown"), never a wrong 15.
- Cost on main: one SSH login and a `tail` of 4 MB every 5 minutes.

## Settings (test server `.env`)

```
GATEWAY_PINGS_SSH=ubuntu@asem.aviconncorp.com
GATEWAY_PINGS_SSH_KEY=~/.ssh/main_pings_ed25519
```

Empty / missing `GATEWAY_PINGS_SSH` = off (the default; main never sets it).

## Setup

1. **Test server** (done 2026-11-06): key `~/.ssh/main_pings_ed25519` (user
   `ubuntu`, comment `test-server-gateway-pings`), no passphrase, only used by
   this task.
2. **Main server** (must be done by an admin): add ONE line to
   `/home/ubuntu/.ssh/authorized_keys`:

   ```
   restrict,command="sudo -n /usr/bin/tail -c 4000000 /var/log/mosquitto/mosquitto.log | /usr/bin/grep -aE 'Received PINGREQ from odroid\.|New (client|bridge) connected from [^ ]+ as odroid\.'" ssh-ed25519 <public key of test> test-server-gateway-pings
   ```

   `restrict` disables shell, terminal, port / agent / X11 forwarding; the
   forced `command` runs whatever the client asks. So this key can only read
   the ping lines.
3. **Test server**: set the two settings above, restart `mqtt-processing-queue2`
   and `celerybeat`.

## Check it works

On test:
`grep -a "gateway health: pings updated=" ~/django_project/celerylogs2/celery_logs_of_server.log | tail -1`
(the task result line shows how many gateways got a ping), and
`grep -a "Gateway pings from" ~/django_project/celerylogs2/celery_logs_of_server.log | tail`
for failures.

## Remove it

On main, delete the line ending in `test-server-gateway-pings` from
`/home/ubuntu/.ssh/authorized_keys` (a backup of the file from before the
change: `authorized_keys.before_gateway_pings_20261106`). On test, remove the
two settings and restart; delete `~/.ssh/main_pings_ed25519*`.

## Tests

`wareApp/tests/test_gateway_health.py` `RemotePingTests`: bridge-connect lines
count as alive; not configured does nothing; a fetch stores pings and marks them
fresh; a failed fetch leaves ping data stale.

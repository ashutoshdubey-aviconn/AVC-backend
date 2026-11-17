# Alarms on merged sites (virtual aisle groups)

Since 2026-11-17. Code: `wareApp/mqtt/services/alarm_sites.py`, used by
`gateway_health.py` (14 / 15 / 16), `spike_alarms.py` (17),
`consumption_alarms.py` (7, 8, 11, 12), `mqtt/consumption.py` (10) and
`alarm_feed.py` (super-admin lists). Tests: `wareApp/tests/test_alarm_sites.py`.

## Why

Gateways and sites are not one-to-one. One site can have several gateways, and
one gateway can feed aisles that are shown under several sites. A customer may
also want two physical sites shown as one. Each aisle has two sites:

| Field | Meaning |
|---|---|
| `AisleGroup.site` | Physical site: where its meter and gateway are, where its readings are stored |
| `AisleGroup.virtual_siteID` | Display site: the site the customer sees the aisle under |

Case: site **185 FM FarukhNagar-2** is *not live*, because the customer wanted
one site. Its aisles (C&S-GF, C&S-F1, C&S-F2, C&S-F3, C&S-EL) show under the
live site **183 FM MCF-1 Farrukhnagar**. Gateway `avc_FMFarukhNagar_GGN_0000185_2`
feeds those aisles and has sent nothing since 6 Nov 09:00. No alarm was raised,
because:
- the gateway check only looked at live sites;
- the alarm pages read alarms by site, while 185's aisle alarms were stored under 185.

## Rules

1. **Monitored site.** A site is monitored when it is live, or when one of its
   active aisles shows under a live display site. The gateway (15 / 16), meter
   (14) and spike (17) checks cover monitored sites.
2. **Aisle alarms** (High / Low Consumption, Meter Reading Issue, Bypassed,
   Operation Hours Increased, Consumption Spike) are stored and e-mailed under
   the aisle's **display site**. They are looked up by the aisle, so older rows
   stored under the physical site are still found: no duplicates.
3. **Gateway alarms** (15 / 16) go to the live display sites of the aisles the
   gateway feeds (`AisleSyncRecoveryStatus`; if no mapping exists, all active
   aisles of its site). If none of them is live but the gateway's own site is,
   they go to its own site, as before. The e-mail adds "Gateway's site" and
   "Aisles" when the alarm is stored under another site. Example:
   `Gateway avc_FMFarukhNagar_GGN_0000185_2`, `Gateway's site: FM FarukhNagar-2 (185)`,
   `Aisles: C&S-EL, C&S-F1, C&S-F2, C&S-F3, C&S-GF`, stored under site 183.
4. **Meter Disconnected** (14) goes to the live display sites of the meter's
   site's aisles.
5. **Gateway number.** A gateway alarm's `object_id` is the gateway number
   (`…_2`). If two gateways under one display site have the same number, the
   merged one gets `10000 + its HomeGatewayId id` (logged as a warning), and
   the alarm feed resolves it back to the gateway name.
6. **Settings.** Thresholds, baselines and NL hours still come from the
   physical site (where the data is). An alarm is **Off** when its
   AlarmSetting is Off on the physical site *or* on the display site.
   Recipients are the display site's (it is the site the alarm is e-mailed for).
7. **Moving.** If an aisle's display site changes, a gateway or meter alarm
   still open under the old site is cleared at the next check. Open aisle
   alarms keep their site until the alarm closer closes them.

Several gateways on one site already worked: each gateway is checked on its own.

## Sites affected (17 Nov)

| Physical site (not live) | Shown under (live) | Server |
|---|---|---|
| 185 FM FarukhNagar-2 | 183 FM MCF-1 Farrukhnagar | test and main |
| 191 Myntra Bilaspur RPC | 194 Myntra Bilaspur RSC Inventory-Saving | test only (191 is live on main) |

Live physical sites whose aisles show under another live site (e.g. 29 → 34,
150 → 157 / 174) now have their aisle alarms under the display site. Their
gateway alarms also go to the display site when all of the gateway's aisles
are shown there.

## Test server data (17 Nov)

The test DB had none of main's 12 newest gateways (main ids 143–155,
registered after test's copy), including both Farrukhnagar gateways, so test
never checked them. They were copied from main (`HomeGatewayId`, same ids),
and gateway `…185_2` got `last_data_at` = its last hourly reading (6 Nov 09:59).
Main itself was only read.

## Rolling back

Revert the commit. Alarm rows already stored under a display site stay there;
the closer closes them as usual.

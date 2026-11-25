"""Build docs/operations/ISSUE_LIST.xlsx: issues we have already resolved,
alarm issues first, each with a short name and a simple description."""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

ALARM_ISSUES = [
    ("Meter reading jump",
     "A meter jumps to a very high reading for an hour, then comes back to normal, so the hour shows fake high consumption."),
    ("Catch-up hour after a data gap",
     "When a gateway comes back after a gap, one hour carries the energy of the whole gap and looks like a spike."),
    ("False Bypassed alarm",
     "An aisle was shown as using its full baseline (no saving) because of a wrong daily total, so Bypassed fired when it should not."),
    ("High Consumption / Bypassed on wrong totals",
     "These alarms read the stored daily total, which could include jumps and catch-up hours, instead of the real hourly readings."),
    ("Spike hours counted twice",
     "Spike hours were taken off the day twice when checking alarms, so the day looked lower than it was."),
    ("Meter Reading Issue alarm repeating",
     "The alarm closed after 1 hour and the same meter problem came back as a new alarm and a new e-mail (14 of 17 times)."),
    ("No reason for zero consumption",
     "When an hour showed 0 there was no alarm to say why. Now Meter Disconnected, Gateway Disconnected and Gateway Service / Modbus Issue tell it."),
    ("False Service Issue when a gateway reconnects",
     "A gateway coming back online raised a Service / Modbus Issue alarm and e-mail while its old data was still arriving."),
    ("Offline and service issue looked the same on test",
     "Test had no gateway pings, so it could not tell an offline gateway from one that is online but not reading meters."),
    ("Wrong outage time on test",
     "A gateway's outage showed the test server's start time instead of the real time the gateway went offline."),
    ("Alarm count always 0",
     "Customer and site pages showed 0 alarms because they read rows that nothing writes."),
    ("Wrong open alarm count",
     "The alarm list showed the total number of alarm occurrences instead of the alarms still open."),
    ("Alarm e-mails lost",
     "If the mail server failed, the alarm e-mail was lost. Now it is kept and sent again later."),
    ("Merged sites not checked for alarms",
     "Aisles shown under another live site were not checked for gateway, meter and spike alarms."),
]

OTHER_ISSUES = [
    ("High CPU on the main server",
     "The backend kept the server CPU around 65% on average; it is now about 23%."),
    ("LoadData slowing other data",
     "LoadData packets every 5-10 seconds filled the workers, so other data waited and LoadData had to run on a second server."),
    ("Duplicate DG fuel rows",
     "The same DG fuel reading was saved many times: 1.67 million duplicate rows."),
    ("Missing hours never refilled",
     "When a gateway missed some hours, those hours stayed empty. Now the server asks the gateway again and fills them."),
    ("No view of sync status",
     "Sync and recovery data was stored but no screen or API showed it."),
    ("Real metering values dropped",
     "Readings above 10,000 kWh were dropped on every site, including whole-warehouse meters where such values are real."),
    ("Slow database writes",
     "Saving readings locked and looked up other tables, and some indexes were missing or not used."),
    ("Customer missing in Super Admin list",
     "YusenLogistics did not show in the Super Admin customer list."),
    ("Only 5 sites on the customer page",
     "The site table shared its page control with the alarm table, so only 5 sites showed."),
    ("Gateway status open to anyone",
     "The gateway status API could be read without login; now it is Super Admin only."),
]

wb = Workbook()
ws = wb.active
ws.title = "Resolved issues"
ws.append(["#", "Area", "Issue", "Description"])
rows = [("Alarm", n, d) for n, d in ALARM_ISSUES] + [("Other", n, d) for n, d in OTHER_ISSUES]
for i, (area, name, desc) in enumerate(rows, 1):
    ws.append([i, area, name, desc])

thin = Side(style="thin", color="BFBFBF")
for row in ws.iter_rows():
    for c in row:
        c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        c.alignment = Alignment(wrap_text=True, vertical="top")
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="14213D")
for col, w in zip("ABCD", (5, 9, 42, 95)):
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A2"

out = Path(__file__).with_name("ISSUE_LIST.xlsx")
wb.save(out)
print(out, len(rows), "issues")

# Alarm e-mail retries

Since 2026-11-06. Code: `wareApp/sendmail.py` (`EmailFailure`),
`wareApp/mqtt/services/notifications.py` (`remember_failed`, `retry_pending`),
`wareApp/tasks.py` (`send_notification`, `retry_pending_emails`), model
`PendingEmail` (migration 0109).

## Why

On 6 Nov from 14:55 Gmail closed every SMTP login of the alarm account
(`SMTPServerDisconnected: Connection unexpectedly closed` at login; connect and
TLS worked). Every alarm e-mail after that failed and was lost: the send
functions caught the error and returned `False`, so the queue's automatic
retry (which only reacts to exceptions) never ran. Test and main use the same
Gmail account.

## How

```
alarm raised ──► notify() ──► notifications queue ──► send_notification ──► sendmail.send_alarm_email
                                                                   │
                                     sent ◄────────────────────────┤
                                                                   │ failed
                      passing failure (server closed / login refused / timeout)
                                                                   ▼
                                                    PendingEmail row (function + arguments)
                                                                   │
 Celery beat, every 5 min: retry_pending_emails ◄──────────────────┘
   • due rows, oldest first (max 20 per run)
   • sent → row deleted, log "Email sent on retry N"
   • still refused → next try later; STOP this run (the server is still refusing)
   • 24 h after the first failure (or a permanent error) → given up, log "Email given up"
```

Back-off after each failed try: 5, 15, 30 min, 1, 2, 4, 8 h, then every 8 h until
24 h after the first failure (about 9 tries in all).

| Failure | Retried? |
|---|---|
| Server closed the connection, login refused, timeout, network error | Yes |
| Address refused by the server (`SMTPRecipientsRefused`, `SMTPSenderRefused`) | No |
| No recipients, `EMAIL_HOST` not configured | No |

- The e-mail is rebuilt from the same arguments, so it has the same subject,
  details and recipients (on the test server, still redirected to the override).
- Rows live in the database, so pending e-mails survive restarts (the test server
  is off at night; they go out once it is back, while within 24 h).
- E-mails sent directly (when the queue is down, or `MQTT_ASYNC_NOTIFICATIONS`
  off) are kept the same way.
- The failure value (`EmailFailure`) is false like the old `False`, so existing
  `if sent:` checks are unchanged.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `NOTIFICATION_RETRY_HOURS` | 24 | How long to keep retrying; 0 = off |
| `NOTIFICATION_RETRY_CHECK_SECONDS` | 300 | How often the retry task runs |

## Where to look

- Waiting e-mails: Django admin → **Pending emails** (summary, attempts, first
  failure, next try, last error).
- Logs (notifications worker, `celerylogs*/celery_logs_of_server.log`):
  `Email kept for retry`, `Email sent on retry`, `Email given up after`, and the
  task result `email retries: sent=.. failed=.. given_up=.. waiting=..`.

## Tests

`wareApp/tests/test_email_retries.py`: failure classification; kept only for
passing failures and allowed notifications; queued and direct sends; due /
not-due; still refused backs off and stops the run; back-off steps and giving
up after 24 h; the beat task.

## Rolling back

Set `NOTIFICATION_RETRY_HOURS=0` (no new rows, no retry task), or revert the
commit; migration 0109 only adds the `PendingEmail` table.

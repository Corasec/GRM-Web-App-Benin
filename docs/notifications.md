# Citizen Notifications — How They Work and What Remains to Be Wired

This document describes **what the code currently does** to keep citizens informed about their complaint, and the configuration / administrative steps still needed before messages are actually sent in Benin.

> **Status (November 2026):** the code is functional and tested, but **no SMS provider is configured or budgeted yet**. In the current Docker image SMS are only *simulated* (written to the logs, see [§4](#4-current-production-behaviour)).

---

## 1. When is a citizen notified?

At registration the citizen chooses how to follow their complaint (`Issue.contact_medium`):

| Choice | Value | Notified by the system? |
|---|---|---|
| Does not want to be contacted | `anonymous` | No |
| Updates through the facilitator / committee who registered the complaint | `facilitator` | No — the facilitator follows the complaint in the mobile app and informs the citizen |
| Direct alerts (email, SMS, WhatsApp) | `channel-alert` | **Yes**, on the contact given (`contact_method` + encrypted contact) |

For citizens who asked for direct alerts, a message is sent **immediately by the action itself** (no queue, no background task):

| Event | Triggered by | Type |
|---|---|---|
| Complaint registered | mobile API, dashboard intake | `created` |
| Status changed (accepted, rejected, resolved) | mobile API, dashboard actions | `status_changed` (includes the resolution or the reject reason) |
| Complaint assigned by hand | dashboard | `assigned` |
| Appeal raised | mobile API | `appealed` (includes the appeal reason) |
| Complaint escalated to the next committee | *planned with backlog item 7* | `escalated` |

A failed send is logged and **never blocks the action** (the complaint is still saved).

Code: [`grm/notifications.py`](../src/grm/notifications.py) — `send_issue_notification(issue, notification_type)`.

> The former `send_sms_message` / `send_mail_message` Celery tasks were removed: they crashed on every run and duplicated the messages above. Migration `issues/0035` deletes their schedules.

---

## 2. Message content

- **SMS**: short text, tracking code first so it is never lost, followed by the resolution / reason when relevant. Long texts are sent as a multi-part SMS (capped at 1600 characters, the Twilio limit) instead of being cut at 160 characters.
- **Email**: the full message ("Cher citoyen, …").
- **Language**: Django translations (`locale/fr`). French SMS texts deliberately **avoid accents**: an SMS containing accents is encoded in UCS-2, i.e. 70 characters per part instead of 160, which doubles the cost. Keep this rule when editing the translations.
- **Phone numbers** are normalised to the international format with `COUNTRY_CALLING_CODE` (`229`, `+229` and `00229` are all accepted): `01 97 00 00 00` → `+2290197000000`.
- **WhatsApp**: contacts who chose WhatsApp currently receive an **SMS** (see [§6](#6-whatsapp)).

---

## 3. Configuration

| Variable | Used for | Notes |
|---|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS ([`sms_client.py`](../src/sms_client.py)) | `TWILIO_FROM_NUMBER` must be a Twilio number or an approved alphanumeric sender ID |
| `TWILIO_DEBUG_MODE` | Simulation | `True` → SMS are printed to the logs instead of being sent. Set in `local_settings.py` |
| `COUNTRY_CALLING_CODE` | Phone numbers | `229` for Benin |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Email ([`mail_client.py`](../src/mail_client.py)) | Standard SMTP; the sender is `EMAIL_HOST_USER` |

The same SMS client is used by the **staff reminders** of the performance diagnostics page (inactive case managers / facilitators).

---

## 4. Current production behaviour

The production image does not contain a `local_settings.py`, so Django loads [`local_settings_template.py`](../src/grm/local_settings_template.py), which sets `TWILIO_DEBUG_MODE = True`. Consequences:

- **SMS are not sent**, only written to the container logs (`--- SMS SIMULATION ---`). This is the safe behaviour until a provider is budgeted.
- **Emails are sent for real** as soon as the `EMAIL_*` variables point to a working SMTP server.

To send real SMS: provide a `local_settings.py` (or make `TWILIO_DEBUG_MODE` an environment variable) with `TWILIO_DEBUG_MODE = False`, and set the Twilio variables. This is part of the production configuration review (backlog item 25).

---

## 5. Choosing an SMS provider — recommendations

Nothing is contracted yet. Points to settle with the administration before budgeting:

1. **Volume and cost.** A complaint followed by direct alerts generates roughly 3 to 5 SMS (registration, acceptance, resolution or rejection, possibly appeal and escalation); a long resolution text can take 2 or 3 SMS parts. Multiply by the expected share of citizens choosing direct SMS alerts (most complaints are followed through the facilitator, which costs nothing). Ask each provider for the price per SMS part to Benin operators.
2. **Sender identity.** Citizens trust a recognisable sender ("MGP-COSO") more than an unknown number. Check with the provider and the national telecom regulator whether an alphanumeric sender ID must be registered for Benin and how long it takes.
3. **Provider options.**
   - **Twilio** — already wired (`sms_client.py`); simplest path, only configuration is needed. International pricing.
   - **Africa's Talking** — an adapter already exists (`integrations/providers/africas_talking.py`) but is **not connected** to the notification flow. Check its coverage and pricing for Benin before choosing it.
   - **A local aggregator / operator** (often cheaper for national traffic) — would need a small adapter (an HTTP call), same pattern as below.
4. **Start with email + facilitator follow-up** if the SMS budget is not available at launch: the code already skips SMS safely in simulation mode.

### Wiring another SMS provider

`sms_client.send_sms(to, body)` is the single entry point used by the notifications and the staff reminders. To switch provider without touching the callers:

1. Add a setting, e.g. `SMS_PROVIDER = env("SMS_PROVIDER", default="twilio")`.
2. In `sms_client.py`, dispatch on it: keep the current Twilio code for `twilio`; for `africastalking`, call `africastalking.initialize(username, api_key)` then `africastalking.SMS.send(message=body, recipients=[to], sender_id=...)` (the existing adapter shows the call and the status codes to check: 100/101/102 = accepted).
3. Read the credentials from environment variables (never commit them) and add them to `docker/app/docker-compose.yaml`.
4. Keep the `TWILIO_DEBUG_MODE`-style simulation switch so test environments never send real messages.

---

## 6. WhatsApp

Sending WhatsApp messages (through Twilio or Meta directly) requires a **WhatsApp Business sender approved by Meta** and, for messages sent outside a conversation opened by the citizen, **pre-approved message templates**. Until this is done, WhatsApp contacts get an SMS. Once approved, the change is limited to `_send_sms_notification` in `grm/notifications.py` (send to `whatsapp:+229…` with Twilio) — backlog item 14.

---

## 7. Testing

- Unit tests: [`grm/tests/unit_tests/test_notifications.py`](../src/grm/tests/unit_tests/test_notifications.py) (who is notified, number format, SMS content, appeal, French text without accents).
- Locally, keep `TWILIO_DEBUG_MODE = True` and read the simulated SMS in the server output.

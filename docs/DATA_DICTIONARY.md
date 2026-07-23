# Data dictionary

Version 0.1 uses a deliberately small operational model. Every CSV value is loaded as text; the reference implementations perform only the conversions needed for version ordering and ISO-8601 date comparison.

## Input tables

### `programs.csv`

| Field | Meaning |
|---|---|
| `program_id` | Synthetic source-system program key |
| `program_name` | Human-readable synthetic program label |

### `program_mappings.csv`

| Field | Meaning |
|---|---|
| `program_id` | Program key to map |
| `reporting_program` | Generic reporting category used by the example |

A program may intentionally have no row in this table. Reference logic must preserve its encounters and flag them as unmapped.

### `referrals.csv`

| Field | Meaning |
|---|---|
| `referral_id` | Synthetic referral key |
| `patient_id` | Obvious synthetic person token beginning with `SYN-` |
| `program_id` | Program receiving the referral |
| `referred_at` | ISO-8601 referral timestamp |

### `appointments.csv`

| Field | Meaning |
|---|---|
| `appointment_id` | Synthetic scheduling-event key |
| `patient_id` | Obvious synthetic person token |
| `program_id` | Scheduled program |
| `scheduled_at` | ISO-8601 appointment timestamp |
| `status` | Scheduling status such as `completed` or `cancelled` |

Appointment status is not treated as interchangeable with encounter status.

### `encounters.csv`

| Field | Meaning |
|---|---|
| `encounter_row_id` | Unique physical row key |
| `source_event_id` | Stable logical event key shared by corrected versions |
| `version` | Integer-like version; highest value is current |
| `patient_id` | Obvious synthetic person token |
| `program_id` | Program associated with the event |
| `appointment_id` | Linked appointment, or an empty string |
| `referral_id` | Linked referral, or an empty string |
| `occurred_at` | ISO-8601 service timestamp |
| `status` | Event status such as `completed`, `cancelled`, or `voided` |
| `updated_at` | ISO-8601 source update timestamp used as a deterministic tie-break |

If version and update time are both tied, descending `encounter_row_id` is the final tie-break.

### `reporting_periods.csv`

| Field | Meaning |
|---|---|
| `period_id` | Stable expectation key |
| `period_label` | Human-readable label |
| `start_date` | Inclusive ISO date |
| `end_date` | Inclusive ISO date |

Periods are data rather than hidden runtime assumptions. A case can therefore represent fiscal, calendar, or custom comparison windows.

## Expected outputs

### `expected_metrics.csv`

The composite key is `period_id` plus `metric_id`.

| Metric | Definition |
|---|---|
| `raw_completed_rows` | All physical encounter rows marked completed within the period, before version resolution |
| `completed_service_events` | Current logical events marked completed within the period |
| `unique_patients_served` | Distinct synthetic patient tokens among current completed events |
| `mapped_completed_events` | Current completed events with a non-empty program mapping |
| `unmapped_completed_events` | Current completed events without a usable program mapping |
| `referrals_started` | Referrals whose referral timestamp falls in the period |
| `referrals_with_first_service` | In-period referrals with at least one linked current completed encounter on or after referral |

`referrals_with_first_service` does not require the service itself to occur before the reporting period ends. That choice is explicit and can be challenged through a future case.

### `expected_quality.csv`

The key is `check_id`.

| Check | Definition |
|---|---|
| `source_events_with_multiple_versions` | Distinct source-event IDs represented by more than one physical row |
| `current_voided_events` | Current logical events whose status is voided |
| `unmapped_completed_encounters` | Current completed events without a usable program mapping |
| `completed_encounter_cancelled_appointment` | Current completed events linked to an appointment marked `cancelled` or `canceled` |
| `completed_encounter_before_referral` | Current completed events timestamped before their linked referral |
| `completed_appointments_without_completed_encounter` | Appointments marked completed without a linked current completed event |

Quality counts are deliberately separate from reporting metrics. A record can contribute to activity and simultaneously require investigation.

## Data constraints

- All times are UTC ISO-8601 strings in the fixtures.
- All dates are compared inclusively.
- IDs are case-local; no cross-case relationship is implied.
- The suite contains no direct identifiers, clinical content, diagnoses, treatments, or outcomes.
- Labels and reporting categories are generic examples, not official definitions.

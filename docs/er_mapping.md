# ER diagram → database tables

The ER diagram uses conceptual names; the database keeps its table names. This is the one-to-one mapping. The same map drives the in-app **Data map** (`backend/app/datamap.py`).

| ER entity | Table | Notes |
|---|---|---|
| Patient | `patients` | `age` is derived from `dob` (not stored); `mrn` unique; optional `abha_number`, `abha_address` |
| Registration | `encounters` | One visit (OPD / IPD / emergency / day care). Status OPEN → DISCHARGED → BILLED |
| Doctor | `doctors` | `department_id` → `departments`; consultation fee via `consult_service_code` |
| Consultation | `consultations` | Registration *includes* Consultation; Doctor *conducts* it; posts the consultation charge |
| Prescription | `prescriptions` | Order header with coded `icd_code` (from `diagnosis_catalog`) and `snomed_code` |
| Radiology Order / Result | `radiology_orders` / `radiology_results` | SNOMED-coded study; result posts the charge |
| Lab Order / Lab Result | `lab_orders` / `lab_results` | LOINC-coded test; result posts the charge |
| Pharmacy Order / Medication Issue | `pharmacy_orders` / `dispenses` | Dispense uses the earliest-expiring stock batch and posts the charge |
| Procedure Order / Procedure Performed | `procedure_orders` / `procedures_performed` | SNOMED-coded; `outsourced` flag bills only the service used |
| Ward (Registration *admits* Ward) | `wards`, `room_stays` | `room_stays` is the "admits" relationship with dates; bed days post at discharge |
| Service | `services` (+ `tax_rules`) | Price list; GST rate and HSN/SAC come from the linked tax rule |
| Payer Rate | `payer_rates` | Same service, different price per payer route / TPA |
| Charge (was "Bill Item") | `charges` | Linked to Registration, so charges build up before any bill (running bill). `charge_type` CHARGE / REVERSAL / PACKAGE_ADJ |
| Bill | `invoices` | One final bill per visit; `due_date`, `discount_paise`; payment status is derived |
| Bill Line (weak entity) | `invoice_lines` | Partial key `line_no` under its Bill; each copies one Charge |
| Payment | `receipts` | `status` PENDING / SUCCEEDED / FAILED / TIMEOUT; only SUCCEEDED reduces the balance; retries link via `retry_of` |
| Insurance | `insurance_policies` | Patient-level policy; `coverages` records which policy a visit uses and its verification |
| Insurance Claim | `claims` | Several attempts per bill (`attempt_no`, `parent_claim_id`); APPROVED / PARTIAL / REJECTED |

Workflow tables (the workflow diagram needs them; the minimal ER diagram does not show them):

| Workflow step | Table |
|---|---|
| Appointment schedule | `appointments` |
| Insurance verification | `coverages.eligibility_status` |
| Pre-authorisation | `preauths` |
| Deposit / co-pay at intake | `advances` (unused deposit → `refunds`) |
| Partly approved / rejected → patient, or write-off | `balance_adjustments` |
| Reminder engine, patient notification | `notifications` |
| Pre-bill audit | computed by `GET /api/encounters/{id}/audit`; corrections are REVERSAL rows in `charges` |
| Who did what | `audit_events` (with `actor`) |

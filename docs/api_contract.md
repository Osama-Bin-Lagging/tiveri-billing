# Tiveri demo API (v3, schema version 2)

FastAPI serves http://127.0.0.1:8000 (interactive docs at `/docs`). Next.js calls it through same-origin `/api`. All data is synthetic; insurer, PM-JAY, SMS and GST portal actions are simulated.

Money is integer paise. Dates are ISO. Errors return `{ "detail": "message" }`. Sign in with `POST /api/auth/login` and send `Authorization: Bearer <token>`. Logins: `reception`, `doctor` (also `doctor2`, `doctor3`), `lab`, `pharmacy`, `admin` — password `Demo@1234`.

Reads are open to every desk. Writes are limited by desk (403 otherwise).

## Reception
| Endpoint | Purpose |
|---|---|
| POST /api/patients | Register a patient (MRN generated; optional 14-digit ABHA) |
| POST /api/patients/{id}/policies | Add an insurance policy (PRIVATE, PMJAY, CGHS, CORPORATE) |
| POST /api/appointments | Book an appointment (logs an APPOINTMENT notification) |
| POST /api/appointments/{id}/check-in | Open the visit (Registration) with payment mode SELF / CASHLESS / REIMBURSEMENT |
| POST /api/encounters | Walk-in visit for an existing patient |
| POST /api/coverage/{encounter_id}/verify | Simulated insurance verification (Reception or Billing) |
| POST /api/advances | Deposit / co-pay at intake (Reception or Billing) |

## Doctor
| Endpoint | Purpose |
|---|---|
| POST /api/clinical/consultations | Record the consultation; posts the consultation fee |
| POST /api/clinical/prescriptions | Coded ICD-10 diagnosis plus any lab / radiology / procedure / medicine orders; optional `admit: {ward_id}` |
| POST /api/clinical/orders/cancel | Cancel a pending order (not charged) |
| POST /api/procedures/{id}/perform | Record a performed procedure; posts its charge |
| POST /api/encounters/{id}/discharge | End of visit: closes the ward stay and posts bed days. Blocked while orders are pending |
| POST /api/his/events | Generic HIS charge event (legacy feed; the audit flags charges with no completed service) |

## Diagnostics and pharmacy
| Endpoint | Purpose |
|---|---|
| POST /api/lab/orders/{id}/complete | Lab result (LOINC); posts the charge once; repeat with the same value is a no-op |
| POST /api/radiology/orders/{id}/report | Radiology report (SNOMED); posts the charge |
| POST /api/pharmacy/dispense | Dispense against a pharmacy order from the earliest-expiring batch; IPD supply is GST-exempt |

## Billing and payer
| Endpoint | Purpose |
|---|---|
| GET /api/encounters/{id}/audit | Pre-bill audit: BLOCK and WARN findings |
| POST /api/charges/{id}/reverse | Reverse a charge with a negative REVERSAL line (before billing) |
| POST /api/packages/apply | Package price; included services are offset with PACKAGE_ADJ lines (original prices kept) |
| POST /api/preauth, POST /api/preauth/{id}/decision | Pre-authorisation request and simulated decision |
| POST /api/invoices | Generate the bill (needs a discharged visit and a passed audit) |
| POST /api/claims | Submit the claim for the payer share |
| POST /api/claims/{id}/decision | Simulated insurer decision: APPROVED, PARTIAL (amount + reason) or REJECTED (reason) |
| POST /api/claims/{id}/resubmit | Resubmit the latest rejected claim with a correction note |
| POST /api/invoices/{id}/shortfall | Move what the insurer will not pay TO_PATIENT, or WRITE_OFF |
| POST /api/receipts | Payment: CASH / TRANSFER succeed at once; UPI / CARD / GATEWAY start PENDING |
| POST /api/receipts/{id}/outcome | Simulate SUCCEEDED / FAILED / TIMEOUT |
| POST /api/receipts/{id}/retry | Retry a failed or timed-out payment with another method |
| POST /api/invoices/{id}/remind | Reminder for an outstanding balance (simulated SMS) |
| POST /api/refunds | Refund unused deposit after billing |
| POST /api/rates, POST /api/demo/reset | Rate card update; rebuild all demo data |

## Reads
`GET /api/health` · `/api/catalog` · `/api/patients` · `/api/patients/{id}` · `/api/encounters/{id}` · `/api/appointments` · `/api/diagnostics/queue` · `/api/pharmacy/queue` · `/api/pharmacy/stock` · `/api/dashboard` · `/api/ar` · `/api/gstr1?month=YYYY-MM` · `/api/analytics?month=YYYY-MM` · `/api/audit`

## Data map
| Endpoint | Purpose |
|---|---|
| GET /api/datamap/schema | ER entities, attributes, primary and foreign keys, relationships with cardinality, layout |
| GET /api/datamap/{patient_id}?encounter_id= | Every record for that patient per entity, plus the audit timeline (who did what) |

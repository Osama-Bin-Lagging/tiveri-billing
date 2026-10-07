# Tiveri demo API

FastAPI serves http://127.0.0.1:8000 and interactive documentation at /docs. Next.js calls it through /api on port 3000. All cases and decisions are synthetic. There are no live HIS, insurer, PM-JAY, CGHS or GST portal links.

All money uses integer paise. Dates use ISO format. Errors return FastAPI `{ "detail": "message" }`. Payer routes are `SELF`, `PRIVATE`, `PMJAY`, `CGHS`, `CORPORATE`. Settings are `OPD`, `IPD`, `EMERGENCY`, `DAY_CARE`.

POST `/api/auth/login` accepts a demo username and password and returns a bearer token. All other `/api` endpoints except health require `Authorization: Bearer <token>`. GET `/api/auth/me` returns the staff role and POST `/api/auth/logout` ends the current session. Admin and billing can change financial records, doctor can add clinical notes, prescriptions and HIS service events, coder can add diagnosis reviews, and pharmacy can dispense.

## Reads

| Endpoint | Content |
| --- | --- |
| GET /api/health | Server and PostgreSQL status |
| GET /api/bootstrap | Charge master, payer rates, seeded cases and linked records |
| GET /api/dashboard | Worklist and headline balances |
| GET /api/encounters/{id} | Patient profile and history, doctor notes, prescriptions, coding reviews, running bill and payer state |
| GET /api/clinical/queue | Prescriptions with quantity already dispensed |
| GET /api/pharmacy/stock | Unexpired stock by item and batch |
| GET /api/gstr1?month=YYYY-MM | Tables 4, 7, 8, 12, 13 review packet with warnings |
| GET /api/ar?as_of=YYYY-MM-DD | Outstanding invoices and 30/60/90 day buckets |
| GET /api/analytics?month=YYYY-MM | Collections, invoiced revenue, payer mix, departments |
| GET /api/audit?limit=100 | Recent recorded actions |

## Writes

| Endpoint | Purpose |
| --- | --- |
| POST /api/encounters | Create invented patient and encounter |
| POST /api/his/events | Capture idempotent delivered service |
| POST /api/clinical/notes | Add a doctor note with optional provisional ICD-10 and invented CPT-style identifier |
| POST /api/clinical/prescriptions | Order a stocked medicine for the patient |
| POST /api/coding/reviews | Record a coder-reviewed ICD-10 and procedure identifier |
| POST /api/encounters/{id}/room-stays | Add a dated IPD room stay |
| POST /api/pharmacy/dispense | Decrement one unexpired batch and post charge |
| POST /api/packages/apply | Add package, zero included service charges |
| POST /api/advances | Collect advance before final invoice |
| POST /api/refunds | Return unused advance after billing |
| POST /api/coverage/{id}/verify | Simulate PM-JAY eligibility check |
| POST /api/preauth | Submit synthetic preauthorisation |
| POST /api/preauth/{id}/decision | Record synthetic approval or rejection |
| POST /api/invoices | Finalise one immutable itemised invoice |
| POST /api/claims | Submit a synthetic payer claim with document checklist |
| POST /api/claims/{id}/decision | Record synthetic claim decision |
| POST /api/receipts | Record actual patient or payer money |
| POST /api/rates | Change a future service rate for a payer |
| POST /api/demo/reset | Restore original invented data |

See /docs for request and response schemas. Demo reset is enabled only when `DEMO_MODE=1`.

## Key behavior

- HIS retries with the same `source_event_id` and payload return `duplicate: true`; a conflicting retry returns HTTP 409.
- Pharmacy dispensing checks the doctor's matching prescription and remaining quantity for prescription items.
- Price and tax are snapped on charges. The effective-dated tax rule is selected when charge capture occurs.
- Claims use the latest coder-reviewed ICD-10 and procedure identifier. `CPT-DEMO-01` is an invented classroom identifier, not a licensed CPT catalog code.
- A final invoice locks its itemised lines and sets the encounter to billed.
- An approved claim remains outstanding until a separate receipt is posted.
- PM-JAY demo blocks patient receipts and requires a simulated check and preauthorisation for its seeded IPD case.
- The tax review packet is generated from invoices and includes exempt supply data. It is not upload-ready government JSON.

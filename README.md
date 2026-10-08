# Syndicate 1 Billing

A DH 308 teaching prototype of a hospital billing system integrated with the HIS, for an Indian hospital. Next.js website, FastAPI API, PostgreSQL 16. All patients, prices, payer references and clinical details are invented.

Five staff desks share one patient record:

- **Reception**: registration with MRN and optional ABHA, insurance policy, appointment, check-in, insurance verification, deposit.
- **Doctor**: consultation, a coded ICD-10 diagnosis, and any mix of lab, radiology, procedure and medicine orders; admission to a ward; discharge.
- **Diagnostics**: lab results (LOINC) and radiology reports (SNOMED CT). Each completed test posts its own charge.
- **Pharmacy**: dispensing from the earliest-expiring batch. Inpatient supply is GST-exempt; outpatient sale follows the item rate.
- **Billing**: running bill, pre-bill audit with charge reversal, bill generation, pre-authorisation, packages, claims (full, partial, rejected, resubmitted), shortfall to the patient or written off, payments that can fail and be retried, reminders and notifications.

Every desk also has a **Data map**: the ER diagram drawn live for the selected patient. Each entity box shows how many records exist; click it to see every attribute, and click a linked ID to follow the relationship. A timeline shows who did what.

The ER-name to table mapping is in `docs/er_mapping.md`. The API is summarised in `docs/api_contract.md`.

External insurer, PM-JAY, CGHS, SMS and GST portal actions are simulated. Do not enter real patient details. The shared classroom password is not suitable for a live hospital.

## Fastest local start: Docker

Install Docker Desktop, then from the repository root:

```powershell
docker compose up --build
```

Open http://127.0.0.1:3000. API documentation is at http://127.0.0.1:8000/docs. PostgreSQL is exposed only on localhost port 55433. The demo database seeds itself on first start. To restore the original invented cases, sign in at the billing desk and select Reset demo. Reset ends all current sessions, so sign in again. Data persists in the Compose volume across restarts.

## Native local start

Requirements: Node.js 24, Python 3.12, PostgreSQL 16. Create a PostgreSQL database called `tiveri_demo` and a user with rights to create tables. Set `DATABASE_URL` to its connection string. The app creates tables and synthetic seed cases automatically.

In terminal 1, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DATABASE_URL = "postgresql://USER:PASSWORD@127.0.0.1:5432/tiveri_demo"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In terminal 2:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:3000. `frontend/next.config.ts` sends same-origin `/api/*` requests to the local FastAPI server. If the API uses a different address, set `API_INTERNAL_URL` before running or building Next.js.

## Demo walkthrough

Open the site and choose a desk. The password for every desk is `Demo@1234`. Sign out from the sidebar to change desks; the selected patient stays selected. **Reset demo** (Billing desk) rebuilds all demo data.

**Full self-pay visit (new patient)**
1. **Reception**: register a patient (try an ABHA number such as `56-1234-9876-0001`), book an appointment or start a walk-in visit as Self-pay, and take a deposit.
2. **Doctor**: record the consultation, pick an ICD-10 diagnosis, tick tests (for example CBC and chest X-ray), add a medicine, and save. Tick "Admit to a ward" to make it an inpatient stay.
3. **Diagnostics**: enter the lab result and the radiology findings.
4. **Pharmacy**: dispense the medicine.
5. **Doctor**: end the visit, or discharge the patient. Discharge is blocked while any order is pending.
6. **Billing**: the pre-bill audit runs; generate the bill. Collect by UPI, click *Fail*, retry by card, click *Success*. The bill is settled and a notification is logged.
7. Open **Data map** to show every record the visit created.

**Ready-made cases** (Billing desk)

| Patient | What to show |
|---|---|
| Rohan Iyer | Pre-bill audit fails on a duplicate CBC charge, then *Reverse this charge*, *Re-audit* and *Generate bill* |
| Dev Mehta | Cashless claim awaiting a decision: *Approve part*, record the insurer payment, *Bill the patient* for the rest, *Send reminder*, then collect |
| Nadia Roy | Rejected claim: *Resubmit claim*, *Approve in full*, record the insurer payment |
| Farah Khan | PM-JAY package with original prices kept: Pharmacy dispenses ORS, Doctor discharges, Billing bills and claims |
| Manoj Shah | UPI payment pending: *Fail* or *Timeout*, then retry |
| Sanjay Kumar | 40-day-old unpaid bill: *Send reminder*; shows in the unpaid-bill ageing report |
| Ananya Rao | Open visit with tests and a medicine waiting (fills the Diagnostics and Pharmacy worklists) |
| Asha Kulkarni | Registered with ABHA and an Alpha TPA policy, no visit yet. Use her for a live cashless admission |

## Rules the system enforces

- Charges post only from completed work: consultation, test result, radiology report, procedure, dispense, or ward days at discharge. A source event ID is unique: an identical retry returns the original charge, and a changed retry is rejected.
- Prices and tax are copied onto each charge and again onto each bill line. Nothing is deleted or overwritten. Corrections are REVERSAL lines; packages add PACKAGE_ADJ lines and keep the original prices visible.
- The bill needs a discharged visit and a pre-bill audit with no blocking findings. The audit checks:
  - diagnosis present
  - pending orders
  - duplicate or unsupported charges
  - GST review
  - ward days
  - insurance verification
  - pre-authorisation
  - PM-JAY package
- A claim approval is not a payment. Only SUCCEEDED payments reduce the balance. A part-approved or rejected claim's shortfall goes to the patient or is written off. PM-JAY beneficiaries are never charged.
- Money is stored as integer paise. GST uses effective-dated rules. The tax and HSN values are teaching assumptions.
- The database schema is versioned. On startup an older demo database is rebuilt from `backend/app/schema.sql` and reseeded.

## Tests

With a PostgreSQL 16 database available (set `DATABASE_URL`):

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api.py -q
cd frontend
npm run build
```

The 9 API scenarios cover:
- a full self-pay OPD visit with a payment failure and retry
- a cashless admission with an audit correction and a partly approved claim
- a rejected claim that is resubmitted
- a PM-JAY package
- cancelled orders
- the seeded audit case
- payment timeout and an overdue reminder
- Data map coverage of every ER entity
- reports

## Project layout

- `backend/app/main.py`: app, schema versioning, desk permissions, sign-in, reports
- `backend/app/core.py`: shared rules (pricing, charge posting, balances)
- `backend/app/reception.py`, `clinical.py`, `billing.py`, `payer.py`, `records.py`, `datamap.py`: one module per desk / area
- `backend/app/seed.py`: synthetic demo data, built through the same functions the desks use
- `backend/app/schema.sql`: PostgreSQL schema (ER names noted per table)
- `frontend/app/page.tsx`: shell; `frontend/app/desks/*.tsx`: the five desks; `frontend/app/DataMap.tsx`: live ER view
- `tests/test_api.py`: database-backed API scenarios
- `docs/er_mapping.md`, `docs/api_contract.md`, `docs/sources.md`; `prd.md` for scope and priorities
- `docs/*_er.mmd`: earlier design sketches, kept for reference

## Deployment boundary

The Compose files can run on a private AWS EC2 instance for a classroom demonstration. Keep ports behind a VPN or security group that allows only the presentation team. A hospital deployment needs strong identity management, TLS, secrets management, encryption, backups, monitoring, an approved data retention policy, real payer integration agreements, and reviewed tax/rate masters. The classroom sign-in does not provide these production controls. Do not expose it publicly or store personal health information.

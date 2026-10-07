# Tiveri Billing

A working DH 308 teaching prototype for an Indian hospital. The website uses Next.js, the API uses FastAPI, and records persist in PostgreSQL. All patient labels, payer references, prices and clinical details are invented.

The role-based demo connects admin and billing, doctor, medical coder, and pharmacy workspaces around one patient record. It includes history, care notes, provisional ICD-10 and invented CPT-style identifiers, coding review, prescriptions, batch-tracked dispensing, HIS-style service events, and a running bill. Billing also covers OPD, IPD, emergency and day care encounters; payer rates; room stays; packages; advances and refunds; simulated TPA and PM-JAY workflows; claims and receipts; GSTR-1 review; receivables; reports; and an audit trail.

External insurer, PM-JAY, CGHS and GST portal actions are simulated. Do not enter real patient details or use the demo tax settings for real invoices. The local demo accounts use a shared training password and are not suitable for a live hospital. CPT-DEMO-01 is an invented identifier, not an AMA CPT code or catalog entry.

## Fastest local start: Docker

Install Docker Desktop, then from the repository root:

```powershell
docker compose up --build
```

Open http://127.0.0.1:3000. API documentation is at http://127.0.0.1:8000/docs. PostgreSQL is exposed only on localhost port 55433. The demo database seeds itself on first start. To restore the original invented cases, sign in as admin and use Reset under Audit. Reset ends all current sessions, so sign in again. Data persists in the Compose volume across restarts.

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

## Demo sign-in and handoff

At http://127.0.0.1:3000 choose **Admin / billing**, **Doctor**, **Medical coder**, or **Pharmacy**. The password for every classroom account is `Demo@1234`. The sidebar has **Sign out**. The admin can open the full billing desk from the patient workspace.

1. As admin, open Rohan Iyer (E-IPD-08). Add a one-day private room stay. The running bill shows ₹6,000 plus 5% GST, subject to the specified non-ICU room condition.
2. Sign out and enter as doctor. Open Ananya Rao (E-OPD-01). Review her invented history, save a note with a provisional ICD-10 code and invented CPT-style procedure identifier, mark a service delivered, and add a prescription.
3. Sign out and enter as medical coder. Review the doctor's note and save an ICD-10 and procedure-code review. A payer claim uses the latest coder-reviewed code.
4. Sign out and enter as pharmacy. Choose the prescription and dispense it. Stock falls and the item charge appears on the same patient bill. The catalog shows a 5% medicine, an illustrative nil-rated medicine category, and a 5% device example.
5. Return as admin, open the full billing desk, and show the invoice, TPA or scheme workflow, tax review, and receivables.

## Other billing screens

- Overview: live worklist and balances.
- Encounters: create a synthetic patient, review charges, and finalise an itemised invoice. Doctors record delivered service events from their workspace.
- Claims: choose Demo Patient B for a simulated TPA preauthorisation, final invoice, claim decision and payer receipt. Approval alone does not reduce the balance.
- PM-JAY: choose Demo Patient C, run the simulated beneficiary check, record simulated preauthorisation and finalise its package. Patient collection is blocked.
- Tax review: Table 4, 7, 8, 12 and 13 review data for the selected month. Downloaded JSON is a review packet, not an upload-ready government return.
- Receivables and Reports: outstanding age buckets, payer mix and department totals.
- Catalog: view services and change a future payer rate. Existing charge prices stay unchanged.
- Audit: inspect write history and reset the synthetic cases.

## Important database rules

- A HIS `source_event_id` is unique. An identical retry returns the original charge; a changed retry is rejected.
- Service prices and tax classification are copied to each charge. Final invoice lines copy them again.
- An encounter has one final invoice. Every charge can appear on only one final invoice.
- A payer approval creates no receipt. Only a posted receipt reduces the outstanding balance.
- PM-JAY demo encounters block patient collection and require a simulated check plus preauthorisation for the seeded IPD case.
- Stock dispensing uses an unexpired batch with enough quantity and posts stock and charge in one database transaction.
- Amounts are stored as integer paise. Tax calculations use the seeded effective-dated rule on charge capture.
- The tax and HSN values are teaching assumptions. A real hospital must load current item-level classifications and contracted prices.

## Tests

With a local PostgreSQL database available:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api.py -q
cd frontend
npm run build
```

The API tests reset the synthetic database and exercise role access, clinical notes, coding review, prescription-linked dispensing, nil and 5% tax examples, room rent, OPD, TPA, PM-JAY, packages, payment, refunds, tax review and receivables. The four role screens are also checked in a live browser against the local servers.

## Project layout

- `frontend/app/`: Next.js UI
- `backend/app/main.py`: FastAPI endpoints and billing rules
- `backend/app/schema.sql`: PostgreSQL schema
- `tests/test_api.py`: database-backed API scenarios
- `docs/core_er.mmd`, `docs/payer_er.mmd`, `docs/clinical_er.mmd`: Chen-style Mermaid ER source used by the presentation
- `docs/api_contract.md`: API summary
- `docs/sources.md`: course and official research sources
- `docs/DH308_Billing_Prototype_Guide.pdf`: illustrated local build and AWS classroom demo guide
- `docs/DH308_Billing_Prototype_Guide.tex`: editable guide source
- `presentation/DH308_HIS_Billing_Final.pptx`: final presentation deck without speaker notes
- `docker-compose.yml`: local three-service stack

## Deployment boundary

The Compose files can run on a private AWS EC2 instance for a classroom demonstration. Keep ports behind a VPN or security group that allows only the presentation team. A hospital deployment needs strong identity management, TLS, secrets management, encryption, backups, monitoring, an approved data retention policy, real payer integration agreements, a licensed CPT catalog if required, and reviewed tax/rate masters. The classroom sign-in does not provide these production controls. Do not expose it publicly or store personal health information.

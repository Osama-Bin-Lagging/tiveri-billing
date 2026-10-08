# Tiveri Billing

A working DH 308 teaching prototype for an Indian hospital. The website uses Next.js, the API uses FastAPI, and records persist in PostgreSQL. All patient labels, payer references, prices and clinical details are invented.

The visible demo has four staff desks: doctor, laboratory, pharmacy, and billing. They share an existing patient record. A doctor-confirmed observation admission creates an inpatient encounter with ICD-10 E11.9, an HbA1c order with LOINC 4548-4 and an optional CPT 83036 reference, a prescription, and a doctor assessment charge. Completing the lab result and dispensing the medicine add their own charges to the same running bill. Billing then records a one-day private room stay and generates the itemised admission invoice on the same page. The API also supports outpatient, emergency and day care encounters, payer rates, packages, advances and refunds, simulated TPA and PM-JAY workflows, claims, receipts, GSTR-1 review, receivables, reports, and an audit trail.

External insurer, PM-JAY, CGHS and GST portal actions are simulated. Do not enter real patient details or use the demo tax settings for real invoices. The local demo accounts use a shared training password and are not suitable for a live hospital.

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

## Demo sign-in and handoff

At http://127.0.0.1:3000 choose Billing, Doctor, Laboratory, or Pharmacy. The password for every classroom account is `Demo@1234`. Sign out from the sidebar to change desks. The selected patient remains selected across roles.

For the featured admission, Billing can choose Self-pay, Cashless claim, or Reimbursement claim before the doctor starts. Self-pay and reimbursement collect the hospital bill from the patient using UPI, cash, or card; reimbursement is then pursued by the patient with their insurer outside this demo. Cashless defaults to zero co-pay for eligible charges. It shows patient payment options for any selected co-pay or excluded non-medical expenses, while the insurer claim and settlement are recorded separately. The example does not add excluded expenses to the invoice automatically.

1. Sign in as Billing, select Asha Kulkarni and review her invented history. She has no open encounter. Sign out.
2. Sign in as Doctor with Asha selected. Review the prepared diagnosis and test mapping, edit the note if needed, and select **Create admission and send orders**. The ₹500 doctor assessment posts immediately. ICD-10 E11.9 is the diagnosis. CPT 83036 is shown as an optional procedure reference, while the hospital's own HBA1C code sets the lab price.
3. Sign in as Laboratory. Asha's HbA1c order displays LOINC 4548-4. Enter the synthetic result and select **Complete test and post charge**. The ₹650 lab charge appears once on the running bill.
4. Sign in as Pharmacy. Dispense the 10 training metformin tablets from stock. This adds ₹60 to the inpatient treatment bill without a separate medicine GST charge in the prototype. The catalog also shows separate-sale medicine GST settings and a nil-rated training SKU.
5. Sign in as Billing again. Select the ₹6,000/day private non-ICU room and keep the one-day dates. Click **Add bed / room charge**. The training room rule adds ₹300 GST to that room line, subject to the official conditions.
6. Asha's running bill now has doctor, lab, medicine and room lines. Select **Generate itemised invoice**. The synthetic total is ₹7,510.00 and the invoice appears on the same page. Dev Mehta and Farah Khan retain simulated TPA and PM-JAY cases.

## Scope of the prototype

The website keeps the presentation path short. Billing staff can review a monthly GSTR-1 working summary on the patient page. The backend retains the more detailed report, receivables, rate card, advance, refund, and audit endpoints in `/docs`. The tax review packet is not an upload-ready government return.

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

The API tests reset the synthetic database and exercise the doctor, laboratory, pharmacy, bed and billing handoff, role access, duplicate lab completion, prescription-linked dispensing, nil and 5% tax examples, inpatient treatment supply, room rent, outpatient billing, TPA, PM-JAY, packages, payment, refunds, tax review and receivables. The four role screens and same-page invoice were also checked in a live browser against the local servers.

## Project layout

- `frontend/app/`: Next.js UI
- `backend/app/main.py`: FastAPI endpoints and billing rules
- `backend/app/schema.sql`: PostgreSQL schema
- `tests/test_api.py`: database-backed API scenarios
- `docs/core_er.mmd`, `docs/payer_er.mmd`, `docs/clinical_er.mmd`: earlier design sketches. The final presentation uses the supplied Chen notation ER diagram.
- `docs/api_contract.md`: API summary
- `docs/sources.md`: course and official research sources
- `docs/DH308_Billing_Prototype_Guide.pdf`: illustrated local build and AWS classroom demo guide
- `docs/DH308_Billing_Prototype_Guide.tex`: editable guide source
- `presentation/DH308_HIS_Billing_Final.pptx`: final presentation deck without speaker notes
- `docker-compose.yml`: local three-service stack

## Deployment boundary

The Compose files can run on a private AWS EC2 instance for a classroom demonstration. Keep ports behind a VPN or security group that allows only the presentation team. A hospital deployment needs strong identity management, TLS, secrets management, encryption, backups, monitoring, an approved data retention policy, real payer integration agreements, and reviewed tax/rate masters. The classroom sign-in does not provide these production controls. Do not expose it publicly or store personal health information.

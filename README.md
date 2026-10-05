# Tiveri Billing

A working DH 308 teaching prototype for a 20 to 50 bed Indian hospital. The website uses Next.js, the API uses FastAPI, and records persist in PostgreSQL. All patient labels, payer references, prices and clinical details are invented.

This prototype accepts HIS-style service events and builds a running bill. It supports OPD, IPD, emergency and day care encounters; payer rate cards; room stays; packages; batch-tracked pharmacy dispensing; effective-dated tax settings; advances and refunds; simulated TPA and PM-JAY workflows; claims and receipts; GSTR-1 review; receivables; reports; and an audit trail.

External HIS, insurer, PM-JAY, CGHS and GST portal actions are simulated. Do not enter real patient details or use the demo tax settings for real invoices. The app has no user authentication.

## Fastest local start: Docker

Install Docker Desktop, then from the repository root:

```powershell
docker compose up --build
```

Open http://127.0.0.1:3000. API documentation is at http://127.0.0.1:8000/docs. PostgreSQL is exposed only on localhost port 55433. The demo database seeds itself on first start. To restore the original invented cases, use the Reset button under Audit or call POST /api/demo/reset. Data persists in the Compose volume across restarts.

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

## What to show in the live demo

- Overview: live worklist and balances.
- Encounters: create a synthetic patient, capture a HIS event, and finalise an itemised invoice.
- Pharmacy: dispense a training item from a tracked batch and see its charge and tax snapshot appear on the encounter.
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

The API tests reset the synthetic database and exercise OPD, TPA, PM-JAY, stock, room rent, packages, payment, refunds, tax review and receivables. A Playwright browser test was also run against the live local Next.js and FastAPI servers.

## Project layout

- `frontend/app/`: Next.js UI
- `backend/app/main.py`: FastAPI endpoints and billing rules
- `backend/app/schema.sql`: PostgreSQL schema
- `tests/test_api.py`: database-backed API scenarios
- `docs/core_er.mmd`, `docs/payer_er.mmd`: Chen-style Mermaid ER source used by the presentation
- `docs/api_contract.md`: API summary
- `docs/sources.md`: course and official research sources
- `presentation/DH308_HIS_Billing_Final.pptx`: final 24-slide deck without speaker notes
- `docker-compose.yml`: local three-service stack

## Deployment boundary

The Compose files can run on a private AWS EC2 instance for a classroom demonstration. Keep ports behind a VPN or security group that allows only the presentation team. A hospital deployment needs authentication and roles, TLS, secrets management, encryption, backups, monitoring, an approved data retention policy, real payer/HIS integration agreements, and reviewed tax/rate masters. The synthetic demo does not include these controls. Do not expose it publicly or store personal health information.

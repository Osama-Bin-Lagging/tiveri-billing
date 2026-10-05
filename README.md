# Tiveri Billing

A local DH 308 prototype for a small to mid-sized Indian hospital. It connects an invented HIS service event to a running bill, final invoice, payer decision and actual receipt. The interface, HTTP API and SQLite database all run from this repository.

All patient labels, prices, policy references and payer decisions are synthetic. This project has no live HIS, insurer, PM-JAY, CGHS, ABDM or NHCX connection. It has no authentication or production tax engine, so do not deploy it as a public patient system or enter real patient details.

## Run locally

Python 3.10 or later is enough. No package install or build step is needed.

```powershell
python backend/server.py
```

On the project computer, Python is bundled with Codex but is not on the normal `PATH`. This command runs the same server there:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" backend/server.py
```

Open <http://127.0.0.1:8000/>. The app creates `demo.sqlite3` in the repository root. Stop with Ctrl+C. Set `TIVERI_DB` to another path to use a separate SQLite file, or use `--port 8080` to change the local port.

## Try the workflow

1. Open the `Demo Patient A` OPD self-pay case. Its consultation and lab events are already in the running bill. Finalise the bill and record a patient receipt.
2. Open `Demo Patient B` for private insurance. Request an invented preauthorisation, record the simulated approval, finalise the bill, submit a claim and record the final claim decision. Notice that the balance does not change until you record a receipt.
3. Open `Demo Patient C` to see a PM-JAY package placeholder. The app blocks patient copayment for this sample package. It does not verify eligibility or an official HBP rate.
4. Open the CGHS and corporate cases to see payer-specific example rates and claim paths. Actual rate cards and contract rules would have to be loaded and validated.
5. Create a new training encounter to enter your own invented case. Use `Reset demo` to restore the five original cases.

## Components

- `frontend/`: responsive HTML, CSS and JavaScript.
- `backend/server.py`: local HTTP API and billing rules.
- `backend/schema.sql`: SQLite tables, foreign keys, checks and indexes.
- `docs/*.mmd`: Mermaid ER diagram source. Rendered PNGs are in the same folder and used in the presentation.
- `tests/test_api.py`: integration checks using a temporary database and a running server.

Important database rules: a HIS `source_event_id` is unique, the chosen unit rate is copied into each charge, an encounter has at most one final invoice, a charge appears on at most one invoice line, and payer approval is recorded apart from payment. All monetary values are integer paise.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server and SQLite health |
| GET | `/api/state` | Read the demo workspace |
| POST | `/api/encounters` | Open a synthetic case |
| POST | `/api/his/events` | Record a unique service event |
| POST | `/api/preauth` | Simulate a preauthorisation request |
| POST | `/api/preauth/{id}/decision` | Simulate its response |
| POST | `/api/invoices` | Finalise an itemised bill |
| POST | `/api/claims` | Submit a demo payer claim |
| POST | `/api/claims/{id}/decision` | Simulate final approval |
| POST | `/api/payments` | Record a receipt and reduce balance |
| POST | `/api/demo/reset` | Restore invented cases |

## Test

```powershell
python -m unittest discover -s tests -v
```

On the project computer, replace `python` with the bundled executable path shown above to run the tests.

The tests launch the backend on a free loopback port, use a temporary SQLite database, send real HTTP requests, and inspect the resulting records. The separate browser check used for the project presentation clicks through the website itself.

## Scope for a real hospital

A real implementation needs role-based login, encrypted storage and backups, audit retention, current contracted tariff and GST rules, patient consent and privacy controls, clinical code validation, payer gateway access, and integration testing with the hospital's actual HIS. The current site intentionally does not claim to provide those controls.

Research and official source links are in [`docs/sources.md`](docs/sources.md).

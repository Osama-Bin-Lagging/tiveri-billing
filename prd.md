# Product Requirements Document: Syndicate 1 Billing (HIS-integrated hospital billing, teaching prototype)

## Product Overview
**Product Vision:** Show, end to end and live, how clinical work in an HIS becomes a correct, audited hospital bill and is settled by patient, insurer or scheme — with every record visible on the ER diagram.
**Target Users:** DH 308 presenters and examiners (primary); classmates exploring the demo (secondary).
**Business Objectives:** (1) Match the updated ER diagram and workflow diagram in working code. (2) Demonstrate every workflow loop live in under 10 minutes. (3) Avoid the billing gaps the project identifies: missed or duplicate charges, wrong rate, approval treated as payment, discharge delay.
**Success Metrics:** All ER entities appear on the Data map with live records; all 4 workflow loops demonstrable from seeded cases; 9 API scenarios pass; zero manual retyping of charges in the demo.

## User Personas
### Front-desk executive (Reception)
- **Goals:** register quickly (MRN, optional ABHA), capture insurance, take a deposit, check the patient in.
- **Pain points:** duplicate patient records; insurance discovered at discharge.
### Doctor
- **Goals:** record the consultation, pick a coded diagnosis, order tests/medicines, admit, discharge.
- **Pain points:** free-text diagnoses that break claims; orders lost between departments.
### Diagnostics and pharmacy staff
- **Goals:** complete the ordered work once; stock and charge stay in step.
### Billing executive
- **Goals:** bill only what was delivered, at the payer's rate, with GST; fix errors before the bill; chase claims and payments.
- **Pain points:** duplicate charges, part-approved claims with no way to recover the rest, failed UPI payments.

## Feature Requirements
| Feature | Description | Priority | Acceptance criteria |
|---|---|---|---|
| ER-complete data model | Every entity in the updated ER diagram exists as a table | Must | `GET /api/datamap/schema` lists all 22 ER entities |
| Reception desk | Registration (MRN, ABHA), policy, appointment, check-in, verification, deposit | Must | New patient → visit → deposit via UI |
| Coded doctor flow | ICD-10 picker + any lab/radiology/procedure/medicine orders; admit; discharge | Must | No hard-coded case; discharge blocked while orders pending |
| Charge on completion | Each completed service posts one priced charge; retries are idempotent | Must | Duplicate event returns the original charge |
| Pre-bill audit + correction | BLOCK/WARN findings; reverse a charge; re-audit; bill only when passed | Must | Seeded duplicate case can be corrected and billed |
| Claims loop | Approve full / part / reject; resubmit; shortfall to patient or write-off | Must | Part-approved remainder becomes patient due |
| Payment failure + retry | PENDING → SUCCEEDED / FAILED / TIMEOUT; retry with another mode | Must | Failed payment leaves the balance unchanged |
| Data map | Live, clickable ER view with records, keys and timeline | Must | Clicking a FK jumps to the related record |
| Packages without price loss | Package adds offsetting lines; original prices stay visible | Should | PACKAGE_ADJ lines keep unit price |
| Reminders and notifications | Simulated SMS for appointment, claim decision, reminder, settlement | Should | Settled bill logs a SETTLED message |
| Finance reports | Unpaid-bill ageing, GSTR-1 review packet, analytics | Could | Reports load from the Billing desk |
| Real insurer/NHCX, PM-JAY TMS, SMS, GST portal integration | Live external exchanges | Won't (this release) | Simulated only |
| FHIR / HL7 interfaces | Standard message exchange with an external HIS | Won't (this release) | Mapping explained on slides |

## User Flows
1. Reception registers → books appointment → checks in (self-pay / cashless / reimbursement) → verifies insurance → takes deposit.
2. Doctor consults → prescribes (ICD-10 + orders, optional admission) → performs procedures → discharges once orders are done or cancelled.
3. Diagnostics completes tests/reports; Pharmacy dispenses. Each posts a charge.
4. Billing runs the pre-bill audit → reverses wrong charges → re-audits → generates the bill.
5. Cashless: claim → decision (full / part / reject → resubmit) → insurer payment → shortfall to patient or write-off.
6. Patient payment → success, or fail/timeout → retry → settled → notification; outstanding → reminder.
   - Error states: blocked discharge, failed audit, rejected claim, failed payment — each has a visible next action.

## Non-Functional Requirements
- **Performance:** each desk action responds in under 1 s on the free hosting tier once warm (cold start up to 60 s).
- **Security:** classroom sign-in only, with hashed passwords and sessions and per-desk write permissions. Synthetic data only; not for real patients.
- **Compatibility:** current desktop Chrome / Safari / Edge; the Data map scrolls horizontally on narrow screens.
- **Accessibility:** semantic buttons and labels, visible status text (not colour only), ER map has an aria-label and text record view.

## Technical Specifications
- **Frontend:** Next.js 16 / React 19, one page with five desk components and a Data map.
- **Backend:** FastAPI routers per desk on PostgreSQL 16, with shared rules in `core.py`. The schema is versioned and rebuilds demo data on upgrade.
- **Infrastructure:** Vercel (web), Render (API), Neon (database), all free tier. Pushes to `main` auto-deploy.

## Analytics & Monitoring
- `audit_events` records every action with its actor; the Data map timeline and `GET /api/audit` expose it.
- `/api/health` reports the schema version for deploy checks.

## Release Planning
- **v3 (this change):** everything marked Must and Should above.
- **Next:** FHIR ChargeItem/Invoice export, interim bills for long stays, payer and bed master tables.

## Open Questions & Assumptions
- Assumption: the ER team applies the minimal 7 changes. If their final diagram differs, `docs/er_mapping.md` and the Data map layout need small updates.
- Assumption: radiology is completed at the Diagnostics desk and procedures at the Doctor desk (no extra roles).
- Assumption: ward-level stays only (no bed table); discount is stored at 0 (no discount workflow).
- Open: should examiners see FHIR output? Currently out of scope (Won't).
- Open: the live database is rebuilt on deploy; any data friends entered is lost. Acceptable for a demo.

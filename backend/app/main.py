"""Synthetic hospital billing API backed by PostgreSQL 16."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
import os
import re
import hashlib
import hmac
import secrets

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tiveri_demo@127.0.0.1:55432/tiveri_demo")
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
ROUTES = {"SELF", "PRIVATE", "PMJAY", "CGHS", "CORPORATE"}
SETTINGS = {"OPD", "IPD", "EMERGENCY", "DAY_CARE"}
PUBLIC_TABLES = ("patients", "encounters", "coverages", "tax_rules", "services", "lab_catalog", "lab_orders", "payer_rates", "pharmacy_items", "stock_batches", "package_catalog", "room_stays", "charges", "dispenses", "preauths", "invoices", "invoice_lines", "claims", "advances", "receipts", "refunds", "audit_events")
TABLES = PUBLIC_TABLES + ("staff_users", "auth_sessions", "clinical_notes", "prescriptions")


def db() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def one(conn: psycopg.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def rows(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def need(value: Any, message: str, status: int = 400) -> Any:
    if not value:
        raise HTTPException(status_code=status, detail=message)
    return value


def audit(conn: psycopg.Connection, action: str, entity: str, entity_id: Any, details: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_events(action,entity,entity_id,details) VALUES (%s,%s,%s,%s)",
                 (action, entity, str(entity_id), Jsonb(details or {})))


def password_digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def seed_staff(conn: psycopg.Connection) -> None:
    for username, display_name, role in [
        ("admin", "Riya Menon", "ADMIN"),
        ("doctor", "Dr Mira Sen", "DOCTOR"),
        ("lab", "Arjun Nair", "LAB"),
        ("pharmacy", "Nisha Shah", "PHARMACY"),
    ]:
        salt = secrets.token_hex(16)
        conn.execute("""INSERT INTO staff_users(username,display_name,role,password_salt,password_hash)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (username) DO NOTHING""", (username, display_name, role, salt, password_digest("Demo@1234", salt)))


def tax_for(conn: psycopg.Connection, rule_code: str, on_date: date | None = None) -> dict:
    result = one(conn, """SELECT * FROM tax_rules WHERE rule_code=%s AND effective_from<=%s
        AND (effective_to IS NULL OR effective_to>=%s) ORDER BY effective_from DESC LIMIT 1""",
        (rule_code, on_date or date.today(), on_date or date.today()))
    return need(result, f"Tax rule {rule_code} has no effective version")


def encounter_for(conn: psycopg.Connection, encounter_id: str, lock: bool = False) -> dict:
    return need(one(conn, "SELECT * FROM encounters WHERE encounter_id=%s" + (" FOR UPDATE" if lock else ""),
                    (encounter_id,)), "Encounter not found", 404)


def service_for(conn: psycopg.Connection, service_code: str) -> dict:
    return need(one(conn, "SELECT * FROM services WHERE service_code=%s AND active=true", (service_code,)),
                "Service not found or inactive", 404)


def price_for(conn: psycopg.Connection, service: dict, encounter: dict) -> int:
    rate = one(conn, """SELECT unit_paise FROM payer_rates WHERE service_code=%s AND payer_route=%s
        AND payer_label IN (%s,'') ORDER BY length(payer_label) DESC LIMIT 1""",
        (service["service_code"], encounter["payer_route"], encounter["payer_label"]))
    return rate["unit_paise"] if rate else service["base_unit_paise"]


def tax_amount(subtotal_paise: int, rate_bps: int) -> int:
    return (subtotal_paise * rate_bps + 5000) // 10000


def latest_approved_preauth(conn: psycopg.Connection, encounter_id: str) -> dict | None:
    return one(conn, """SELECT * FROM preauths WHERE encounter_id=%s AND status='APPROVED_DEMO'
        ORDER BY preauth_id DESC LIMIT 1""", (encounter_id,))


def balance_for(conn: psycopg.Connection, invoice: dict) -> dict:
    paid = one(conn, "SELECT COALESCE(sum(amount_paise),0) AS amount FROM receipts WHERE invoice_id=%s",
               (invoice["invoice_id"],))["amount"]
    return {"paid_paise": paid + invoice["advance_allocated_paise"],
            "receipts_paise": paid,
            "remaining_paise": invoice["total_paise"] - invoice["advance_allocated_paise"] - paid}


def create_charge(conn: psycopg.Connection, encounter_id: str, service_code: str, quantity: int,
                  source_event_id: str, room_stay_id: int | None = None) -> dict:
    need(quantity > 0 and quantity <= 1000, "Quantity must be between 1 and 1000")
    need(source_event_id.strip(), "A unique HIS source event ID is required")
    existing = one(conn, "SELECT * FROM charges WHERE source_event_id=%s", (source_event_id,))
    if existing:
        if (existing["encounter_id"], existing["service_code"], existing["quantity"]) != (encounter_id, service_code, quantity):
            raise HTTPException(409, "This HIS event ID belongs to a different payload")
        return {"charge": existing, "duplicate": True}
    encounter = encounter_for(conn, encounter_id, True)
    need(encounter["status"] == "OPEN", "Charges require an open encounter")
    service = service_for(conn, service_code)
    need(service["kind"] != "PHARMACY", "Use pharmacy dispense for a stock item")
    need(service["kind"] != "PACKAGE", "Use package apply for a package")
    unit = price_for(conn, service, encounter)
    rule_code = service["tax_rule_code"]
    if service["kind"] == "ROOM":
        rule_code = "ROOM_5_DEMO" if unit > 500000 else "CARE_EXEMPT"
    included = False
    package = one(conn, """SELECT p.* FROM charges c JOIN package_catalog p ON p.service_code=c.service_code
        WHERE c.encounter_id=%s ORDER BY c.charge_id DESC LIMIT 1""", (encounter_id,))
    if package and service["department"] in package["included_departments"]:
        unit, rule_code, included = 0, "CARE_EXEMPT", True
    rule = tax_for(conn, rule_code)
    charge = one(conn, """INSERT INTO charges(encounter_id,source_event_id,service_code,description,department,
        quantity,unit_price_paise,tax_rule_code,tax_category,tax_rate_bps,hsn_sac,included_in_package,room_stay_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (encounter_id, source_event_id, service_code, service["description"], service["department"],
         quantity, unit, rule_code, rule["tax_category"], rule["rate_bps"], rule["hsn_sac"], included, room_stay_id))
    audit(conn, "HIS_CHARGE_CAPTURED", "charge", charge["charge_id"], {"source_event_id": source_event_id})
    return {"charge": charge, "duplicate": False}


def seed_demo(conn: psycopg.Connection) -> None:
    """Seed invented training records only. Never import a real bill here."""
    rules = [
        ("CARE_EXEMPT", "EXEMPT", 0, "9993", "Healthcare exemption requires qualification review"),
        ("ROOM_5_DEMO", "TAXABLE", 500, "9993", "Demo: specified non-ICU room above Rs 5,000/day, subject to CBIC conditions"),
        ("MED_5_DEMO", "TAXABLE", 500, "3004", "Synthetic medicine tax setting; verify actual HSN and rate"),
        ("MED_NIL_DEMO", "NIL", 0, "3006", "Contraceptive products are listed at nil rate in the CBIC schedule; training SKU only"),
        ("DEVICE_5_DEMO", "TAXABLE", 500, "9018", "Synthetic medical device; verify actual HSN and rate"),
        ("REVIEW_REQUIRED", "REVIEW", 0, "", "Finance must classify this item before invoicing"),
    ]
    conn.cursor().executemany("""INSERT INTO tax_rules(rule_code,effective_from,tax_category,rate_bps,hsn_sac,note)
        VALUES (%s,'2026-01-01',%s,%s,%s,%s)""", rules)
    services = [
        ("CONSULT", "Doctor assessment", "CLINICAL", "CARE", 50000, "CARE_EXEMPT"),
        ("CBC", "Complete blood count", "LAB", "LAB", 35000, "CARE_EXEMPT"),
        ("HBA1C", "HbA1c blood test", "LAB", "LAB", 65000, "CARE_EXEMPT"),
        ("XRAY", "X-ray investigation", "RADIOLOGY", "LAB", 90000, "CARE_EXEMPT"),
        ("PROC", "Procedure example", "PROCEDURE", "PROCEDURE", 850000, "CARE_EXEMPT"),
        ("WARD", "General ward, one day", "ROOM", "ROOM", 230000, "CARE_EXEMPT"),
        ("PRIVATE_ROOM", "Private room, one day", "ROOM", "ROOM", 600000, "ROOM_5_DEMO"),
        ("MED_A", "Paracetamol 500 mg, training SKU", "PHARMACY", "PHARMACY", 10000, "MED_5_DEMO"),
        ("MED_M", "Metformin 500 mg, training SKU", "PHARMACY", "PHARMACY", 600, "MED_5_DEMO"),
        ("MED_N", "Contraceptive product, training SKU", "PHARMACY", "PHARMACY", 18000, "MED_NIL_DEMO"),
        ("DEVICE_B", "Medical device, training SKU", "PHARMACY", "DEVICE", 250000, "DEVICE_5_DEMO"),
        ("PMJAY_PKG", "PM-JAY training package", "PACKAGE", "PACKAGE", 1200000, "CARE_EXEMPT"),
        ("DAY_PKG", "Day-care procedure package", "PACKAGE", "PACKAGE", 600000, "CARE_EXEMPT"),
        ("MAT_PKG", "Maternity package example", "PACKAGE", "PACKAGE", 2200000, "CARE_EXEMPT"),
        ("UNCLASSIFIED", "Unclassified pharmacy placeholder", "PHARMACY", "PHARMACY", 10000, "REVIEW_REQUIRED"),
    ]
    conn.cursor().executemany("""INSERT INTO services(service_code,description,department,kind,base_unit_paise,tax_rule_code)
        VALUES (%s,%s,%s,%s,%s,%s)""", services)
    conn.execute("""INSERT INTO lab_catalog(service_code,loinc_code,cpt_reference,result_unit,specimen)
        VALUES ('HBA1C','4548-4','83036','%','Blood')""")
    rates = [
        ("CONSULT", "PRIVATE", "", 45000), ("CONSULT", "CGHS", "", 40000),
        ("CONSULT", "CORPORATE", "", 45000), ("CONSULT", "PRIVATE", "Alpha TPA", 43000),
        ("CONSULT", "PRIVATE", "Bharat TPA", 44000), ("CONSULT", "PRIVATE", "City TPA", 45000),
        ("WARD", "PRIVATE", "", 230000), ("PROC", "PRIVATE", "", 850000),
        ("PMJAY_PKG", "PMJAY", "", 1200000),
    ]
    conn.cursor().executemany("INSERT INTO payer_rates(service_code,payer_route,payer_label,unit_paise) VALUES (%s,%s,%s,%s)", rates)
    conn.cursor().executemany("""INSERT INTO pharmacy_items(item_code,service_code,display_name,requires_prescription,controlled_stock)
        VALUES (%s,%s,%s,%s,%s)""", [
            ("MED-A", "MED_A", "Paracetamol 500 mg, training SKU", True, False),
            ("MED-M", "MED_M", "Metformin 500 mg, training SKU", True, False),
            ("MED-N", "MED_N", "Contraceptive product, training SKU", True, False),
            ("DEVICE-B", "DEVICE_B", "Medical device, training SKU", False, False),
        ])
    conn.cursor().executemany("""INSERT INTO stock_batches(item_code,batch_no,expiry_date,quantity_available)
        VALUES (%s,%s,%s,%s)""", [
            ("MED-A", "DEMO-MA-01", date.today() + timedelta(days=365), 120),
            ("MED-A", "DEMO-MA-02", date.today() + timedelta(days=540), 80),
            ("MED-M", "DEMO-MM-01", date.today() + timedelta(days=365), 300),
            ("MED-N", "DEMO-MN-01", date.today() + timedelta(days=365), 24),
            ("DEVICE-B", "DEMO-DB-01", date.today() + timedelta(days=730), 35),
        ])
    conn.cursor().executemany("""INSERT INTO package_catalog(package_code,service_code,payer_route,included_departments,preauth_required,note)
        VALUES (%s,%s,%s,%s,%s,%s)""", [
            ("HBP-DEMO-01", "PMJAY_PKG", "PMJAY", ["ROOM", "LAB", "PROCEDURE"], True, "Invented teaching package, not an official HBP rate"),
            ("DAY-DEMO-01", "DAY_PKG", "SELF", ["PROCEDURE", "LAB"], False, "Invented day-care package"),
            ("MAT-DEMO-01", "MAT_PKG", "SELF", ["ROOM", "PROCEDURE", "LAB"], False, "Invented maternity package"),
        ])
    cases = [
        ("P-DEMO-01", "Ananya Rao", "E-OPD-01", "OPD", "SELF", "Self pay"),
        ("P-DEMO-02", "Dev Mehta", "E-IPD-02", "IPD", "PRIVATE", "Alpha TPA"),
        ("P-DEMO-03", "Farah Khan", "E-IPD-03", "IPD", "PMJAY", "PM-JAY demo"),
        ("P-DEMO-04", "Kiran Das", "E-OPD-04", "OPD", "CGHS", "CGHS demo"),
        ("P-DEMO-05", "Leela Nair", "E-OPD-05", "OPD", "CORPORATE", "Demo employer"),
        ("P-DEMO-06", "Manoj Shah", "E-OLD-06", "OPD", "SELF", "Self pay"),
        ("P-DEMO-07", "Nadia Roy", "E-OLD-07", "IPD", "PRIVATE", "Bharat TPA"),
        ("P-DEMO-08", "Rohan Iyer", "E-IPD-08", "IPD", "SELF", "Self pay"),
    ]
    seed_staff(conn)
    profiles = [
        (28, "Female", "B+", "9XXXXX1201", "Bengaluru", "No known drug allergies", "Intermittent fever for three days; prior OPD consultation in 2025."),
        (46, "Male", "O+", "9XXXXX1202", "Mysuru", "Penicillin listed", "Type 2 diabetes; admitted for planned procedure. Previous admission in 2024."),
        (37, "Female", "A+", "9XXXXX1203", "Bengaluru", "No known drug allergies", "Recent abdominal pain; scheme eligibility and package are simulated."),
        (62, "Male", "AB+", "9XXXXX1204", "Hubballi", "Sulfa listed", "Hypertension, on long-term follow-up."),
        (33, "Female", "O-", "9XXXXX1205", "Bengaluru", "No known drug allergies", "Corporate OPD visit for family planning advice; no admission history."),
        (51, "Male", "B-", "9XXXXX1206", "Tumakuru", "No known drug allergies", "Past OPD consultation, now fully settled."),
        (43, "Female", "A-", "9XXXXX1207", "Mysuru", "No known drug allergies", "Prior inpatient procedure with insurer balance pending."),
        (39, "Male", "O+", "9XXXXX1208", "Bengaluru", "No known drug allergies", "Admitted for observation. Room choice remains open for the live billing demonstration."),
    ]
    for (pid, label, eid, setting, route, payer), profile in zip(cases, profiles):
        conn.execute("""INSERT INTO patients(patient_id,display_label,age_years,sex,blood_group,contact_masked,city,allergies,history_summary)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (pid, label, *profile))
        conn.execute("""INSERT INTO encounters(encounter_id,patient_id,setting,payer_route,payer_label,bill_to_gstin)
            VALUES (%s,%s,%s,%s,%s,%s)""", (eid, pid, setting, route, payer,
                                              "29ABCDE1234F1Z5" if route == "CORPORATE" else ""))
        conn.execute("""INSERT INTO coverages(coverage_id,encounter_id,payer_route,payer_label,member_ref,preauth_required)
            VALUES (%s,%s,%s,%s,%s,%s)""", (f"C-{pid}", eid, route, payer,
                                            f"SYN-{pid}", route in {"PRIVATE", "PMJAY"} and setting == "IPD"))
    conn.execute("""INSERT INTO patients(patient_id,display_label,age_years,sex,blood_group,contact_masked,city,allergies,history_summary)
        VALUES ('P-DEMO-09','Asha Kulkarni',52,'Female','O+','9XXXXX1209','Bengaluru',
        'No known drug allergies','Known type 2 diabetes. Referred for a short admission to review repeated high glucose readings and the treatment plan. No documented complications. Prior HbA1c result is not imported into this demo.')""")
    for eid, note_text in [
        ("E-OPD-01", "Fever and fatigue for three days. CBC requested. Review hydration and temperature."),
        ("E-IPD-02", "Admitted for planned procedure. Review medication allergy before any dispensing."),
        ("E-IPD-03", "Abdominal pain assessment completed. Package pathway used for classroom simulation."),
        ("E-IPD-08", "Observation admission. Stable on assessment; room category to be confirmed."),
    ]:
        conn.execute("""INSERT INTO clinical_notes(encounter_id,author_username,note_text,provisional_icd_code,procedure_code)
            VALUES (%s,'doctor',%s,%s,%s)""", (eid, note_text, "R50.9" if eid == "E-OPD-01" else "Z00.0",
            "CBC" if eid == "E-OPD-01" else ""))
    conn.execute("""INSERT INTO prescriptions(prescription_ref,encounter_id,item_code,quantity,instruction,author_username)
        VALUES ('RX-DEMO-01','E-OPD-01','MED-A',4,'After food, as directed','doctor'),
               ('RX-DEMO-02','E-OPD-05','MED-N',1,'Use as advised at the OPD visit','doctor')""")
    for eid, code, qty, source in [
        ("E-OPD-01", "CONSULT", 1, "SEED-OPD-CONSULT"),
        ("E-OPD-01", "CBC", 1, "SEED-OPD-CBC"),
        ("E-IPD-02", "WARD", 2, "SEED-IPD-WARD"),
        ("E-IPD-02", "PROC", 1, "SEED-IPD-PROC"),
        ("E-OPD-04", "CONSULT", 1, "SEED-CGHS-CONSULT"),
        ("E-OPD-05", "CONSULT", 1, "SEED-CORP-CONSULT"),
        ("E-OLD-06", "CONSULT", 1, "SEED-OLD-CONSULT"),
        ("E-OLD-07", "WARD", 2, "SEED-OLD-WARD"),
        ("E-OLD-07", "PROC", 1, "SEED-OLD-PROC"),
    ]:
        create_charge(conn, eid, code, qty, source)
    apply_package_core(conn, "E-IPD-03", "HBP-DEMO-01")
    # Two completed cases make reports useful before the live walkthrough.
    old = finalize_invoice_core(conn, "E-OLD-06", bypass_preauth=True)
    conn.execute("""INSERT INTO receipts(invoice_id,payer_kind,amount_paise,method,reference_no)
        VALUES (%s,'PATIENT',%s,'UPI','SYN-PAID-06')""", (old["invoice_id"], old["total_paise"]))
    conn.execute("""UPDATE invoices SET issued_at=now()-interval '12 days' WHERE invoice_id=%s""", (old["invoice_id"],))
    conn.execute("""INSERT INTO preauths(encounter_id,coverage_id,requested_paise,approved_paise,status,reference_no,decided_at)
        VALUES ('E-OLD-07','C-P-DEMO-07',1400000,1400000,'APPROVED_DEMO','SYN-PRE-07',now()-interval '45 days')""")
    due = finalize_invoice_core(conn, "E-OLD-07")
    conn.execute("""UPDATE invoices SET issued_at=now()-interval '45 days' WHERE invoice_id=%s""", (due["invoice_id"],))
    conn.execute("""INSERT INTO claims(invoice_id,coverage_id,preauth_id,status,submitted_paise,approved_paise,
        diagnosis_code,discharge_summary,documents,reference_no,decided_at)
        SELECT %s,'C-P-DEMO-07',preauth_id,'APPROVED_DEMO',%s,1000000,'Z00','Synthetic discharge summary',
        %s,'SYN-CLAIM-07',now()-interval '42 days' FROM preauths WHERE encounter_id='E-OLD-07' LIMIT 1""",
        (due["invoice_id"], due["total_paise"], Jsonb({"itemised_bill": True, "discharge_summary": True})))
    audit(conn, "DEMO_SEEDED", "system", "synthetic", {"cases": len(cases) + 1})


def reset_demo(conn: psycopg.Connection) -> None:
    conn.execute("TRUNCATE TABLE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
    seed_demo(conn)


def initialise() -> None:
    with db() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        if one(conn, "SELECT count(*) AS n FROM patients")["n"] == 0:
            seed_demo(conn)
        seed_staff(conn)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialise()
    yield


app = FastAPI(title="Tiveri Billing Demo API", version="2.0", lifespan=lifespan)


@app.middleware("http")
async def demo_auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in {"/api/health", "/api/auth/login"}:
        return await call_next(request)
    authorization = request.headers.get("authorization", "")
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    if not token:
        return JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    with db() as conn:
        user = one(conn, """SELECT u.username,u.display_name,u.role FROM auth_sessions s
            JOIN staff_users u USING(username) WHERE s.token_hash=%s AND s.expires_at>now()""",
            (hashlib.sha256(token.encode()).hexdigest(),))
    if not user:
        return JSONResponse({"detail": "Session expired. Sign in again"}, status_code=401)
    request.state.user = user
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/api/auth/logout":
        required = "ADMIN"
        if path.startswith("/api/clinical/") or path == "/api/his/events":
            required = "DOCTOR"
        elif path.startswith("/api/lab/"):
            required = "LAB"
        elif path == "/api/pharmacy/dispense":
            required = "PHARMACY"
        if user["role"] != required:
            return JSONResponse({"detail": f"{required.title()} role required for this action"}, status_code=403)
    return await call_next(request)


class LoginIn(BaseModel):
    username: str
    password: str


class ClinicalNoteIn(BaseModel):
    encounter_id: str
    note_text: str = Field(min_length=10, max_length=2000)
    provisional_icd_code: str = Field(default="", max_length=12)
    procedure_code: str = Field(default="", max_length=24)


class PrescriptionIn(BaseModel):
    encounter_id: str
    item_code: str
    quantity: int = Field(ge=1, le=100)
    instruction: str = Field(default="", max_length=300)


class DemoEncounterIn(BaseModel):
    patient_id: str
    case_code: str = "DIABETES_FOLLOWUP"
    note_text: str = Field(min_length=15, max_length=2000)
    medicine_item_code: str = "MED-M"
    medicine_quantity: int = Field(default=10, ge=1, le=100)
    instruction: str = Field(default="Existing medicine reviewed; take only as prescribed by the treating doctor.", max_length=300)


class LabResultIn(BaseModel):
    result_value: float = Field(gt=0, lt=30)


@app.post("/api/auth/login")
def login(data: LoginIn):
    with db() as conn:
        user = one(conn, "SELECT * FROM staff_users WHERE username=%s", (data.username.lower().strip(),))
        if not user or not hmac.compare_digest(password_digest(data.password, user["password_salt"]), user["password_hash"]):
            raise HTTPException(401, "Incorrect demo sign-in")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO auth_sessions(token_hash,username,expires_at) VALUES (%s,%s,%s)",
                     (hashlib.sha256(token.encode()).hexdigest(), user["username"], datetime.now(timezone.utc) + timedelta(hours=12)))
        return {"token": token, "user": {key: user[key] for key in ("username", "display_name", "role")}}


@app.get("/api/auth/me")
def me(request: Request):
    return request.state.user


@app.post("/api/auth/logout")
def logout(request: Request):
    token = request.headers.get("authorization", "")[7:]
    with db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (hashlib.sha256(token.encode()).hexdigest(),))
    return {"ok": True}


@app.post("/api/clinical/notes")
def add_clinical_note(data: ClinicalNoteIn, request: Request):
    with db() as conn:
        enc = encounter_for(conn, data.encounter_id)
        need(enc["status"] == "OPEN", "Encounter is closed")
        if data.provisional_icd_code:
            need(re.fullmatch(r"[A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?", data.provisional_icd_code.upper()), "Enter an ICD-style diagnosis code")
        record = one(conn, """INSERT INTO clinical_notes(encounter_id,author_username,note_text,provisional_icd_code,procedure_code)
            VALUES (%s,%s,%s,%s,%s) RETURNING *""", (data.encounter_id, request.state.user["username"],
            data.note_text.strip(), data.provisional_icd_code.upper().strip(), data.procedure_code.strip()))
        audit(conn, "CLINICAL_NOTE_ADDED", "note", record["note_id"])
        return record


@app.post("/api/clinical/prescriptions")
def add_prescription(data: PrescriptionIn, request: Request):
    with db() as conn:
        enc = encounter_for(conn, data.encounter_id)
        need(enc["status"] == "OPEN", "Encounter is closed")
        need(one(conn, "SELECT 1 FROM pharmacy_items WHERE item_code=%s", (data.item_code,)), "Medicine not found", 404)
        ref = "RX-" + uuid4().hex[:10].upper()
        record = one(conn, """INSERT INTO prescriptions(prescription_ref,encounter_id,item_code,quantity,instruction,author_username)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""", (ref, data.encounter_id, data.item_code,
            data.quantity, data.instruction.strip(), request.state.user["username"]))
        audit(conn, "PRESCRIPTION_ADDED", "prescription", ref)
        return record


@app.post("/api/clinical/demo-encounters")
def create_demo_clinical_encounter(data: DemoEncounterIn, request: Request):
    """A clinician confirms a preconfigured pathway; no free-text code inference is performed."""
    need(data.case_code == "DIABETES_OBSERVATION", "Unknown demo pathway")
    need(data.medicine_item_code == "MED-M", "This pathway uses the metformin training SKU")
    with db() as conn:
        patient = need(one(conn, "SELECT * FROM patients WHERE patient_id=%s FOR UPDATE", (data.patient_id,)),
                       "Patient not found", 404)
        need("type 2 diabetes" in patient["history_summary"].lower(),
             "This teaching pathway requires the diabetes observation patient")
        need(not one(conn, "SELECT 1 FROM encounters WHERE patient_id=%s AND status='OPEN'", (data.patient_id,)),
             "This patient already has an open encounter", 409)
        eid = f"E-{uuid4().hex[:9].upper()}"
        conn.execute("""INSERT INTO encounters(encounter_id,patient_id,setting,payer_route,payer_label)
            VALUES (%s,%s,'IPD','SELF','Self pay')""", (eid, data.patient_id))
        conn.execute("""INSERT INTO coverages(coverage_id,encounter_id,payer_route,payer_label,member_ref)
            VALUES (%s,%s,'SELF','Self pay',%s)""", (f"C-{eid}", eid, f"SYN-{eid}"))
        note = one(conn, """INSERT INTO clinical_notes(encounter_id,author_username,note_text,
            provisional_icd_code,procedure_code) VALUES (%s,%s,%s,'E11.9','83036') RETURNING *""",
            (eid, request.state.user["username"], data.note_text.strip()))
        consultation = create_charge(conn, eid, "CONSULT", 1, f"CONSULT-{eid}")["charge"]
        lab_order = one(conn, """INSERT INTO lab_orders(encounter_id,service_code,ordered_by)
            VALUES (%s,'HBA1C',%s) RETURNING *""", (eid, request.state.user["username"]))
        ref = "RX-" + uuid4().hex[:10].upper()
        prescription = one(conn, """INSERT INTO prescriptions(prescription_ref,encounter_id,item_code,
            quantity,instruction,author_username) VALUES (%s,%s,'MED-M',%s,%s,%s) RETURNING *""",
            (ref, eid, data.medicine_quantity, data.instruction.strip(), request.state.user["username"]))
        audit(conn, "CLINICIAN_PATHWAY_CONFIRMED", "encounter", eid,
              {"case_code": data.case_code, "icd10": "E11.9", "cpt_reference": "83036",
               "loinc": "4548-4", "lab_order_id": lab_order["lab_order_id"]})
        return {"encounter_id": eid, "note": note, "consultation_charge": consultation,
                "lab_order": lab_order, "prescription": prescription}


@app.get("/api/lab/queue")
def lab_queue():
    with db() as conn:
        return {"orders": rows(conn, """SELECT o.*,p.display_label AS patient_label,
            c.loinc_code,c.cpt_reference,c.result_unit,c.specimen,s.description,
            s.base_unit_paise FROM lab_orders o JOIN encounters e USING(encounter_id)
            JOIN patients p USING(patient_id) JOIN lab_catalog c USING(service_code)
            JOIN services s USING(service_code) ORDER BY o.ordered_at DESC,o.lab_order_id DESC""")}


@app.post("/api/lab/orders/{lab_order_id}/complete")
def complete_lab_order(lab_order_id: int, data: LabResultIn, request: Request):
    with db() as conn:
        order = need(one(conn, "SELECT * FROM lab_orders WHERE lab_order_id=%s FOR UPDATE", (lab_order_id,)),
                     "Lab order not found", 404)
        if order["status"] == "COMPLETED":
            need(float(order["result_value"]) == data.result_value,
                 "The completed result cannot be changed by repeating this request", 409)
            return {"order": order, "charge": one(conn, "SELECT * FROM charges WHERE charge_id=%s",
                                                     (order["charge_id"],)), "duplicate": True}
        charge = create_charge(conn, order["encounter_id"], order["service_code"], 1,
                               f"LAB-ORDER-{lab_order_id}")["charge"]
        updated = one(conn, """UPDATE lab_orders SET status='COMPLETED',result_value=%s,
            performed_by=%s,charge_id=%s,completed_at=now() WHERE lab_order_id=%s RETURNING *""",
            (data.result_value, request.state.user["username"], charge["charge_id"], lab_order_id))
        audit(conn, "LAB_RESULT_COMPLETED", "lab_order", lab_order_id,
              {"loinc": "4548-4", "charge_id": charge["charge_id"]})
        return {"order": updated, "charge": charge, "duplicate": False}


class EncounterIn(BaseModel):
    display_label: str = Field(min_length=2, max_length=80)
    setting: str
    payer_route: str
    payer_label: str = ""
    bill_to_gstin: str = ""
    state_code: str = "29"


class HisEventIn(BaseModel):
    encounter_id: str
    service_code: str
    quantity: int = Field(ge=1, le=1000)
    source_event_id: str = Field(min_length=3, max_length=100)


class RoomStayIn(BaseModel):
    room_code: str
    start_date: date
    end_date: date


class DispenseIn(BaseModel):
    encounter_id: str
    item_code: str
    quantity: int = Field(ge=1, le=100)
    source_event_id: str = Field(min_length=3, max_length=100)
    prescription_ref: str = ""


class PackageIn(BaseModel):
    encounter_id: str
    package_code: str


class AdvanceIn(BaseModel):
    encounter_id: str
    amount_paise: int = Field(gt=0)
    method: str = "UPI"
    reference_no: str = ""


class PreauthIn(BaseModel):
    encounter_id: str
    requested_paise: int = Field(gt=0)
    request_type: str = "INITIAL"


class DecisionIn(BaseModel):
    approved_paise: int = Field(ge=0)
    reference_no: str = "SYN-DECISION"


class InvoiceIn(BaseModel):
    encounter_id: str


class ClaimIn(BaseModel):
    invoice_id: int
    discharge_summary: str = "Synthetic discharge summary for classroom demonstration"
    documents: dict[str, bool] = Field(default_factory=lambda: {"itemised_bill": True, "discharge_summary": True})


class ReceiptIn(BaseModel):
    invoice_id: int
    payer_kind: str
    amount_paise: int = Field(gt=0)
    method: str = "UPI"
    reference_no: str = ""


class RefundIn(BaseModel):
    encounter_id: str
    amount_paise: int = Field(gt=0)
    method: str = "UPI"
    reference_no: str = ""


class VerifyIn(BaseModel):
    member_ref: str = "SYN-BENEFICIARY"


class RateIn(BaseModel):
    service_code: str
    payer_route: str
    payer_label: str = ""
    unit_paise: int = Field(ge=0)


@app.get("/api/health")
def health():
    with db() as conn:
        one(conn, "SELECT 1 AS ok")
    return {"ok": True, "mode": "synthetic_demo", "database": "postgresql"}


@app.get("/api/bootstrap")
def bootstrap():
    with db() as conn:
        result = {table: rows(conn, f"SELECT * FROM {table} ORDER BY 1") for table in PUBLIC_TABLES}
    result["demo_notice"] = "Synthetic teaching cases only. External HIS, payer and GST portal actions are simulated."
    return result


@app.get("/api/dashboard")
def dashboard():
    with db() as conn:
        worklist = rows(conn, """SELECT e.encounter_id,p.display_label AS patient_label,e.setting,e.payer_route,
            e.payer_label,e.status,COALESCE(i.total_paise,(SELECT COALESCE(sum(c.subtotal_paise +
            ((c.subtotal_paise*c.tax_rate_bps+5000)/10000)),0) FROM charges c WHERE c.encounter_id=e.encounter_id))
            AS running_total_paise,COALESCE(i.total_paise-i.advance_allocated_paise-
            (SELECT COALESCE(sum(r.amount_paise),0) FROM receipts r WHERE r.invoice_id=i.invoice_id),0)
            AS remaining_paise FROM encounters e JOIN patients p USING(patient_id)
            LEFT JOIN invoices i USING(encounter_id) ORDER BY e.opened_at DESC,e.encounter_id""")
        stats = one(conn, """SELECT (SELECT count(*) FROM encounters WHERE status='OPEN') AS open_encounters,
            (SELECT count(*) FROM invoices) AS final_invoices,
            (SELECT COALESCE(sum(total_paise-advance_allocated_paise-
              (SELECT COALESCE(sum(amount_paise),0) FROM receipts WHERE invoice_id=i.invoice_id)),0)
              FROM invoices i) AS unpaid_paise,
            (SELECT COALESCE(sum(amount_paise),0) FROM receipts) +
            (SELECT COALESCE(sum(amount_paise),0) FROM advances) -
            (SELECT COALESCE(sum(amount_paise),0) FROM refunds) AS collections_paise""")
    return {**stats, "worklist": worklist}


@app.get("/api/patients")
def patient_list():
    with db() as conn:
        return {"patients": rows(conn, """SELECT p.*,e.encounter_id AS latest_encounter_id,
            e.status AS latest_status,e.setting AS latest_setting FROM patients p
            LEFT JOIN LATERAL (SELECT encounter_id,status,setting FROM encounters
              WHERE patient_id=p.patient_id ORDER BY opened_at DESC,encounter_id DESC LIMIT 1) e ON true
            ORDER BY p.patient_id""")}


@app.get("/api/patients/{patient_id}")
def patient_detail(patient_id: str):
    with db() as conn:
        patient = need(one(conn, "SELECT * FROM patients WHERE patient_id=%s", (patient_id,)),
                       "Patient not found", 404)
        return {"patient": patient,
                "encounters": rows(conn, """SELECT encounter_id,setting,payer_route,status,opened_at
                    FROM encounters WHERE patient_id=%s ORDER BY opened_at DESC,encounter_id DESC""",
                    (patient_id,))}


@app.get("/api/encounters/{encounter_id}")
def encounter_detail(encounter_id: str):
    with db() as conn:
        enc = encounter_for(conn, encounter_id)
        inv = one(conn, "SELECT * FROM invoices WHERE encounter_id=%s", (encounter_id,))
        charges = rows(conn, "SELECT * FROM charges WHERE encounter_id=%s ORDER BY charge_id", (encounter_id,))
        preview = sum(c["subtotal_paise"] + tax_amount(c["subtotal_paise"], c["tax_rate_bps"]) for c in charges)
        if inv:
            balance = balance_for(conn, inv)
        else:
            advance = one(conn, "SELECT COALESCE(sum(amount_paise),0) AS n FROM advances WHERE encounter_id=%s", (encounter_id,))["n"]
            balance = {"paid_paise": advance, "receipts_paise": 0, "remaining_paise": max(0, preview - advance)}
        return {"encounter": enc,
                "patient": one(conn, "SELECT * FROM patients WHERE patient_id=%s", (enc["patient_id"],)),
                "coverage": one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (encounter_id,)),
                "charges": charges,
                "room_stays": rows(conn, "SELECT * FROM room_stays WHERE encounter_id=%s ORDER BY room_stay_id", (encounter_id,)),
                "dispenses": rows(conn, "SELECT * FROM dispenses WHERE encounter_id=%s ORDER BY dispense_id", (encounter_id,)),
                "clinical_notes": rows(conn, "SELECT * FROM clinical_notes WHERE encounter_id=%s ORDER BY created_at DESC,note_id DESC", (encounter_id,)),
                "lab_orders": rows(conn, """SELECT o.*,c.loinc_code,c.cpt_reference,c.result_unit,
                    c.specimen,s.description FROM lab_orders o JOIN lab_catalog c USING(service_code)
                    JOIN services s USING(service_code) WHERE encounter_id=%s ORDER BY lab_order_id""", (encounter_id,)),
                "prescriptions": rows(conn, """SELECT p.*,COALESCE((SELECT sum(d.quantity) FROM dispenses d
                    WHERE d.prescription_ref=p.prescription_ref),0) AS dispensed_quantity FROM prescriptions p
                    WHERE encounter_id=%s ORDER BY created_at DESC""", (encounter_id,)),
                "preauths": rows(conn, "SELECT * FROM preauths WHERE encounter_id=%s ORDER BY preauth_id", (encounter_id,)),
                "invoice": inv,
                "invoice_lines": rows(conn, "SELECT * FROM invoice_lines WHERE invoice_id=%s ORDER BY invoice_line_id", (inv["invoice_id"],)) if inv else [],
                "claim": one(conn, "SELECT * FROM claims WHERE invoice_id=%s", (inv["invoice_id"],)) if inv else None,
                "advances": rows(conn, "SELECT * FROM advances WHERE encounter_id=%s ORDER BY advance_id", (encounter_id,)),
                "receipts": rows(conn, "SELECT * FROM receipts WHERE invoice_id=%s ORDER BY receipt_id", (inv["invoice_id"],)) if inv else [],
                "refunds": rows(conn, "SELECT * FROM refunds WHERE encounter_id=%s ORDER BY refund_id", (encounter_id,)),
                "running_total_paise": preview, **balance}


@app.get("/api/clinical/queue")
def clinical_queue():
    with db() as conn:
        return {"prescriptions": rows(conn, """SELECT p.*,pt.display_label AS patient_label,e.setting,
            COALESCE((SELECT sum(d.quantity) FROM dispenses d WHERE d.prescription_ref=p.prescription_ref),0)
            AS dispensed_quantity FROM prescriptions p JOIN encounters e USING(encounter_id)
            JOIN patients pt USING(patient_id) ORDER BY p.created_at DESC""")}


def apply_package_core(conn: psycopg.Connection, encounter_id: str, package_code: str) -> dict:
    enc = encounter_for(conn, encounter_id, True)
    need(enc["status"] == "OPEN", "Only an open encounter can receive a package")
    package = need(one(conn, "SELECT * FROM package_catalog WHERE package_code=%s", (package_code,)), "Package not found", 404)
    need(package["payer_route"] == enc["payer_route"], "Package does not match this payer route")
    need(not one(conn, "SELECT 1 FROM charges WHERE encounter_id=%s AND service_code=%s", (encounter_id, package["service_code"])), "Package already applied", 409)
    svc = service_for(conn, package["service_code"])
    rule = tax_for(conn, svc["tax_rule_code"])
    unit = price_for(conn, svc, enc)
    charge = one(conn, """INSERT INTO charges(encounter_id,source_event_id,service_code,description,department,
        quantity,unit_price_paise,tax_rule_code,tax_category,tax_rate_bps,hsn_sac)
        VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s) RETURNING *""",
        (encounter_id, f"PKG-{encounter_id}-{package_code}", svc["service_code"], svc["description"],
         svc["department"], unit, svc["tax_rule_code"], rule["tax_category"], rule["rate_bps"], rule["hsn_sac"]))
    # Existing included services are retained in the audit trail at zero price.
    conn.execute("""UPDATE charges SET unit_price_paise=0,tax_rule_code='CARE_EXEMPT',tax_category='EXEMPT',
        tax_rate_bps=0,included_in_package=true WHERE encounter_id=%s AND charge_id<>%s
        AND department=ANY(%s)""", (encounter_id, charge["charge_id"], package["included_departments"]))
    audit(conn, "PACKAGE_APPLIED", "charge", charge["charge_id"], {"package_code": package_code})
    return {"package": package, "charge": charge}


def finalize_invoice_core(conn: psycopg.Connection, encounter_id: str, bypass_preauth: bool = False) -> dict:
    enc = encounter_for(conn, encounter_id, True)
    need(enc["status"] == "OPEN", "Encounter has already been billed", 409)
    charges = rows(conn, "SELECT * FROM charges WHERE encounter_id=%s ORDER BY charge_id", (encounter_id,))
    need(charges, "Capture at least one service before invoicing")
    need(all(c["tax_category"] != "REVIEW" for c in charges), "A charge needs tax classification review")
    cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (encounter_id,))
    if cov and cov["preauth_required"] and not bypass_preauth:
        need(latest_approved_preauth(conn, encounter_id), "Simulated pre-authorisation approval required")
    if enc["payer_route"] == "PMJAY":
        need(cov and cov["eligibility_status"] == "VERIFIED_DEMO", "Complete simulated beneficiary check")
        need(any(c["service_code"] == "PMJAY_PKG" for c in charges), "PM-JAY demo requires package selection")
    subtotal = sum(c["subtotal_paise"] for c in charges)
    tax = sum(tax_amount(c["subtotal_paise"], c["tax_rate_bps"]) for c in charges)
    total = subtotal + tax
    advances = one(conn, "SELECT COALESCE(sum(amount_paise),0) AS n FROM advances WHERE encounter_id=%s", (encounter_id,))["n"]
    allocated = min(total, advances)
    inv_id = one(conn, "SELECT nextval(pg_get_serial_sequence('invoices','invoice_id')) AS n")["n"]
    invoice = one(conn, """INSERT INTO invoices(invoice_id,encounter_id,invoice_no,subtotal_paise,tax_paise,
        total_paise,advance_allocated_paise) OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (inv_id, encounter_id, f"TVR-{date.today().year}-{inv_id:05d}", subtotal, tax, total, allocated))
    for c in charges:
        line_tax = tax_amount(c["subtotal_paise"], c["tax_rate_bps"])
        conn.execute("""INSERT INTO invoice_lines(invoice_id,charge_id,description,department,quantity,
            unit_price_paise,taxable_paise,tax_category,tax_rate_bps,tax_paise,total_paise,hsn_sac)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (inv_id, c["charge_id"], c["description"], c["department"], c["quantity"],
             c["unit_price_paise"], c["subtotal_paise"], c["tax_category"], c["tax_rate_bps"],
             line_tax, c["subtotal_paise"] + line_tax, c["hsn_sac"]))
    conn.execute("UPDATE encounters SET status='BILLED',discharged_at=now() WHERE encounter_id=%s", (encounter_id,))
    audit(conn, "INVOICE_FINALISED", "invoice", inv_id, {"encounter_id": encounter_id, "total_paise": total})
    return invoice


@app.post("/api/encounters")
def create_encounter(data: EncounterIn):
    need(data.setting in SETTINGS, "Invalid care setting")
    need(data.payer_route in ROUTES, "Invalid payer route")
    pid, eid = f"P-{uuid4().hex[:9].upper()}", f"E-{uuid4().hex[:9].upper()}"
    with db() as conn:
        conn.execute("INSERT INTO patients(patient_id,display_label) VALUES (%s,%s)", (pid, data.display_label.strip()))
        enc = one(conn, """INSERT INTO encounters(encounter_id,patient_id,setting,payer_route,payer_label,
            bill_to_gstin,state_code) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (eid, pid, data.setting, data.payer_route, data.payer_label.strip(),
             data.bill_to_gstin.strip(), data.state_code))
        conn.execute("""INSERT INTO coverages(coverage_id,encounter_id,payer_route,payer_label,member_ref,
            preauth_required) VALUES (%s,%s,%s,%s,%s,%s)""",
            (f"C-{eid}", eid, data.payer_route, data.payer_label.strip(), f"SYN-{eid}",
             data.payer_route in {"PRIVATE", "PMJAY"} and data.setting == "IPD"))
        audit(conn, "ENCOUNTER_CREATED", "encounter", eid)
        return enc


@app.post("/api/his/events")
def his_event(data: HisEventIn):
    with db() as conn:
        return create_charge(conn, data.encounter_id, data.service_code, data.quantity, data.source_event_id)


@app.post("/api/encounters/{encounter_id}/room-stays")
def room_stay(encounter_id: str, data: RoomStayIn):
    days = (data.end_date - data.start_date).days
    need(0 < days <= 365, "Room stay must be 1 to 365 days")
    with db() as conn:
        enc = encounter_for(conn, encounter_id, True)
        need(enc["setting"] == "IPD", "Room charges require IPD setting")
        svc = service_for(conn, data.room_code)
        need(svc["kind"] == "ROOM", "Select a room service")
        need(not one(conn, """SELECT 1 FROM room_stays WHERE encounter_id=%s
            AND start_date<%s AND end_date>%s""", (encounter_id, data.end_date, data.start_date)),
            "Room dates overlap an existing stay", 409)
        stay = one(conn, """INSERT INTO room_stays(encounter_id,room_code,start_date,end_date)
            VALUES (%s,%s,%s,%s) RETURNING *""", (encounter_id, data.room_code, data.start_date, data.end_date))
        result = create_charge(conn, encounter_id, data.room_code, days, f"ROOM-{stay['room_stay_id']}", stay["room_stay_id"])
        return {"room_stay": stay, "charges": [result["charge"]]}


@app.post("/api/packages/apply")
def apply_package(data: PackageIn):
    with db() as conn:
        return apply_package_core(conn, data.encounter_id, data.package_code)


@app.get("/api/pharmacy/stock")
def pharmacy_stock():
    with db() as conn:
        items = rows(conn, """SELECT p.item_code,p.display_name AS description,p.requires_prescription,
            p.controlled_stock,s.base_unit_paise AS unit_price_paise,s.tax_rule_code,
            t.hsn_sac AS hsn_code,t.tax_category,t.rate_bps AS tax_rate_bps FROM pharmacy_items p JOIN services s USING(service_code)
            JOIN tax_rules t ON t.rule_code=s.tax_rule_code ORDER BY p.item_code""")
        for item in items:
            item["batches"] = rows(conn, "SELECT * FROM stock_batches WHERE item_code=%s ORDER BY expiry_date", (item["item_code"],))
            item["available_units"] = sum(b["quantity_available"] for b in item["batches"] if b["expiry_date"] > date.today())
        return {"items": items}


@app.post("/api/pharmacy/dispense")
def dispense(data: DispenseIn):
    with db() as conn:
        existing = one(conn, "SELECT d.*,c.source_event_id FROM dispenses d JOIN charges c USING(charge_id) WHERE c.source_event_id=%s", (data.source_event_id,))
        if existing:
            need((existing["encounter_id"], existing["item_code"], existing["quantity"]) ==
                 (data.encounter_id, data.item_code, data.quantity), "Dispense event ID has conflicting payload", 409)
            return {"dispense": existing, "charge": one(conn, "SELECT * FROM charges WHERE charge_id=%s", (existing["charge_id"],)), "duplicate": True}
        enc = encounter_for(conn, data.encounter_id, True)
        need(enc["status"] == "OPEN", "Dispensing requires an open encounter")
        item = need(one(conn, "SELECT * FROM pharmacy_items WHERE item_code=%s", (data.item_code,)), "Item not found", 404)
        need(not item["controlled_stock"], "Controlled medicine needs a separate register and is unavailable in this demo")
        need(not item["requires_prescription"] or data.prescription_ref.strip(), "Prescription reference required")
        if item["requires_prescription"]:
            rx = need(one(conn, "SELECT * FROM prescriptions WHERE prescription_ref=%s FOR UPDATE",
                          (data.prescription_ref.strip(),)), "Doctor prescription not found", 404)
            need((rx["encounter_id"], rx["item_code"]) == (data.encounter_id, data.item_code),
                 "Prescription does not match this patient and item")
            dispensed = one(conn, "SELECT COALESCE(sum(quantity),0) AS n FROM dispenses WHERE prescription_ref=%s",
                            (data.prescription_ref.strip(),))["n"]
            need(dispensed + data.quantity <= rx["quantity"], "Quantity exceeds doctor prescription")
        batch = need(one(conn, """SELECT * FROM stock_batches WHERE item_code=%s AND expiry_date>%s
            AND quantity_available>=%s ORDER BY expiry_date,batch_id LIMIT 1 FOR UPDATE""",
            (data.item_code, date.today(), data.quantity)), "No unexpired batch has sufficient stock")
        svc = service_for(conn, item["service_code"])
        rule = tax_for(conn, "CARE_EXEMPT" if enc["setting"] == "IPD" else svc["tax_rule_code"])
        need(rule["tax_category"] != "REVIEW", "Item tax classification requires review")
        unit = price_for(conn, svc, enc)
        charge = one(conn, """INSERT INTO charges(encounter_id,source_event_id,service_code,description,department,
            quantity,unit_price_paise,tax_rule_code,tax_category,tax_rate_bps,hsn_sac)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data.encounter_id, data.source_event_id, svc["service_code"], svc["description"], svc["department"],
             data.quantity, unit, rule["rule_code"], rule["tax_category"], rule["rate_bps"], rule["hsn_sac"]))
        conn.execute("UPDATE stock_batches SET quantity_available=quantity_available-%s WHERE batch_id=%s", (data.quantity, batch["batch_id"]))
        disp = one(conn, """INSERT INTO dispenses(encounter_id,item_code,batch_id,charge_id,quantity,prescription_ref)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""", (data.encounter_id, data.item_code,
              batch["batch_id"], charge["charge_id"], data.quantity, data.prescription_ref.strip()))
        audit(conn, "PHARMACY_DISPENSED", "dispense", disp["dispense_id"], {"batch_no": batch["batch_no"]})
        return {"dispense": disp, "charge": charge, "duplicate": False}


@app.post("/api/advances")
def add_advance(data: AdvanceIn):
    with db() as conn:
        enc = encounter_for(conn, data.encounter_id, True)
        need(enc["status"] == "OPEN", "Advances are recorded before invoicing")
        need(enc["payer_route"] != "PMJAY", "PM-JAY demo blocks patient collection")
        record = one(conn, """INSERT INTO advances(encounter_id,amount_paise,method,reference_no)
            VALUES (%s,%s,%s,%s) RETURNING *""", (data.encounter_id, data.amount_paise, data.method, data.reference_no))
        audit(conn, "ADVANCE_RECEIVED", "advance", record["advance_id"])
        return record


@app.post("/api/coverage/{encounter_id}/verify")
def verify_coverage(encounter_id: str, data: VerifyIn):
    with db() as conn:
        enc = encounter_for(conn, encounter_id, True)
        need(enc["payer_route"] == "PMJAY", "Verification demo applies to PM-JAY route")
        cov = one(conn, """UPDATE coverages SET eligibility_status='VERIFIED_DEMO',member_ref=%s
            WHERE encounter_id=%s RETURNING *""", (data.member_ref.strip(), encounter_id))
        audit(conn, "BENEFICIARY_CHECK_SIMULATED", "coverage", cov["coverage_id"])
        return cov


@app.post("/api/preauth")
def submit_preauth(data: PreauthIn):
    need(data.request_type in {"INITIAL", "ENHANCEMENT"}, "Invalid request type")
    with db() as conn:
        enc = encounter_for(conn, data.encounter_id, True)
        need(enc["status"] == "OPEN", "Pre-authorisation requires open encounter")
        need(enc["payer_route"] in {"PRIVATE", "PMJAY"}, "Pre-authorisation applies to TPA or PM-JAY")
        cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (data.encounter_id,))
        record = one(conn, """INSERT INTO preauths(encounter_id,coverage_id,request_type,requested_paise)
            VALUES (%s,%s,%s,%s) RETURNING *""", (data.encounter_id, cov["coverage_id"],
             data.request_type, data.requested_paise))
        audit(conn, "PREAUTH_SUBMITTED_DEMO", "preauth", record["preauth_id"])
        return record


@app.post("/api/preauth/{preauth_id}/decision")
def decide_preauth(preauth_id: int, data: DecisionIn):
    with db() as conn:
        record = need(one(conn, "SELECT * FROM preauths WHERE preauth_id=%s FOR UPDATE", (preauth_id,)), "Pre-authorisation not found", 404)
        need(record["status"] == "SUBMITTED_DEMO", "Decision already recorded", 409)
        need(data.approved_paise <= record["requested_paise"], "Approval exceeds request")
        status = "APPROVED_DEMO" if data.approved_paise > 0 else "REJECTED_DEMO"
        updated = one(conn, """UPDATE preauths SET approved_paise=%s,status=%s,reference_no=%s,decided_at=now()
            WHERE preauth_id=%s RETURNING *""", (data.approved_paise, status, data.reference_no, preauth_id))
        audit(conn, "PREAUTH_DECIDED_DEMO", "preauth", preauth_id, {"status": status})
        return updated


@app.post("/api/invoices")
def create_invoice(data: InvoiceIn):
    with db() as conn:
        return finalize_invoice_core(conn, data.encounter_id)


@app.post("/api/claims")
def submit_claim(data: ClaimIn):
    with db() as conn:
        invoice = need(one(conn, "SELECT * FROM invoices WHERE invoice_id=%s FOR UPDATE", (data.invoice_id,)), "Invoice not found", 404)
        enc = encounter_for(conn, invoice["encounter_id"])
        need(enc["payer_route"] in {"PRIVATE", "PMJAY", "CGHS", "CORPORATE"}, "Self-pay invoice does not need a claim")
        need(not one(conn, "SELECT 1 FROM claims WHERE invoice_id=%s", (data.invoice_id,)), "Claim already submitted", 409)
        need(len(data.discharge_summary.strip()) >= 10, "Discharge summary required")
        need(data.documents.get("itemised_bill") and data.documents.get("discharge_summary"), "Itemised bill and discharge summary are required")
        note = need(one(conn, """SELECT * FROM clinical_notes WHERE encounter_id=%s AND provisional_icd_code<>''
            ORDER BY created_at DESC,note_id DESC LIMIT 1""", (enc["encounter_id"],)), "Doctor diagnosis required for the claim")
        cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (enc["encounter_id"],))
        pre = latest_approved_preauth(conn, enc["encounter_id"])
        if cov["preauth_required"]:
            need(pre, "Approved demo pre-authorisation required")
        submitted = invoice["total_paise"] - invoice["advance_allocated_paise"]
        need(submitted > 0, "Nothing remains to claim")
        record = one(conn, """INSERT INTO claims(invoice_id,coverage_id,preauth_id,submitted_paise,
            diagnosis_code,procedure_code,discharge_summary,documents) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data.invoice_id, cov["coverage_id"], pre["preauth_id"] if pre else None,
             submitted, note["provisional_icd_code"], note["procedure_code"], data.discharge_summary.strip(), Jsonb(data.documents)))
        audit(conn, "CLAIM_SUBMITTED_DEMO", "claim", record["claim_id"])
        return record


@app.post("/api/claims/{claim_id}/decision")
def decide_claim(claim_id: int, data: DecisionIn):
    with db() as conn:
        claim = need(one(conn, "SELECT * FROM claims WHERE claim_id=%s FOR UPDATE", (claim_id,)), "Claim not found", 404)
        need(claim["status"] == "SUBMITTED_DEMO", "Claim already decided", 409)
        need(data.approved_paise <= claim["submitted_paise"], "Approval exceeds submitted claim")
        status = "APPROVED_DEMO" if data.approved_paise > 0 else "REJECTED_DEMO"
        record = one(conn, """UPDATE claims SET approved_paise=%s,status=%s,reference_no=%s,decided_at=now()
            WHERE claim_id=%s RETURNING *""", (data.approved_paise, status, data.reference_no, claim_id))
        audit(conn, "CLAIM_DECIDED_DEMO", "claim", claim_id, {"status": status})
        return record


@app.post("/api/receipts")
def add_receipt(data: ReceiptIn):
    need(data.payer_kind in {"PATIENT", "INSURER", "SCHEME", "CORPORATE"}, "Invalid payer kind")
    with db() as conn:
        invoice = need(one(conn, "SELECT * FROM invoices WHERE invoice_id=%s FOR UPDATE", (data.invoice_id,)), "Invoice not found", 404)
        enc = encounter_for(conn, invoice["encounter_id"])
        if enc["payer_route"] == "PMJAY":
            need(data.payer_kind == "SCHEME", "PM-JAY patient co-payment is blocked")
        if data.payer_kind in {"INSURER", "SCHEME", "CORPORATE"}:
            claim = need(one(conn, "SELECT * FROM claims WHERE invoice_id=%s", (data.invoice_id,)), "Submit a payer claim first")
            need(claim["status"] == "APPROVED_DEMO", "Simulated claim approval required before payer settlement")
            received = one(conn, """SELECT COALESCE(sum(amount_paise),0) AS n FROM receipts
                WHERE invoice_id=%s AND payer_kind=%s""", (data.invoice_id, data.payer_kind))["n"]
            need(data.amount_paise <= claim["approved_paise"] - received, "Receipt exceeds approved claim balance")
        remaining = balance_for(conn, invoice)["remaining_paise"]
        need(data.amount_paise <= remaining, "Receipt exceeds outstanding balance")
        record = one(conn, """INSERT INTO receipts(invoice_id,payer_kind,amount_paise,method,reference_no)
            VALUES (%s,%s,%s,%s,%s) RETURNING *""", (data.invoice_id, data.payer_kind,
              data.amount_paise, data.method, data.reference_no))
        audit(conn, "RECEIPT_POSTED", "receipt", record["receipt_id"])
        return record


@app.post("/api/refunds")
def add_refund(data: RefundIn):
    with db() as conn:
        enc = encounter_for(conn, data.encounter_id, True)
        need(enc["payer_route"] != "PMJAY", "No patient advance on PM-JAY route")
        paid = one(conn, "SELECT COALESCE(sum(amount_paise),0) AS n FROM advances WHERE encounter_id=%s", (data.encounter_id,))["n"]
        inv = one(conn, "SELECT * FROM invoices WHERE encounter_id=%s", (data.encounter_id,))
        used = inv["advance_allocated_paise"] if inv else 0
        prior = one(conn, "SELECT COALESCE(sum(amount_paise),0) AS n FROM refunds WHERE encounter_id=%s", (data.encounter_id,))["n"]
        need(inv and data.amount_paise <= paid - used - prior, "Refund exceeds unused advance credit")
        record = one(conn, """INSERT INTO refunds(encounter_id,amount_paise,method,reference_no)
            VALUES (%s,%s,%s,%s) RETURNING *""", (data.encounter_id, data.amount_paise, data.method, data.reference_no))
        audit(conn, "ADVANCE_REFUNDED", "refund", record["refund_id"])
        return record


@app.post("/api/rates")
def set_rate(data: RateIn):
    need(data.payer_route in ROUTES, "Invalid payer route")
    with db() as conn:
        service_for(conn, data.service_code)
        row = one(conn, """INSERT INTO payer_rates(service_code,payer_route,payer_label,unit_paise)
            VALUES (%s,%s,%s,%s) ON CONFLICT (service_code,payer_route,payer_label)
            DO UPDATE SET unit_paise=EXCLUDED.unit_paise RETURNING *""",
            (data.service_code, data.payer_route, data.payer_label, data.unit_paise))
        audit(conn, "RATE_CARD_UPDATED", "service", data.service_code)
        return row


@app.post("/api/demo/reset")
def demo_reset():
    need(DEMO_MODE, "Demo reset disabled", 403)
    with db() as conn:
        reset_demo(conn)
    return {"ok": True, "mode": "synthetic_demo"}


@app.get("/api/ar")
def ar_report(as_of: date | None = None):
    today = as_of or date.today()
    with db() as conn:
        data = rows(conn, """SELECT i.invoice_id,i.invoice_no,i.issued_at,e.encounter_id,e.payer_route,
            e.payer_label,p.display_label AS patient_label,i.total_paise,i.advance_allocated_paise,
            COALESCE((SELECT sum(amount_paise) FROM receipts r WHERE r.invoice_id=i.invoice_id),0) AS receipts_paise
            FROM invoices i JOIN encounters e USING(encounter_id) JOIN patients p USING(patient_id)
            ORDER BY i.issued_at""")
    buckets = {"current": 0, "days_31_60": 0, "days_61_90": 0, "over_90": 0, "total": 0}
    result = []
    for r in data:
        outstanding = max(0, r["total_paise"] - r["advance_allocated_paise"] - r["receipts_paise"])
        if outstanding == 0:
            continue
        age = max(0, (today - r["issued_at"].date()).days)
        bucket = "current" if age <= 30 else "days_31_60" if age <= 60 else "days_61_90" if age <= 90 else "over_90"
        r.update(outstanding_paise=outstanding, age_days=age, age_bucket=bucket)
        result.append(r)
        buckets[bucket] += outstanding
        buckets["total"] += outstanding
    return {"as_of": today.isoformat(), "rows": result, "totals": buckets}


@app.get("/api/gstr1")
def gstr1_report(month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"))):
    need(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month), "Use YYYY-MM period")
    with db() as conn:
        records = rows(conn, """SELECT i.invoice_id,i.invoice_no,i.issued_at,e.bill_to_gstin,e.state_code,
            l.description,l.quantity,l.taxable_paise,l.tax_category,l.tax_rate_bps,l.tax_paise,
            l.hsn_sac FROM invoices i JOIN encounters e USING(encounter_id)
            JOIN invoice_lines l USING(invoice_id) WHERE to_char(i.issued_at,'YYYY-MM')=%s
            ORDER BY i.invoice_id,l.invoice_line_id""", (month,))
    table4, table7, table8, table12 = [], {}, {}, {}
    warnings = ["Review packet only. Tax rules and HSN codes are synthetic assumptions; validate with finance before filing.",
                "This is not GST portal upload JSON and does not submit a return."]
    for r in records:
        rate = r["tax_rate_bps"] / 100
        if r["tax_category"] in {"EXEMPT", "NIL"}:
            key = (r["tax_category"], r["state_code"])
            table8[key] = table8.get(key, 0) + r["taxable_paise"]
            continue
        if r["tax_category"] != "TAXABLE":
            warnings.append(f"Invoice {r['invoice_no']} contains an unclassified line.")
            continue
        if r["bill_to_gstin"]:
            table4.append({"invoice_no": r["invoice_no"], "recipient_gstin": r["bill_to_gstin"],
                           "description": r["description"], "rate_percent": rate,
                           "taxable_paise": r["taxable_paise"], "tax_paise": r["tax_paise"]})
        else:
            key = (r["state_code"], r["tax_rate_bps"])
            item = table7.setdefault(key, {"state_code": r["state_code"], "rate_percent": rate,
                                           "taxable_paise": 0, "tax_paise": 0})
            item["taxable_paise"] += r["taxable_paise"]
            item["tax_paise"] += r["tax_paise"]
        supply_type = "B2B" if r["bill_to_gstin"] else "B2C"
        hsn_key = (supply_type, r["hsn_sac"], r["tax_rate_bps"])
        hsn = table12.setdefault(hsn_key, {"supply_type": supply_type, "hsn_sac": r["hsn_sac"], "rate_percent": rate,
                                             "quantity": 0, "taxable_paise": 0, "tax_paise": 0})
        hsn["quantity"] += r["quantity"]
        hsn["taxable_paise"] += r["taxable_paise"]
        hsn["tax_paise"] += r["tax_paise"]
    invoices = sorted({r["invoice_no"] for r in records})
    return {"period": month, "tables": {"table4": table4, "table7": list(table7.values()),
            "table8": [{"category": k[0], "state_code": k[1], "value_paise": v} for k, v in table8.items()],
            "table12": list(table12.values()), "table13": [{"series": "TVR", "issued_count": len(invoices),
             "invoice_numbers": invoices}]}, "warnings": warnings}


@app.get("/api/analytics")
def analytics(month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"))):
    need(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month), "Use YYYY-MM period")
    with db() as conn:
        invoices = rows(conn, """SELECT i.invoice_id,i.total_paise,e.payer_route
            FROM invoices i JOIN encounters e USING(encounter_id)
            WHERE to_char(i.issued_at,'YYYY-MM')=%s""", (month,))
        departments = rows(conn, """SELECT l.department,sum(l.total_paise) AS revenue_paise
            FROM invoice_lines l JOIN invoices i USING(invoice_id)
            WHERE to_char(i.issued_at,'YYYY-MM')=%s GROUP BY l.department ORDER BY revenue_paise DESC""", (month,))
        receipts = rows(conn, """SELECT r.received_at::date AS day,sum(r.amount_paise) AS amount_paise
            FROM receipts r WHERE to_char(r.received_at,'YYYY-MM')=%s
            GROUP BY r.received_at::date ORDER BY day""", (month,))
        collected = one(conn, """SELECT COALESCE(sum(amount_paise),0) AS n FROM receipts
            WHERE to_char(received_at,'YYYY-MM')=%s""", (month,))["n"]
        advances = one(conn, """SELECT COALESCE(sum(amount_paise),0) AS n FROM advances
            WHERE to_char(received_at,'YYYY-MM')=%s""", (month,))["n"]
    mix = {}
    for inv in invoices:
        mix[inv["payer_route"]] = mix.get(inv["payer_route"], 0) + inv["total_paise"]
    return {"month": month, "collections_paise": collected + advances,
            "revenue_paise": sum(i["total_paise"] for i in invoices),
            "payer_mix": [{"payer_route": k, "revenue_paise": v} for k, v in mix.items()],
            "department_revenue": departments, "daily_collections": receipts}


@app.get("/api/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500)):
    with db() as conn:
        return {"events": rows(conn, "SELECT * FROM audit_events ORDER BY audit_id DESC LIMIT %s", (limit,))}

"""Synthetic hospital billing API backed by PostgreSQL 16. Five desks share one patient record."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import hashlib
import hmac
import re
import secrets

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import billing, clinical, datamap, payer, reception, records
from .core import (DEMO_MODE, ROUTES, SCHEMA_VERSION, actor, audit, balance_for, db, need, one, rows,
                   service_for)
from .seed import password_digest, seed_demo

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
# Every table created by any schema version, dropped before a rebuild (demo data only).
ALL_TABLES = (
    "schema_meta", "notifications", "audit_events", "refunds", "receipts", "advances", "balance_adjustments", "claims",
    "preauths", "invoice_lines", "invoices", "room_stays", "dispenses", "pharmacy_orders", "procedures_performed",
    "procedure_orders", "radiology_results", "radiology_orders", "lab_results", "lab_orders", "prescriptions",
    "consultations", "charges", "coverages", "encounters", "appointments", "insurance_policies", "patients",
    "auth_sessions", "staff_users", "doctors", "wards", "package_catalog", "stock_batches", "pharmacy_items",
    "procedure_catalog", "radiology_catalog", "lab_catalog", "diagnosis_catalog", "payer_rates", "services",
    "tax_rules", "departments",
    # version 1 tables
    "admission_plans", "clinical_notes", "coding_reviews")


def rebuild(conn) -> None:
    conn.execute("DROP TABLE IF EXISTS " + ", ".join(ALL_TABLES) + " CASCADE")
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_meta(version) VALUES (%s)", (SCHEMA_VERSION,))
    seed_demo(conn)


def schema_version(conn) -> int:
    if not one(conn, "SELECT to_regclass('public.schema_meta') AS t")["t"]:
        return 0
    row = one(conn, "SELECT max(version) AS v FROM schema_meta")
    return row["v"] or 0


def initialise() -> None:
    with db() as conn:
        if schema_version(conn) != SCHEMA_VERSION:
            rebuild(conn)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialise()
    yield


app = FastAPI(title="Syndicate 1 Billing Demo API", version="3.0", lifespan=lifespan)
for module in (reception, clinical, billing, payer, records, datamap):
    app.include_router(module.router)


def roles_for_write(path: str) -> set[str]:
    """Which desk may change what. Reads are open to every signed-in desk."""
    if path.endswith("/discharge") or path.startswith(("/api/clinical/", "/api/procedures/", "/api/his/")):
        return {"DOCTOR"}
    if path.startswith(("/api/lab/", "/api/radiology/")):
        return {"LAB"}
    if path.startswith("/api/pharmacy/"):
        return {"PHARMACY"}
    if path.startswith(("/api/patients", "/api/appointments")) or path == "/api/encounters":
        return {"RECEPTION"}
    if path.startswith(("/api/coverage/", "/api/advances")):
        return {"RECEPTION", "ADMIN"}
    return {"ADMIN"}


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
        user = one(conn, """SELECT u.username,u.display_name,u.role,u.doctor_id FROM auth_sessions s
            JOIN staff_users u USING(username) WHERE s.token_hash=%s AND s.expires_at>now()""",
            (hashlib.sha256(token.encode()).hexdigest(),))
    if not user:
        return JSONResponse({"detail": "Session expired. Sign in again"}, status_code=401)
    request.state.user = user
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/api/auth/logout":
        allowed = roles_for_write(path)
        if user["role"] not in allowed:
            names = {"ADMIN": "Billing", "DOCTOR": "Doctor", "LAB": "Diagnostics", "PHARMACY": "Pharmacy",
                     "RECEPTION": "Reception"}
            return JSONResponse({"detail": f"{' or '.join(sorted(names[r] for r in allowed))} desk required for this action"},
                                status_code=403)
    return await call_next(request)


class LoginIn(BaseModel):
    username: str
    password: str


class RateIn(BaseModel):
    service_code: str
    payer_route: str
    payer_label: str = ""
    unit_paise: int = Field(ge=0)


@app.post("/api/auth/login")
def login(data: LoginIn):
    with db() as conn:
        user = one(conn, "SELECT * FROM staff_users WHERE username=%s", (data.username.lower().strip(),))
        if not user or not hmac.compare_digest(password_digest(data.password, user["password_salt"]), user["password_hash"]):
            raise HTTPException(401, "Incorrect demo sign-in")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO auth_sessions(token_hash,username,expires_at) VALUES (%s,%s,%s)",
                     (hashlib.sha256(token.encode()).hexdigest(), user["username"], datetime.now(timezone.utc) + timedelta(hours=12)))
        return {"token": token, "user": {k: user[k] for k in ("username", "display_name", "role", "doctor_id")}}


@app.get("/api/auth/me")
def me(request: Request):
    return request.state.user


@app.post("/api/auth/logout")
def logout(request: Request):
    token = request.headers.get("authorization", "")[7:]
    with db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (hashlib.sha256(token.encode()).hexdigest(),))
    return {"ok": True}


@app.get("/api/health")
def health():
    with db() as conn:
        version = schema_version(conn)
    return {"ok": True, "mode": "synthetic_demo", "database": "postgresql", "schema_version": version}


@app.post("/api/demo/reset")
def demo_reset(request: Request):
    need(DEMO_MODE, "Demo reset disabled", 403)
    with db() as conn:
        rebuild(conn)
    return {"ok": True, "mode": "synthetic_demo"}


@app.post("/api/rates")
def set_rate(data: RateIn, request: Request):
    need(data.payer_route in ROUTES, "Invalid payer route")
    with db() as conn:
        service_for(conn, data.service_code)
        row = one(conn, """INSERT INTO payer_rates(service_code,payer_route,payer_label,unit_paise) VALUES (%s,%s,%s,%s)
            ON CONFLICT (service_code,payer_route,payer_label) DO UPDATE SET unit_paise=EXCLUDED.unit_paise RETURNING *""",
            (data.service_code, data.payer_route, data.payer_label, data.unit_paise))
        audit(conn, actor(request), "RATE_UPDATED", "payer_rates", data.service_code)
        return row


def _open_bills(conn) -> list[dict]:
    bills = rows(conn, """SELECT i.*,e.payer_route,e.payer_label,e.patient_id,p.display_label AS patient_label
        FROM invoices i JOIN encounters e USING(encounter_id) JOIN patients p USING(patient_id) ORDER BY i.issued_at""")
    for b in bills:
        b.update(balance_for(conn, b))
    return bills


@app.get("/api/dashboard")
def dashboard():
    with db() as conn:
        bills = _open_bills(conn)
        stats = one(conn, """SELECT (SELECT count(*) FROM encounters WHERE status='OPEN') AS open_visits,
            (SELECT count(*) FROM encounters WHERE status='DISCHARGED') AS awaiting_bill,
            (SELECT count(*) FROM invoices) AS bills""")
        collected = one(conn, """SELECT (SELECT COALESCE(sum(amount_paise),0)::bigint FROM receipts WHERE status='SUCCEEDED') +
            (SELECT COALESCE(sum(amount_paise),0)::bigint FROM advances) - (SELECT COALESCE(sum(amount_paise),0)::bigint FROM refunds) AS n""")["n"]
    return {**stats, "collections_paise": collected,
            "outstanding_paise": sum(b["remaining_paise"] for b in bills),
            "patient_due_paise": sum(b["patient_due_paise"] for b in bills),
            "payer_due_paise": sum(b["payer_due_paise"] for b in bills)}


@app.get("/api/ar")
def ar_report(as_of: date | None = None):
    today = as_of or date.today()
    with db() as conn:
        bills = _open_bills(conn)
    buckets = {"current": 0, "days_31_60": 0, "days_61_90": 0, "over_90": 0, "total": 0}
    result = []
    for b in bills:
        if b["remaining_paise"] == 0:
            continue
        age = max(0, (today - b["issued_at"].date()).days)
        bucket = "current" if age <= 30 else "days_31_60" if age <= 60 else "days_61_90" if age <= 90 else "over_90"
        result.append({k: b[k] for k in ("invoice_id", "invoice_no", "issued_at", "due_date", "encounter_id", "patient_label",
                                         "payer_route", "payer_label", "total_paise", "patient_due_paise", "payer_due_paise",
                                         "remaining_paise")} | {"age_days": age, "age_bucket": bucket})
        buckets[bucket] += b["remaining_paise"]
        buckets["total"] += b["remaining_paise"]
    return {"as_of": today.isoformat(), "rows": result, "totals": buckets}


@app.get("/api/gstr1")
def gstr1_report(month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"))):
    need(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month), "Use YYYY-MM period")
    with db() as conn:
        records_ = rows(conn, """SELECT i.invoice_no,e.bill_to_gstin,e.state_code,l.description,l.quantity,l.taxable_paise,
            l.tax_category,l.tax_rate_bps,l.tax_paise,l.hsn_sac FROM invoices i JOIN encounters e USING(encounter_id)
            JOIN invoice_lines l USING(invoice_id) WHERE to_char(i.issued_at,'YYYY-MM')=%s ORDER BY i.invoice_id,l.line_no""",
            (month,))
    table4, table7, table8, table12 = [], {}, {}, {}
    warnings = ["Review packet only. Tax rules and HSN codes are teaching assumptions; validate with finance before filing.",
                "This is not GST portal upload JSON and does not submit a return."]
    for r in records_:
        rate = r["tax_rate_bps"] / 100
        if r["tax_category"] in {"EXEMPT", "NIL"}:
            key = (r["tax_category"], r["state_code"])
            table8[key] = table8.get(key, 0) + r["taxable_paise"]
            continue
        if r["tax_category"] != "TAXABLE":
            warnings.append(f"Bill {r['invoice_no']} has an unclassified line.")
            continue
        if r["bill_to_gstin"]:
            table4.append({"invoice_no": r["invoice_no"], "recipient_gstin": r["bill_to_gstin"], "description": r["description"],
                           "rate_percent": rate, "taxable_paise": r["taxable_paise"], "tax_paise": r["tax_paise"]})
        else:
            item = table7.setdefault((r["state_code"], r["tax_rate_bps"]), {"state_code": r["state_code"], "rate_percent": rate,
                                                                           "taxable_paise": 0, "tax_paise": 0})
            item["taxable_paise"] += r["taxable_paise"]
            item["tax_paise"] += r["tax_paise"]
        supply = "B2B" if r["bill_to_gstin"] else "B2C"
        hsn = table12.setdefault((supply, r["hsn_sac"], r["tax_rate_bps"]), {"supply_type": supply, "hsn_sac": r["hsn_sac"],
                                 "rate_percent": rate, "quantity": 0, "taxable_paise": 0, "tax_paise": 0})
        hsn["quantity"] += r["quantity"]
        hsn["taxable_paise"] += r["taxable_paise"]
        hsn["tax_paise"] += r["tax_paise"]
    numbers = sorted({r["invoice_no"] for r in records_})
    return {"period": month, "tables": {"table4": table4, "table7": list(table7.values()),
            "table8": [{"category": k[0], "state_code": k[1], "value_paise": v} for k, v in table8.items()],
            "table12": list(table12.values()), "table13": [{"series": "SYN", "issued_count": len(numbers),
             "invoice_numbers": numbers}]}, "warnings": warnings}


@app.get("/api/analytics")
def analytics(month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"))):
    need(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month), "Use YYYY-MM period")
    with db() as conn:
        bills = rows(conn, """SELECT i.total_paise,e.payer_route FROM invoices i JOIN encounters e USING(encounter_id)
            WHERE to_char(i.issued_at,'YYYY-MM')=%s""", (month,))
        departments = rows(conn, """SELECT d.name AS department,sum(l.total_paise) AS revenue_paise FROM invoice_lines l
            JOIN invoices i USING(invoice_id) JOIN departments d ON d.department_id=l.department
            WHERE to_char(i.issued_at,'YYYY-MM')=%s GROUP BY d.name ORDER BY revenue_paise DESC""", (month,))
        collected = one(conn, """SELECT COALESCE(sum(amount_paise),0)::bigint AS n FROM receipts WHERE status='SUCCEEDED'
            AND to_char(received_at,'YYYY-MM')=%s""", (month,))["n"]
    mix: dict[str, int] = {}
    for b in bills:
        mix[b["payer_route"]] = mix.get(b["payer_route"], 0) + b["total_paise"]
    return {"month": month, "collections_paise": collected, "revenue_paise": sum(b["total_paise"] for b in bills),
            "payer_mix": [{"payer_route": k, "revenue_paise": v} for k, v in mix.items()], "department_revenue": departments}


@app.get("/api/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500)):
    with db() as conn:
        return {"events": rows(conn, "SELECT * FROM audit_events ORDER BY audit_id DESC LIMIT %s", (limit,))}

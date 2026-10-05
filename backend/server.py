"""Local HIS billing prototype for synthetic teaching cases.

Run from the repository root with: python backend/server.py
Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "frontend"
DB_PATH = Path(os.environ.get("TIVERI_DB", str(ROOT / "demo.sqlite3")))
ROUTES = ("SELF", "PRIVATE", "PMJAY", "CGHS", "CORPORATE")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def audit(db: sqlite3.Connection, action: str, kind: str, entity_id: str) -> None:
    db.execute(
        "INSERT INTO audit_event(action,entity_type,entity_id,occurred_at) VALUES (?,?,?,?)",
        (action, kind, entity_id, now()),
    )


def seed(db: sqlite3.Connection) -> None:
    """Invented cases and tariffs. No actual patient or government rate is stored."""
    db.executemany("INSERT INTO patient VALUES (?,?)", [
        ("P-DEMO-01", "Demo Patient A"),
        ("P-DEMO-02", "Demo Patient B"),
        ("P-DEMO-03", "Demo Patient C"),
        ("P-DEMO-04", "Demo Patient D"),
        ("P-DEMO-05", "Demo Patient E"),
    ])
    db.executemany("INSERT INTO encounter VALUES (?,?,?,?,?)", [
        ("E-OPD-01", "P-DEMO-01", "OPD", "SELF", now()),
        ("E-IPD-02", "P-DEMO-02", "IPD", "PRIVATE", now()),
        ("E-IPD-03", "P-DEMO-03", "IPD", "PMJAY", now()),
        ("E-OPD-04", "P-DEMO-04", "OPD", "CGHS", now()),
        ("E-OPD-05", "P-DEMO-05", "OPD", "CORPORATE", now()),
    ])
    db.executemany("INSERT INTO coverage VALUES (?,?,?,?,?,?,?)", [
        ("C-DEMO-02", "P-DEMO-02", "PRIVATE", "Demo private insurer", "SIM-POLICY-02", 1, "UNVERIFIED_DEMO"),
        ("C-DEMO-03", "P-DEMO-03", "PMJAY", "PM-JAY training route", "SIM-SCHEME-03", 1, "UNVERIFIED_DEMO"),
        ("C-DEMO-04", "P-DEMO-04", "CGHS", "CGHS training route", "SIM-CGHS-04", 0, "UNVERIFIED_DEMO"),
        ("C-DEMO-05", "P-DEMO-05", "CORPORATE", "Demo employer", "SIM-CORP-05", 0, "UNVERIFIED_DEMO"),
    ])
    db.executemany("INSERT INTO service_catalog VALUES (?,?,?,?,?,?)", [
        ("CONSULT", "OPD consultation", "OPD", 50000, "EXEMPT_DEMO", 1),
        ("CBC", "Complete blood count", "Laboratory", 35000, "EXEMPT_DEMO", 1),
        ("XRAY", "Chest X-ray", "Radiology", 65000, "EXEMPT_DEMO", 1),
        ("BED", "General ward bed, one day", "Ward", 250000, "EXEMPT_DEMO", 1),
        ("PROC", "Procedure, training example", "Procedure", 900000, "EXEMPT_DEMO", 1),
        ("DAYCARE", "Day-care procedure example", "Day care", 450000, "EXEMPT_DEMO", 1),
        ("PMJAY-PKG", "PM-JAY package placeholder", "Scheme", 1200000, "EXEMPT_DEMO", 1),
        ("PHARM-REVIEW", "Pharmacy item, rate review needed", "Pharmacy", 120000, "REVIEW_REQUIRED", 0),
    ])
    db.executemany("INSERT INTO payer_rate VALUES (?,?,?)", [
        ("CONSULT", "CGHS", 40000),
        ("CONSULT", "CORPORATE", 45000),
        ("CBC", "CGHS", 30000),
        ("BED", "PRIVATE", 230000),
        ("PROC", "PRIVATE", 850000),
    ])
    for encounter_id, code, qty, event in [
        ("E-OPD-01", "CONSULT", 1, "SEED-OPD-CONSULT"),
        ("E-OPD-01", "CBC", 1, "SEED-OPD-CBC"),
        ("E-IPD-02", "BED", 2, "SEED-IPD-BED"),
        ("E-IPD-02", "PROC", 1, "SEED-IPD-PROC"),
        ("E-IPD-03", "PMJAY-PKG", 1, "SEED-PMJAY-PKG"),
        ("E-OPD-04", "CONSULT", 1, "SEED-CGHS-CONSULT"),
        ("E-OPD-05", "CONSULT", 1, "SEED-CORP-CONSULT"),
    ]:
        add_charge(db, {"encounter_id": encounter_id, "service_code": code, "quantity": qty, "source_event_id": event})


def init_db() -> None:
    with closing(connect()) as db:
        db.executescript((ROOT / "backend" / "schema.sql").read_text(encoding="utf-8"))
        if db.execute("SELECT COUNT(*) FROM patient").fetchone()[0] == 0:
            seed(db)
            db.commit()


def reset_demo(db: sqlite3.Connection) -> dict:
    for table in ("audit_event", "payment", "claim", "invoice_line", "invoice", "preauth", "charge", "payer_rate", "service_catalog", "coverage", "encounter", "patient"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM sqlite_sequence")
    seed(db)
    audit(db, "DEMO_RESET", "workspace", "synthetic")
    return {"ok": True}


def state(db: sqlite3.Connection) -> dict:
    tables = ("patient", "encounter", "coverage", "service_catalog", "payer_rate", "charge", "preauth", "invoice", "invoice_line", "claim", "payment", "audit_event")
    return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")] for table in tables}


class ClientError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.status = status
        super().__init__(message)


def text_field(data: dict, key: str, limit: int = 80) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ClientError(f"{key} must contain 1 to {limit} characters")
    return value.strip()


def int_field(data: dict, key: str, minimum: int = 0, maximum: int | None = None) -> int:
    value = data.get(key)
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ClientError(f"{key} must be an integer >= {minimum}{upper}")
    return value


def create_encounter(db: sqlite3.Connection, data: dict) -> dict:
    label = text_field(data, "display_label", 70)
    setting = text_field(data, "setting", 20).upper()
    route = text_field(data, "payer_route", 20).upper()
    if setting not in ("OPD", "IPD", "EMERGENCY", "DAY_CARE") or route not in ROUTES:
        raise ClientError("Choose a supported setting and payer route")
    patient_id, encounter_id = "P-" + uuid4().hex[:10].upper(), "E-" + uuid4().hex[:10].upper()
    db.execute("INSERT INTO patient VALUES (?,?)", (patient_id, label))
    db.execute("INSERT INTO encounter VALUES (?,?,?,?,?)", (encounter_id, patient_id, setting, route, now()))
    if route != "SELF":
        payer_label = text_field(data, "payer_label", 70)
        coverage_id = "C-" + uuid4().hex[:10].upper()
        db.execute("INSERT INTO coverage VALUES (?,?,?,?,?,?,?)", (
            coverage_id, patient_id, route, payer_label, "SIM-" + uuid4().hex[:8].upper(),
            1 if route in ("PRIVATE", "PMJAY") else 0, "UNVERIFIED_DEMO",
        ))
    audit(db, "ENCOUNTER_OPENED", "encounter", encounter_id)
    return {"patient_id": patient_id, "encounter_id": encounter_id}


def add_charge(db: sqlite3.Connection, data: dict) -> dict:
    event_id = text_field(data, "source_event_id", 80)
    encounter_id = text_field(data, "encounter_id", 80)
    service_code = text_field(data, "service_code", 50)
    quantity = int_field(data, "quantity", 1, 100)
    existing = db.execute("SELECT * FROM charge WHERE source_event_id=?", (event_id,)).fetchone()
    if existing:
        if (existing["encounter_id"], existing["service_code"], existing["quantity"]) != (encounter_id, service_code, quantity):
            raise ClientError("source_event_id already belongs to another charge", 409)
        return {"charge": dict(existing), "duplicate": True}
    enc = db.execute("SELECT * FROM encounter WHERE encounter_id=?", (encounter_id,)).fetchone()
    service = db.execute("SELECT * FROM service_catalog WHERE service_code=? AND active=1", (service_code,)).fetchone()
    if not enc or not service:
        raise ClientError("Encounter or active service not found", 404)
    if service_code == "PMJAY-PKG" and enc["payer_route"] != "PMJAY":
        raise ClientError("The example package is only for the PM-JAY training route")
    if db.execute("SELECT 1 FROM invoice WHERE encounter_id=?", (encounter_id,)).fetchone():
        raise ClientError("The final bill is locked", 409)
    rate = db.execute("SELECT unit_price_paise FROM payer_rate WHERE service_code=? AND payer_kind=?", (service_code, enc["payer_route"])).fetchone()
    price = rate[0] if rate else service["list_price_paise"]
    cur = db.execute(
        "INSERT INTO charge(encounter_id,service_code,quantity,unit_price_paise,amount_paise,source_event_id,created_at) VALUES (?,?,?,?,?,?,?)",
        (encounter_id, service_code, quantity, price, quantity * price, event_id, now()),
    )
    audit(db, "HIS_CHARGE_RECEIVED", "charge", str(cur.lastrowid))
    return {"charge": dict(db.execute("SELECT * FROM charge WHERE charge_id=?", (cur.lastrowid,)).fetchone()), "duplicate": False}


def create_preauth(db: sqlite3.Connection, data: dict) -> dict:
    encounter_id = text_field(data, "encounter_id")
    coverage_id = text_field(data, "coverage_id")
    amount = int_field(data, "requested_paise", 1)
    enc = db.execute("SELECT * FROM encounter WHERE encounter_id=?", (encounter_id,)).fetchone()
    cov = db.execute("SELECT * FROM coverage WHERE coverage_id=?", (coverage_id,)).fetchone()
    if not enc or not cov:
        raise ClientError("Encounter or coverage not found", 404)
    if enc["patient_id"] != cov["patient_id"] or enc["payer_route"] != cov["payer_kind"]:
        raise ClientError("Coverage does not match this encounter", 409)
    if not cov["preauth_required"]:
        raise ClientError("This demo route does not require a preauthorisation")
    if db.execute("SELECT 1 FROM invoice WHERE encounter_id=?", (encounter_id,)).fetchone():
        raise ClientError("Request preauthorisation before the final invoice", 409)
    if db.execute("SELECT 1 FROM preauth WHERE encounter_id=?", (encounter_id,)).fetchone():
        raise ClientError("A request already exists", 409)
    cur = db.execute("INSERT INTO preauth(encounter_id,coverage_id,status,requested_paise,created_at) VALUES (?,?,?,?,?)",
                     (encounter_id, coverage_id, "SUBMITTED_DEMO", amount, now()))
    audit(db, "DEMO_PREAUTH_SUBMITTED", "preauth", str(cur.lastrowid))
    return {"preauth_id": cur.lastrowid, "status": "SUBMITTED_DEMO"}


def decide_preauth(db: sqlite3.Connection, item_id: int, data: dict) -> dict:
    amount = int_field(data, "approved_paise", 0)
    row = db.execute("SELECT * FROM preauth WHERE preauth_id=?", (item_id,)).fetchone()
    if not row:
        raise ClientError("Preauthorisation not found", 404)
    if row["status"] != "SUBMITTED_DEMO":
        raise ClientError("Decision already recorded", 409)
    if amount > row["requested_paise"]:
        raise ClientError("Approval exceeds request")
    status = "APPROVED_DEMO" if amount else "REJECTED_DEMO"
    db.execute("UPDATE preauth SET status=?,approved_paise=? WHERE preauth_id=?", (status, amount, item_id))
    audit(db, "DEMO_PREAUTH_DECISION", "preauth", str(item_id))
    return {"preauth_id": item_id, "status": status, "approved_paise": amount}


def create_invoice(db: sqlite3.Connection, data: dict) -> dict:
    encounter_id = text_field(data, "encounter_id")
    if not db.execute("SELECT 1 FROM encounter WHERE encounter_id=?", (encounter_id,)).fetchone():
        raise ClientError("Encounter not found", 404)
    if db.execute("SELECT 1 FROM invoice WHERE encounter_id=?", (encounter_id,)).fetchone():
        raise ClientError("One final invoice already exists", 409)
    charges = db.execute("SELECT c.*,s.description,s.department,s.tax_code FROM charge c JOIN service_catalog s USING(service_code) WHERE c.encounter_id=? ORDER BY c.charge_id", (encounter_id,)).fetchall()
    if not charges:
        raise ClientError("Add a delivered service first")
    if any(row["tax_code"] == "REVIEW_REQUIRED" for row in charges):
        raise ClientError("Finance must classify the tax treatment before finalising")
    subtotal = sum(row["amount_paise"] for row in charges)
    cur = db.execute("INSERT INTO invoice(encounter_id,status,subtotal_paise,tax_paise,total_paise,created_at) VALUES (?,?,?,?,?,?)",
                     (encounter_id, "FINAL", subtotal, 0, subtotal, now()))
    for row in charges:
        db.execute("INSERT INTO invoice_line(invoice_id,charge_id,description,department,quantity,unit_price_paise,amount_paise) VALUES (?,?,?,?,?,?,?)",
                   (cur.lastrowid, row["charge_id"], row["description"], row["department"], row["quantity"], row["unit_price_paise"], row["amount_paise"]))
    audit(db, "INVOICE_FINALISED", "invoice", str(cur.lastrowid))
    return {"invoice_id": cur.lastrowid, "total_paise": subtotal}


def create_claim(db: sqlite3.Connection, data: dict) -> dict:
    invoice_id = int_field(data, "invoice_id", 1)
    coverage_id = text_field(data, "coverage_id")
    inv = db.execute("SELECT i.*,e.patient_id,e.payer_route FROM invoice i JOIN encounter e USING(encounter_id) WHERE i.invoice_id=?", (invoice_id,)).fetchone()
    cov = db.execute("SELECT * FROM coverage WHERE coverage_id=?", (coverage_id,)).fetchone()
    if not inv or not cov:
        raise ClientError("Invoice or coverage not found", 404)
    if inv["patient_id"] != cov["patient_id"] or inv["payer_route"] != cov["payer_kind"]:
        raise ClientError("Coverage does not match the invoice", 409)
    if db.execute("SELECT 1 FROM claim WHERE invoice_id=?", (invoice_id,)).fetchone():
        raise ClientError("Claim already exists", 409)
    preauth = db.execute("SELECT * FROM preauth WHERE encounter_id=? AND coverage_id=?", (inv["encounter_id"], coverage_id)).fetchone()
    if cov["preauth_required"] and (not preauth or preauth["status"] != "APPROVED_DEMO"):
        raise ClientError("Record an approved demo preauthorisation first")
    cur = db.execute("INSERT INTO claim(invoice_id,coverage_id,preauth_id,status,requested_paise,created_at) VALUES (?,?,?,?,?,?)",
                     (invoice_id, coverage_id, preauth["preauth_id"] if preauth else None, "SUBMITTED_DEMO", inv["total_paise"], now()))
    audit(db, "DEMO_CLAIM_SUBMITTED", "claim", str(cur.lastrowid))
    return {"claim_id": cur.lastrowid, "status": "SUBMITTED_DEMO"}


def decide_claim(db: sqlite3.Connection, item_id: int, data: dict) -> dict:
    amount = int_field(data, "approved_paise", 0)
    row = db.execute("SELECT * FROM claim WHERE claim_id=?", (item_id,)).fetchone()
    if not row:
        raise ClientError("Claim not found", 404)
    if row["status"] != "SUBMITTED_DEMO":
        raise ClientError("Decision already recorded", 409)
    if amount > row["requested_paise"]:
        raise ClientError("Approval exceeds claimed amount")
    status = "APPROVED_DEMO" if amount else "REJECTED_DEMO"
    db.execute("UPDATE claim SET status=?,approved_paise=? WHERE claim_id=?", (status, amount, item_id))
    audit(db, "DEMO_CLAIM_DECISION", "claim", str(item_id))
    return {"claim_id": item_id, "status": status, "approved_paise": amount}


def add_payment(db: sqlite3.Connection, data: dict) -> dict:
    invoice_id = int_field(data, "invoice_id", 1)
    amount = int_field(data, "amount_paise", 1)
    payer_kind = text_field(data, "payer_kind", 20).upper()
    method = text_field(data, "method", 60)
    if payer_kind not in ("PATIENT", "INSURER", "SCHEME", "CORPORATE"):
        raise ClientError("Invalid payer kind")
    inv = db.execute("SELECT i.*,e.payer_route FROM invoice i JOIN encounter e USING(encounter_id) WHERE i.invoice_id=?", (invoice_id,)).fetchone()
    if not inv:
        raise ClientError("Invoice not found", 404)
    paid = db.execute("SELECT COALESCE(SUM(amount_paise),0) FROM payment WHERE invoice_id=?", (invoice_id,)).fetchone()[0]
    if amount > inv["total_paise"] - paid:
        raise ClientError("Receipt exceeds outstanding balance")
    if payer_kind == "PATIENT" and inv["payer_route"] == "PMJAY":
        raise ClientError("Do not collect a patient copayment on this PM-JAY demo package")
    if payer_kind != "PATIENT":
        expected = {"PRIVATE": "INSURER", "PMJAY": "SCHEME", "CGHS": "SCHEME", "CORPORATE": "CORPORATE"}.get(inv["payer_route"])
        if payer_kind != expected:
            raise ClientError("Receipt payer does not match the encounter route")
        claim = db.execute("SELECT * FROM claim WHERE invoice_id=?", (invoice_id,)).fetchone()
        if not claim or claim["status"] != "APPROVED_DEMO":
            raise ClientError("Record a demo claim approval before payer settlement")
        payer_paid = db.execute("SELECT COALESCE(SUM(amount_paise),0) FROM payment WHERE invoice_id=? AND payer_kind=?", (invoice_id, payer_kind)).fetchone()[0]
        if amount > claim["approved_paise"] - payer_paid:
            raise ClientError("Payer receipt exceeds approved amount")
    cur = db.execute("INSERT INTO payment(invoice_id,payer_kind,method,amount_paise,recorded_at) VALUES (?,?,?,?,?)",
                     (invoice_id, payer_kind, method, amount, now()))
    audit(db, "PAYMENT_RECORDED", "payment", str(cur.lastrowid))
    return {"payment_id": cur.lastrowid, "remaining_paise": inv["total_paise"] - paid - amount}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print("%s %s" % (self.address_string(), fmt % args))

    def send_json(self, obj: dict, status: int = 200) -> None:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json({"ok": True, "mode": "synthetic_demo", "database": "sqlite"})
        elif path == "/api/state":
            with closing(connect()) as db:
                self.send_json(state(db))
        elif path in ("/", "/index.html", "/app.js", "/style.css"):
            file = STATIC / ("index.html" if path == "/" else path[1:])
            raw = file.read_bytes()
            content_type = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if not path.startswith("/api/"):
                raise ClientError("Not found", 404)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 10000:
                raise ClientError("JSON body must be 1 to 10000 bytes")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ClientError("JSON object required")
            with closing(connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                if path == "/api/encounters":
                    result = create_encounter(db, data)
                elif path == "/api/his/events":
                    result = add_charge(db, data)
                elif path == "/api/preauth":
                    result = create_preauth(db, data)
                elif path.startswith("/api/preauth/") and path.endswith("/decision"):
                    result = decide_preauth(db, int(path.split("/")[3]), data)
                elif path == "/api/invoices":
                    result = create_invoice(db, data)
                elif path == "/api/claims":
                    result = create_claim(db, data)
                elif path.startswith("/api/claims/") and path.endswith("/decision"):
                    result = decide_claim(db, int(path.split("/")[3]), data)
                elif path == "/api/payments":
                    result = add_payment(db, data)
                elif path == "/api/demo/reset":
                    result = reset_demo(db)
                else:
                    raise ClientError("Not found", 404)
                db.commit()
            self.send_json(result, 200 if result.get("duplicate") else 201)
        except ClientError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid request"}, 400)
        except sqlite3.IntegrityError:
            self.send_json({"error": "Database constraint rejected the request"}, 409)
        except Exception as exc:
            print(f"Server error: {exc}")
            self.send_json({"error": "Server error"}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Tiveri billing demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    init_db()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Tiveri synthetic demo at http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

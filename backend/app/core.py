"""Shared database helpers and billing rules used by every router and the seed data."""

from __future__ import annotations

from datetime import date
from typing import Any
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import HTTPException, Request

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tiveri_demo@127.0.0.1:55432/tiveri_demo")
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
SCHEMA_VERSION = 2
ROUTES = {"SELF", "PRIVATE", "PMJAY", "CGHS", "CORPORATE"}
SETTINGS = {"OPD", "IPD", "EMERGENCY", "DAY_CARE"}
ROOM_GST_THRESHOLD_PAISE = 500000  # specified non-ICU room above Rs 5,000 per day


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


def actor(request: Request) -> str:
    return request.state.user["username"]


def audit(conn: psycopg.Connection, who: str, action: str, entity: str, entity_id: Any, details: dict | None = None) -> None:
    """Entity names are table names so the Data map can match events to records."""
    conn.execute("""INSERT INTO audit_events(actor,action,entity,entity_id,details,created_at)
        VALUES (%s,%s,%s,%s,%s,clock_timestamp())""",
                 (who, action, entity, str(entity_id), Jsonb(details or {})))


def notify(conn: psycopg.Connection, who: str, patient_id: str, kind: str, message: str, *,
           encounter_id: str | None = None, invoice_id: int | None = None, appointment_id: int | None = None) -> dict:
    row = one(conn, """INSERT INTO notifications(patient_id,encounter_id,invoice_id,appointment_id,kind,message,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (patient_id, encounter_id, invoice_id, appointment_id, kind, message, who))
    audit(conn, who, f"NOTIFICATION_{kind}", "notifications", row["notification_id"])
    return row


# --- lookups ---------------------------------------------------------------

def encounter_for(conn: psycopg.Connection, encounter_id: str, lock: bool = False) -> dict:
    return need(one(conn, "SELECT * FROM encounters WHERE encounter_id=%s" + (" FOR UPDATE" if lock else ""),
                    (encounter_id,)), "Visit not found", 404)


def service_for(conn: psycopg.Connection, service_code: str) -> dict:
    return need(one(conn, "SELECT * FROM services WHERE service_code=%s AND active=true", (service_code,)),
                f"Service {service_code} not found or inactive", 404)


def tax_for(conn: psycopg.Connection, rule_code: str, on_date: date | None = None) -> dict:
    day = on_date or date.today()
    result = one(conn, """SELECT * FROM tax_rules WHERE rule_code=%s AND effective_from<=%s
        AND (effective_to IS NULL OR effective_to>=%s) ORDER BY effective_from DESC LIMIT 1""", (rule_code, day, day))
    return need(result, f"Tax rule {rule_code} has no effective version")


def price_for(conn: psycopg.Connection, service: dict, encounter: dict) -> int:
    rate = one(conn, """SELECT unit_paise FROM payer_rates WHERE service_code=%s AND payer_route=%s
        AND payer_label IN (%s,'') ORDER BY length(payer_label) DESC LIMIT 1""",
        (service["service_code"], encounter["payer_route"], encounter["payer_label"]))
    return rate["unit_paise"] if rate else service["base_unit_paise"]


def tax_amount(subtotal_paise: int, rate_bps: int) -> int:
    """Half-up rounding that is symmetric for reversal (negative) lines."""
    sign = -1 if subtotal_paise < 0 else 1
    return sign * ((abs(subtotal_paise) * rate_bps + 5000) // 10000)


def age_years(dob: date | None) -> int | None:
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# --- charges ---------------------------------------------------------------

def active_charges(conn: psycopg.Connection, encounter_id: str) -> list[dict]:
    """Original CHARGE rows that have not been reversed or absorbed by a package."""
    return rows(conn, """SELECT c.*,s.kind FROM charges c JOIN services s USING(service_code)
        WHERE c.encounter_id=%s AND c.charge_type='CHARGE'
        AND NOT EXISTS (SELECT 1 FROM charges o WHERE o.reverses_charge_id=c.charge_id)
        ORDER BY c.charge_id""", (encounter_id,))


def applied_package(conn: psycopg.Connection, encounter_id: str) -> dict | None:
    return one(conn, """SELECT p.* FROM charges c JOIN package_catalog p ON p.service_code=c.service_code
        WHERE c.encounter_id=%s AND c.charge_type='CHARGE'
        AND NOT EXISTS (SELECT 1 FROM charges o WHERE o.reverses_charge_id=c.charge_id)
        ORDER BY c.charge_id DESC LIMIT 1""", (encounter_id,))


def offset_charge(conn: psycopg.Connection, who: str, original: dict, charge_type: str, reason: str) -> dict:
    """REVERSAL or PACKAGE_ADJ: a negative copy of the original. Nothing is ever deleted or overwritten."""
    prefix = "REV" if charge_type == "REVERSAL" else "PKGADJ"
    row = one(conn, """INSERT INTO charges(encounter_id,source_event_id,source_type,source_id,charge_type,reverses_charge_id,
        service_code,description,department,quantity,unit_price_paise,tax_rule_code,tax_category,tax_rate_bps,hsn_sac,
        reason,created_by,room_stay_id) VALUES (%s,%s,'OFFSET',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (original["encounter_id"], f"{prefix}-{original['charge_id']}", str(original["charge_id"]), charge_type,
         original["charge_id"], original["service_code"], original["description"], original["department"],
         original["quantity"], original["unit_price_paise"], original["tax_rule_code"], original["tax_category"],
         original["tax_rate_bps"], original["hsn_sac"], reason, who, original.get("room_stay_id")))
    audit(conn, who, f"CHARGE_{charge_type}", "charges", row["charge_id"],
          {"offsets_charge_id": original["charge_id"], "reason": reason})
    return row


def create_charge(conn: psycopg.Connection, who: str, encounter_id: str, service_code: str, quantity: int,
                  source_event_id: str, *, source_type: str = "HIS_EVENT", source_id: str = "",
                  room_stay_id: int | None = None, tax_rule_override: str | None = None,
                  allow_closed: bool = False) -> dict:
    """Post one priced charge from a completed clinical event. Retrying the same event returns the same charge."""
    need(0 < quantity <= 1000, "Quantity must be between 1 and 1000")
    need(source_event_id.strip(), "A unique source event ID is required")
    encounter = encounter_for(conn, encounter_id, True)
    existing = one(conn, "SELECT * FROM charges WHERE source_event_id=%s", (source_event_id,))
    if existing:
        if (existing["encounter_id"], existing["service_code"], existing["quantity"], existing["source_type"]) != \
                (encounter_id, service_code, quantity, source_type):
            raise HTTPException(409, "This event ID belongs to a different charge")
        return {"charge": existing, "duplicate": True}
    need(encounter["status"] == "OPEN" or allow_closed, "Charges need an open visit")
    service = service_for(conn, service_code)
    unit = price_for(conn, service, encounter)
    rule_code = tax_rule_override or service["tax_rule_code"]
    if service["kind"] == "ROOM" and not tax_rule_override:
        rule_code = "ROOM_5_DEMO" if unit > ROOM_GST_THRESHOLD_PAISE else "CARE_EXEMPT"
    rule = tax_for(conn, rule_code)
    charge = one(conn, """INSERT INTO charges(encounter_id,source_event_id,source_type,source_id,service_code,description,
        department,quantity,unit_price_paise,tax_rule_code,tax_category,tax_rate_bps,hsn_sac,created_by,room_stay_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (encounter_id, source_event_id, source_type, source_id, service_code, service["description"],
         service["department_id"], quantity, unit, rule_code, rule["tax_category"], rule["rate_bps"], rule["hsn_sac"],
         who, room_stay_id))
    audit(conn, who, "CHARGE_POSTED", "charges", charge["charge_id"],
          {"source_event_id": source_event_id, "service_code": service_code})
    package = applied_package(conn, encounter_id)
    if package and service["kind"] in package["included_kinds"]:
        offset_charge(conn, who, charge, "PACKAGE_ADJ", f"Included in package {package['package_code']}")
    return {"charge": charge, "duplicate": False}


def running_totals(conn: psycopg.Connection, encounter_id: str) -> dict:
    lines = rows(conn, "SELECT subtotal_paise,tax_rate_bps FROM charges WHERE encounter_id=%s", (encounter_id,))
    subtotal = sum(l["subtotal_paise"] for l in lines)
    tax = sum(tax_amount(l["subtotal_paise"], l["tax_rate_bps"]) for l in lines)
    return {"subtotal_paise": subtotal, "tax_paise": tax, "total_paise": subtotal + tax}


# --- shares and balances ---------------------------------------------------

def split_shares(encounter: dict, coverage: dict | None, total: int) -> tuple[int, int]:
    """Patient share and payer share of a bill."""
    if encounter["payment_mode"] != "CASHLESS" or encounter["payer_route"] == "SELF":
        return total, 0
    copay = tax_amount(total, coverage["copay_bps"]) if coverage and encounter["payer_route"] == "PRIVATE" else 0
    return copay, total - copay


def deposits_available(conn: psycopg.Connection, encounter_id: str) -> int:
    paid = one(conn, "SELECT COALESCE(sum(amount_paise),0)::bigint AS n FROM advances WHERE encounter_id=%s", (encounter_id,))["n"]
    refunded = one(conn, "SELECT COALESCE(sum(amount_paise),0)::bigint AS n FROM refunds WHERE encounter_id=%s", (encounter_id,))["n"]
    return paid - refunded


def balance_for(conn: psycopg.Connection, invoice: dict) -> dict:
    """Who still owes what. Only SUCCEEDED payments count; claim shortfalls move via balance_adjustments."""
    received = one(conn, """SELECT
        COALESCE(sum(amount_paise) FILTER (WHERE payer_kind='PATIENT'),0)::bigint AS patient,
        COALESCE(sum(amount_paise) FILTER (WHERE payer_kind<>'PATIENT'),0)::bigint AS payer
        FROM receipts WHERE invoice_id=%s AND status='SUCCEEDED'""", (invoice["invoice_id"],))
    adj = one(conn, """SELECT
        COALESCE(sum(amount_paise) FILTER (WHERE kind='TO_PATIENT'),0)::bigint AS to_patient,
        COALESCE(sum(amount_paise) FILTER (WHERE kind='WRITE_OFF'),0)::bigint AS write_off
        FROM balance_adjustments WHERE invoice_id=%s""", (invoice["invoice_id"],))
    patient_share = invoice["patient_share_paise"] + adj["to_patient"]
    payer_share = invoice["payer_share_paise"] - adj["to_patient"] - adj["write_off"]
    deposit_used = min(patient_share, max(0, deposits_available(conn, invoice["encounter_id"])))
    patient_due = max(0, patient_share - deposit_used - received["patient"])
    payer_due = max(0, payer_share - received["payer"])
    remaining = patient_due + payer_due
    paid = deposit_used + received["patient"] + received["payer"]
    return {"patient_share_paise": patient_share, "payer_share_paise": payer_share,
            "deposit_used_paise": deposit_used, "patient_received_paise": received["patient"],
            "payer_received_paise": received["payer"], "moved_to_patient_paise": adj["to_patient"],
            "written_off_paise": adj["write_off"], "patient_due_paise": patient_due, "payer_due_paise": payer_due,
            "paid_paise": paid, "remaining_paise": remaining,
            "payment_status": "PAID" if remaining == 0 else "PARTIAL" if paid > 0 else "UNPAID"}


def settle_if_paid(conn: psycopg.Connection, who: str, invoice: dict) -> None:
    """Workflow: no outstanding balance -> bill settled -> patient notification."""
    if balance_for(conn, invoice)["remaining_paise"] > 0:
        return
    if one(conn, "SELECT 1 FROM notifications WHERE invoice_id=%s AND kind='SETTLED'", (invoice["invoice_id"],)):
        return
    enc = encounter_for(conn, invoice["encounter_id"])
    notify(conn, who, enc["patient_id"], "SETTLED",
           f"Bill {invoice['invoice_no']} is fully settled. Thank you. Follow-up as advised by your doctor.",
           encounter_id=enc["encounter_id"], invoice_id=invoice["invoice_id"])

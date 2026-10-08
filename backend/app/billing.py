"""Billing desk: pre-bill audit, charge correction, bill generation, packages and pre-authorisation."""

from __future__ import annotations

from datetime import date, timedelta
from collections import Counter

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .core import (active_charges, actor, applied_package, audit, create_charge, db, encounter_for, need,
                   offset_charge, one, rows, running_totals, split_shares, tax_amount)

router = APIRouter()
PATIENT_DUE_DAYS = 15


class ReverseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class InvoiceIn(BaseModel):
    encounter_id: str


class PackageIn(BaseModel):
    encounter_id: str
    package_code: str


class PreauthIn(BaseModel):
    encounter_id: str
    requested_paise: int = Field(gt=0)
    request_type: str = "INITIAL"


class PreauthDecisionIn(BaseModel):
    outcome: str
    approved_paise: int = Field(default=0, ge=0)
    reference_no: str = ""


def finding(severity: str, rule: str, message: str, charge_id: int | None = None) -> dict:
    return {"severity": severity, "rule": rule, "message": message, "charge_id": charge_id}


def completed_sources(conn, encounter_id: str) -> Counter:
    """How many times each service was actually delivered, per day (from completed clinical records)."""
    delivered = rows(conn, """
        SELECT c.service_code, r.report_date::date AS day FROM lab_results r JOIN lab_orders o USING(lab_order_id)
          JOIN charges c ON c.charge_id=r.charge_id WHERE o.encounter_id=%(e)s
        UNION ALL SELECT c.service_code, r.report_date::date FROM radiology_results r JOIN radiology_orders o USING(rad_order_id)
          JOIN charges c ON c.charge_id=r.charge_id WHERE o.encounter_id=%(e)s
        UNION ALL SELECT c.service_code, p.performed_at::date FROM procedures_performed p JOIN procedure_orders o USING(proc_order_id)
          JOIN charges c ON c.charge_id=p.charge_id WHERE o.encounter_id=%(e)s
        UNION ALL SELECT c.service_code, k.consult_at::date FROM consultations k JOIN charges c ON c.charge_id=k.charge_id
          WHERE k.encounter_id=%(e)s
        UNION ALL SELECT c.service_code, d.created_at::date FROM dispenses d JOIN charges c ON c.charge_id=d.charge_id
          WHERE d.encounter_id=%(e)s
        UNION ALL SELECT c.service_code, c.created_at::date FROM room_stays s JOIN charges c ON c.charge_id=s.charge_id
          WHERE s.encounter_id=%(e)s""", {"e": encounter_id})
    return Counter((d["service_code"], d["day"]) for d in delivered)


def run_audit(conn, encounter_id: str) -> dict:
    """Pre-bill audit. BLOCK findings stop the bill; WARN findings are shown for review."""
    enc = encounter_for(conn, encounter_id)
    out: list[dict] = []
    if enc["status"] == "OPEN":
        out.append(finding("BLOCK", "NOT_DISCHARGED", "The doctor has not discharged / ended this visit yet."))
    if enc["status"] == "BILLED":
        return {"encounter_id": encounter_id, "passed": True, "findings": [], "billed": True}
    charges = active_charges(conn, encounter_id)
    if not charges:
        out.append(finding("BLOCK", "NO_CHARGES", "No delivered service has been charged."))
    if not one(conn, "SELECT 1 FROM prescriptions WHERE encounter_id=%s", (encounter_id,)) and \
            not applied_package(conn, encounter_id):
        out.append(finding("BLOCK", "NO_DIAGNOSIS", "No coded ICD-10 diagnosis on this visit (needed for claims and records)."))
    open_orders = one(conn, """SELECT
        (SELECT count(*) FROM lab_orders WHERE encounter_id=%(e)s AND status='ORDERED') +
        (SELECT count(*) FROM radiology_orders WHERE encounter_id=%(e)s AND status='ORDERED') +
        (SELECT count(*) FROM procedure_orders WHERE encounter_id=%(e)s AND status='ORDERED') +
        (SELECT count(*) FROM pharmacy_orders WHERE encounter_id=%(e)s AND status IN ('ORDERED','PARTIAL')) AS n""",
        {"e": encounter_id})["n"]
    if open_orders:
        out.append(finding("BLOCK", "OPEN_ORDERS", f"{open_orders} order(s) are not completed yet. Complete or cancel them."))
    # Charged more often than delivered on the same day -> duplicate or unsupported charge.
    delivered = completed_sources(conn, encounter_id)
    seen: Counter = Counter()
    for c in charges:
        if c["kind"] == "PACKAGE":
            continue
        key = (c["service_code"], c["created_at"].date())
        seen[key] += 1
        if seen[key] > delivered.get(key, 0):
            label = "Duplicate charge" if delivered.get(key, 0) else "Charge with no completed service"
            out.append(finding("BLOCK", "DUPLICATE_OR_UNSUPPORTED",
                               f"{label}: {c['description']} on {key[1]:%d %b}. Reverse it if it was posted in error.",
                               c["charge_id"]))
    for c in charges:
        if c["tax_category"] == "REVIEW":
            out.append(finding("BLOCK", "TAX_REVIEW", f"{c['description']} needs a GST classification.", c["charge_id"]))
    if enc["setting"] == "IPD" and not one(conn, "SELECT 1 FROM room_stays WHERE encounter_id=%s AND charge_id IS NOT NULL",
                                           (encounter_id,)):
        out.append(finding("BLOCK", "NO_BED_DAYS", "Inpatient visit without a charged ward stay."))
    cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (encounter_id,))
    if enc["payment_mode"] == "CASHLESS":
        if cov["eligibility_status"] != "VERIFIED":
            out.append(finding("BLOCK", "NOT_VERIFIED", "Insurance has not been verified for this visit."))
        approved = one(conn, """SELECT COALESCE(sum(approved_paise),0)::bigint AS n, count(*) AS c FROM preauths
            WHERE encounter_id=%s AND status='APPROVED'""", (encounter_id,))
        if cov["preauth_required"] and not approved["c"]:
            out.append(finding("BLOCK", "PREAUTH_MISSING", "Cashless admission needs an approved pre-authorisation."))
        elif cov["preauth_required"]:
            total = running_totals(conn, encounter_id)["total_paise"]
            payer_share = split_shares(enc, cov, total)[1]
            if payer_share > approved["n"]:
                out.append(finding("WARN", "PREAUTH_LIMIT",
                                   f"Insurer share ₹{payer_share/100:,.2f} exceeds the approved ₹{approved['n']/100:,.2f}. "
                                   "Request an enhancement, or the difference may become patient due."))
    if enc["payer_route"] == "PMJAY" and not applied_package(conn, encounter_id):
        out.append(finding("BLOCK", "PMJAY_PACKAGE", "PM-JAY visits are billed at a package rate. Apply the package."))
    return {"encounter_id": encounter_id, "passed": not any(f["severity"] == "BLOCK" for f in out), "findings": out}


def reverse_charge(conn, who: str, charge_id: int, reason: str) -> dict:
    charge = need(one(conn, "SELECT * FROM charges WHERE charge_id=%s FOR UPDATE", (charge_id,)), "Charge not found", 404)
    need(charge["charge_type"] == "CHARGE", "Only an original charge can be reversed")
    enc = encounter_for(conn, charge["encounter_id"], True)
    need(enc["status"] != "BILLED", "The bill is already final; corrections after billing need a credit note")
    need(not one(conn, "SELECT 1 FROM charges WHERE reverses_charge_id=%s", (charge_id,)),
         "This charge is already reversed or included in a package", 409)
    return offset_charge(conn, who, charge, "REVERSAL", reason.strip())


def apply_package(conn, who: str, encounter_id: str, package_code: str) -> dict:
    """Post the package price, then offset included services with PACKAGE_ADJ lines. Original prices stay visible."""
    enc = encounter_for(conn, encounter_id, True)
    need(enc["status"] in {"OPEN", "DISCHARGED"}, "A billed visit cannot receive a package")
    package = need(one(conn, "SELECT * FROM package_catalog WHERE package_code=%s", (package_code,)), "Package not found", 404)
    need(package["payer_route"] == enc["payer_route"], "This package is not offered for this payer")
    need(not applied_package(conn, encounter_id), "A package is already applied", 409)
    charge = create_charge(conn, who, encounter_id, package["service_code"], 1, f"PKG-{encounter_id}-{package_code}",
                           source_type="PACKAGE", source_id=package_code, allow_closed=True)["charge"]
    for c in active_charges(conn, encounter_id):
        if c["kind"] in package["included_kinds"]:
            offset_charge(conn, who, c, "PACKAGE_ADJ", f"Included in package {package_code}")
    audit(conn, who, "PACKAGE_APPLIED", "charges", charge["charge_id"], {"package_code": package_code})
    return {"package": package, "charge": charge}


def finalize_bill(conn, who: str, encounter_id: str) -> dict:
    enc = encounter_for(conn, encounter_id, True)
    need(enc["status"] != "BILLED", "This visit is already billed", 409)
    result = run_audit(conn, encounter_id)
    need(result["passed"], "Pre-bill audit has open findings: " +
         "; ".join(f["message"] for f in result["findings"] if f["severity"] == "BLOCK"))
    charges = rows(conn, "SELECT * FROM charges WHERE encounter_id=%s ORDER BY charge_id", (encounter_id,))
    totals = running_totals(conn, encounter_id)
    need(totals["total_paise"] >= 0, "Bill total cannot be negative")
    cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (encounter_id,))
    patient_share, payer_share = split_shares(enc, cov, totals["total_paise"])
    seq = one(conn, "SELECT nextval(pg_get_serial_sequence('invoices','invoice_id')) AS n")["n"]
    invoice = one(conn, """INSERT INTO invoices(invoice_id,encounter_id,invoice_no,subtotal_paise,tax_paise,total_paise,
        patient_share_paise,payer_share_paise,due_date) OVERRIDING SYSTEM VALUE
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (seq, encounter_id, f"SYN-{date.today().year}-{seq:05d}", totals["subtotal_paise"], totals["tax_paise"],
         totals["total_paise"], patient_share, payer_share, date.today() + timedelta(days=PATIENT_DUE_DAYS)))
    for n, c in enumerate(charges, 1):
        line_tax = tax_amount(c["subtotal_paise"], c["tax_rate_bps"])
        conn.execute("""INSERT INTO invoice_lines(invoice_id,line_no,charge_id,charge_type,description,department,quantity,
            unit_price_paise,taxable_paise,tax_category,tax_rate_bps,tax_paise,total_paise,hsn_sac)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (seq, n, c["charge_id"], c["charge_type"], c["description"], c["department"], c["quantity"],
             c["unit_price_paise"], c["subtotal_paise"], c["tax_category"], c["tax_rate_bps"], line_tax,
             c["subtotal_paise"] + line_tax, c["hsn_sac"]))
    conn.execute("UPDATE encounters SET status='BILLED' WHERE encounter_id=%s", (encounter_id,))
    audit(conn, who, "BILL_GENERATED", "invoices", seq, {"encounter_id": encounter_id, "total_paise": totals["total_paise"]})
    return invoice


def request_preauth(conn, who: str, data: PreauthIn) -> dict:
    need(data.request_type in {"INITIAL", "ENHANCEMENT"}, "Invalid request type")
    enc = encounter_for(conn, data.encounter_id, True)
    need(enc["status"] != "BILLED", "Pre-authorisation is requested before billing")
    need(enc["payment_mode"] == "CASHLESS" and enc["payer_route"] in {"PRIVATE", "PMJAY"},
         "Pre-authorisation applies to cashless insurance and PM-JAY")
    cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (data.encounter_id,))
    need(cov["eligibility_status"] == "VERIFIED", "Verify the insurance before requesting pre-authorisation")
    record = one(conn, """INSERT INTO preauths(encounter_id,coverage_id,request_type,requested_paise)
        VALUES (%s,%s,%s,%s) RETURNING *""", (data.encounter_id, cov["coverage_id"], data.request_type, data.requested_paise))
    audit(conn, who, "PREAUTH_REQUESTED", "preauths", record["preauth_id"])
    return record


def decide_preauth_core(conn, who: str, preauth_id: int, data: PreauthDecisionIn) -> dict:
    record = need(one(conn, "SELECT * FROM preauths WHERE preauth_id=%s FOR UPDATE", (preauth_id,)), "Pre-authorisation not found", 404)
    need(record["status"] == "SUBMITTED", "A decision is already recorded", 409)
    need(data.outcome in {"APPROVED", "REJECTED"}, "Outcome must be APPROVED or REJECTED")
    approved = (data.approved_paise or record["requested_paise"]) if data.outcome == "APPROVED" else 0
    need(approved <= record["requested_paise"], "Approval exceeds the request")
    updated = one(conn, """UPDATE preauths SET approved_paise=%s,status=%s,reference_no=%s,decided_at=now()
        WHERE preauth_id=%s RETURNING *""", (approved, data.outcome, data.reference_no or f"SYN-PA-{preauth_id}", preauth_id))
    audit(conn, who, f"PREAUTH_{data.outcome}", "preauths", preauth_id)
    return updated


# --- endpoints ------------------------------------------------------------

@router.get("/api/encounters/{encounter_id}/audit")
def pre_bill_audit(encounter_id: str):
    with db() as conn:
        return run_audit(conn, encounter_id)


@router.post("/api/charges/{charge_id}/reverse")
def reverse(charge_id: int, data: ReverseIn, request: Request):
    with db() as conn:
        return reverse_charge(conn, actor(request), charge_id, data.reason)


@router.post("/api/packages/apply")
def package_apply(data: PackageIn, request: Request):
    with db() as conn:
        return apply_package(conn, actor(request), data.encounter_id, data.package_code)


@router.post("/api/invoices")
def create_invoice(data: InvoiceIn, request: Request):
    with db() as conn:
        return finalize_bill(conn, actor(request), data.encounter_id)


@router.post("/api/preauth")
def submit_preauth(data: PreauthIn, request: Request):
    with db() as conn:
        return request_preauth(conn, actor(request), data)


@router.post("/api/preauth/{preauth_id}/decision")
def decide_preauth(preauth_id: int, data: PreauthDecisionIn, request: Request):
    with db() as conn:
        return decide_preauth_core(conn, actor(request), preauth_id, data)

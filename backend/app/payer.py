"""Payer channel: claims (approve / partial / reject / resubmit), shortfall, payments with failure and retry, reminders."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .core import (actor, audit, balance_for, db, deposits_available, encounter_for, need, notify, one, rows,
                   settle_if_paid)

router = APIRouter()
INSTANT_METHODS = {"CASH", "TRANSFER"}
PENDING_METHODS = {"UPI", "CARD", "GATEWAY"}


class ClaimIn(BaseModel):
    invoice_id: int
    discharge_summary: str = Field(default="Synthetic discharge summary for classroom demonstration", max_length=2000)
    documents: dict[str, bool] = Field(default_factory=lambda: {"itemised_bill": True, "discharge_summary": True})


class ClaimDecisionIn(BaseModel):
    outcome: str
    approved_paise: int = Field(default=0, ge=0)
    reason: str = Field(default="", max_length=300)
    reference_no: str = ""


class ResubmitIn(BaseModel):
    correction_note: str = Field(min_length=5, max_length=500)
    documents: dict[str, bool] = Field(default_factory=lambda: {"itemised_bill": True, "discharge_summary": True})


class ShortfallIn(BaseModel):
    action: str
    reason: str = Field(default="", max_length=300)


class ReceiptIn(BaseModel):
    invoice_id: int
    payer_kind: str
    amount_paise: int = Field(gt=0)
    method: str = "UPI"
    reference_no: str = ""


class OutcomeIn(BaseModel):
    outcome: str


class RetryIn(BaseModel):
    method: str


class RefundIn(BaseModel):
    encounter_id: str
    amount_paise: int = Field(gt=0)
    method: str = "UPI"
    reference_no: str = ""


def invoice_for(conn, invoice_id: int, lock: bool = False) -> dict:
    return need(one(conn, "SELECT * FROM invoices WHERE invoice_id=%s" + (" FOR UPDATE" if lock else ""), (invoice_id,)),
                "Bill not found", 404)


def latest_claim(conn, invoice_id: int) -> dict | None:
    return one(conn, "SELECT * FROM claims WHERE invoice_id=%s ORDER BY attempt_no DESC LIMIT 1", (invoice_id,))


def pending_total(conn, invoice_id: int, patient: bool) -> int:
    op = "=" if patient else "<>"
    return one(conn, f"""SELECT COALESCE(sum(amount_paise),0)::bigint AS n FROM receipts
        WHERE invoice_id=%s AND status='PENDING' AND payer_kind{op}'PATIENT'""", (invoice_id,))["n"]


# --- claims ---------------------------------------------------------------

def _claim_codes(conn, encounter_id: str) -> tuple[str, str]:
    rx = need(one(conn, "SELECT icd_code FROM prescriptions WHERE encounter_id=%s ORDER BY prescription_id DESC LIMIT 1",
                  (encounter_id,)), "A coded diagnosis is needed for the claim")
    procs = rows(conn, """SELECT p.snomed_code FROM procedures_performed p JOIN procedure_orders o USING(proc_order_id)
        WHERE o.encounter_id=%s""", (encounter_id,))
    return rx["icd_code"], ",".join(p["snomed_code"] for p in procs)


def submit_claim_core(conn, who: str, data: ClaimIn, *, attempt: int = 1, parent: dict | None = None) -> dict:
    invoice = invoice_for(conn, data.invoice_id, True)
    enc = encounter_for(conn, invoice["encounter_id"])
    need(enc["payment_mode"] == "CASHLESS", "Only cashless visits are claimed by the hospital")
    need(data.documents.get("itemised_bill") and data.documents.get("discharge_summary"),
         "Attach the itemised bill and discharge summary")
    need(len(data.discharge_summary.strip()) >= 10, "Add a discharge summary")
    prior = latest_claim(conn, data.invoice_id)
    if attempt == 1:
        need(not prior, "A claim already exists for this bill; resubmit the rejected one instead", 409)
    need(not prior or prior["status"] != "SUBMITTED", "A claim for this bill is still awaiting a decision", 409)
    balance = balance_for(conn, invoice)
    amount = balance["payer_due_paise"] - pending_total(conn, invoice["invoice_id"], patient=False)
    need(amount > 0, "Nothing remains to claim from the payer")
    cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (enc["encounter_id"],))
    pre = one(conn, """SELECT * FROM preauths WHERE encounter_id=%s AND status='APPROVED' ORDER BY preauth_id DESC LIMIT 1""",
              (enc["encounter_id"],))
    if cov["preauth_required"]:
        need(pre, "An approved pre-authorisation is required")
    icd, procedure = _claim_codes(conn, enc["encounter_id"])
    claim = one(conn, """INSERT INTO claims(invoice_id,attempt_no,parent_claim_id,coverage_id,preauth_id,submitted_paise,
        diagnosis_code,procedure_code,discharge_summary,documents) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (invoice["invoice_id"], attempt, parent["claim_id"] if parent else None, cov["coverage_id"],
         pre["preauth_id"] if pre else None, amount, icd, procedure, data.discharge_summary.strip(), Jsonb(data.documents)))
    audit(conn, who, "CLAIM_SUBMITTED" if attempt == 1 else "CLAIM_RESUBMITTED", "claims", claim["claim_id"],
          {"invoice_id": invoice["invoice_id"], "attempt": attempt})
    return claim


def decide_claim_core(conn, who: str, claim_id: int, data: ClaimDecisionIn) -> dict:
    claim = need(one(conn, "SELECT * FROM claims WHERE claim_id=%s FOR UPDATE", (claim_id,)), "Claim not found", 404)
    need(claim["status"] == "SUBMITTED", "This claim already has a decision", 409)
    need(data.outcome in {"APPROVED", "PARTIAL", "REJECTED"}, "Outcome must be APPROVED, PARTIAL or REJECTED")
    if data.outcome == "APPROVED":
        approved = claim["submitted_paise"]
    elif data.outcome == "PARTIAL":
        approved = data.approved_paise
        need(0 < approved < claim["submitted_paise"], "A partial approval must be more than 0 and less than the claim")
        need(data.reason.strip(), "Give the reason for the deduction")
    else:
        approved = 0
        need(data.reason.strip(), "Give the rejection reason")
    updated = one(conn, """UPDATE claims SET status=%s,approved_paise=%s,rejection_reason=%s,reference_no=%s,decided_at=now()
        WHERE claim_id=%s RETURNING *""",
        (data.outcome, approved, data.reason.strip(), data.reference_no or f"SYN-CLM-{claim_id}", claim_id))
    audit(conn, who, f"CLAIM_{data.outcome}", "claims", claim_id, {"approved_paise": approved, "reason": data.reason})
    invoice = invoice_for(conn, claim["invoice_id"])
    enc = encounter_for(conn, invoice["encounter_id"])
    message = {"APPROVED": f"Your insurer approved the claim for bill {invoice['invoice_no']}.",
               "PARTIAL": f"Your insurer approved part of the claim for bill {invoice['invoice_no']}: {data.reason.strip()}",
               "REJECTED": f"Your insurer rejected the claim for bill {invoice['invoice_no']}: {data.reason.strip()}"}[data.outcome]
    notify(conn, who, enc["patient_id"], "CLAIM", message, encounter_id=enc["encounter_id"], invoice_id=invoice["invoice_id"])
    return updated


def resubmit_claim(conn, who: str, claim_id: int, data: ResubmitIn) -> dict:
    claim = need(one(conn, "SELECT * FROM claims WHERE claim_id=%s FOR UPDATE", (claim_id,)), "Claim not found", 404)
    latest = latest_claim(conn, claim["invoice_id"])
    need(latest["claim_id"] == claim_id and claim["status"] == "REJECTED", "Only the latest rejected claim can be resubmitted")
    summary = f"{claim['discharge_summary']}\nCorrection: {data.correction_note.strip()}"
    return submit_claim_core(conn, who, ClaimIn(invoice_id=claim["invoice_id"], discharge_summary=summary,
                                                documents=data.documents), attempt=claim["attempt_no"] + 1, parent=claim)


def move_shortfall(conn, who: str, invoice_id: int, data: ShortfallIn) -> dict:
    """What the insurer will not pay goes to the patient (self-pay path) or is written off."""
    need(data.action in {"TO_PATIENT", "WRITE_OFF"}, "Choose TO_PATIENT or WRITE_OFF")
    invoice = invoice_for(conn, invoice_id, True)
    enc = encounter_for(conn, invoice["encounter_id"])
    claim = need(latest_claim(conn, invoice_id), "Submit a claim first")
    need(claim["status"] in {"PARTIAL", "REJECTED"}, "Only a partial or rejected claim leaves a shortfall")
    if enc["payer_route"] == "PMJAY":
        need(data.action == "WRITE_OFF", "PM-JAY beneficiaries cannot be charged; the hospital writes off the shortfall")
    balance = balance_for(conn, invoice)
    expected = claim["approved_paise"] if claim["status"] == "PARTIAL" else balance["payer_received_paise"]
    amount = balance["payer_share_paise"] - expected
    need(amount > 0, "There is no shortfall to move")
    row = one(conn, """INSERT INTO balance_adjustments(invoice_id,claim_id,kind,amount_paise,reason,created_by)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (invoice_id, claim["claim_id"], data.action, amount,
         data.reason.strip() or ("Claim shortfall billed to patient" if data.action == "TO_PATIENT" else "Claim shortfall written off"),
         who))
    audit(conn, who, f"SHORTFALL_{data.action}", "balance_adjustments", row["adjustment_id"], {"amount_paise": amount})
    settle_if_paid(conn, who, invoice)
    return row


# --- payments -------------------------------------------------------------

def record_receipt(conn, who: str, data: ReceiptIn, *, retry_of: dict | None = None) -> dict:
    need(data.payer_kind in {"PATIENT", "INSURER", "SCHEME", "CORPORATE"}, "Invalid payer kind")
    invoice = invoice_for(conn, data.invoice_id, True)
    enc = encounter_for(conn, invoice["encounter_id"])
    balance = balance_for(conn, invoice)
    if data.payer_kind == "PATIENT":
        need(data.method in {"CASH", "UPI", "CARD", "GATEWAY"}, "Choose cash, UPI, card or gateway")
        need(enc["payer_route"] != "PMJAY", "PM-JAY beneficiaries are not charged")
        due = balance["patient_due_paise"] - pending_total(conn, invoice["invoice_id"], patient=True)
        need(data.amount_paise <= due, "Payment exceeds what the patient owes")
    else:
        claim = need(latest_claim(conn, invoice["invoice_id"]), "Submit a payer claim first")
        need(claim["status"] in {"APPROVED", "PARTIAL"}, "The insurer pays only after the claim is approved")
        open_amount = claim["approved_paise"] - balance["payer_received_paise"] - pending_total(conn, invoice["invoice_id"], patient=False)
        need(data.amount_paise <= open_amount, "Payment exceeds the approved claim still unpaid")
    status = "SUCCEEDED" if data.method in INSTANT_METHODS else "PENDING"
    record = one(conn, """INSERT INTO receipts(invoice_id,payer_kind,amount_paise,method,reference_no,status,attempt_no,retry_of,
        settled_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (data.invoice_id, data.payer_kind, data.amount_paise, data.method, data.reference_no, status,
         (retry_of["attempt_no"] + 1) if retry_of else 1, retry_of["receipt_id"] if retry_of else None,
         None))
    if status == "SUCCEEDED":
        conn.execute("UPDATE receipts SET settled_at=now() WHERE receipt_id=%s", (record["receipt_id"],))
    audit(conn, who, "PAYMENT_STARTED" if status == "PENDING" else "PAYMENT_RECEIVED", "receipts", record["receipt_id"],
          {"method": data.method, "amount_paise": data.amount_paise})
    if status == "SUCCEEDED":
        settle_if_paid(conn, who, invoice)
    return one(conn, "SELECT * FROM receipts WHERE receipt_id=%s", (record["receipt_id"],))


def payment_outcome(conn, who: str, receipt_id: int, outcome: str) -> dict:
    need(outcome in {"SUCCEEDED", "FAILED", "TIMEOUT"}, "Outcome must be SUCCEEDED, FAILED or TIMEOUT")
    receipt = need(one(conn, "SELECT * FROM receipts WHERE receipt_id=%s FOR UPDATE", (receipt_id,)), "Payment not found", 404)
    need(receipt["status"] == "PENDING", "This payment already has an outcome", 409)
    updated = one(conn, """UPDATE receipts SET status=%s,settled_at=CASE WHEN %s='SUCCEEDED' THEN now() END
        WHERE receipt_id=%s RETURNING *""", (outcome, outcome, receipt_id))
    audit(conn, who, f"PAYMENT_{outcome}", "receipts", receipt_id)
    if outcome == "SUCCEEDED":
        settle_if_paid(conn, who, invoice_for(conn, receipt["invoice_id"]))
    return updated


def retry_payment(conn, who: str, receipt_id: int, method: str) -> dict:
    receipt = need(one(conn, "SELECT * FROM receipts WHERE receipt_id=%s", (receipt_id,)), "Payment not found", 404)
    need(receipt["status"] in {"FAILED", "TIMEOUT"}, "Only a failed or timed-out payment can be retried")
    need(not one(conn, "SELECT 1 FROM receipts WHERE retry_of=%s", (receipt_id,)), "This payment was already retried", 409)
    return record_receipt(conn, who, ReceiptIn(invoice_id=receipt["invoice_id"], payer_kind=receipt["payer_kind"],
                                               amount_paise=receipt["amount_paise"], method=method,
                                               reference_no=receipt["reference_no"]), retry_of=receipt)


def send_reminder(conn, who: str, invoice_id: int) -> dict:
    invoice = invoice_for(conn, invoice_id)
    balance = balance_for(conn, invoice)
    need(balance["remaining_paise"] > 0, "Nothing is outstanding on this bill")
    enc = encounter_for(conn, invoice["encounter_id"])
    parts = []
    if balance["patient_due_paise"]:
        parts.append(f"₹{balance['patient_due_paise']/100:,.2f} due from you by {invoice['due_date']:%d %b %Y}")
    if balance["payer_due_paise"]:
        parts.append(f"₹{balance['payer_due_paise']/100:,.2f} awaited from your insurer")
    return notify(conn, who, enc["patient_id"], "REMINDER", f"Bill {invoice['invoice_no']}: " + "; ".join(parts) + ".",
                  encounter_id=enc["encounter_id"], invoice_id=invoice_id)


def refund_core(conn, who: str, data: RefundIn) -> dict:
    enc = encounter_for(conn, data.encounter_id, True)
    invoice = need(one(conn, "SELECT * FROM invoices WHERE encounter_id=%s", (data.encounter_id,)),
                   "Refunds of unused deposit are made after the bill")
    used = balance_for(conn, invoice)["deposit_used_paise"]
    unused = deposits_available(conn, data.encounter_id) - used
    need(data.amount_paise <= unused, "Refund exceeds the unused deposit")
    record = one(conn, """INSERT INTO refunds(encounter_id,amount_paise,method,reference_no) VALUES (%s,%s,%s,%s) RETURNING *""",
                 (data.encounter_id, data.amount_paise, data.method, data.reference_no))
    audit(conn, who, "DEPOSIT_REFUNDED", "refunds", record["refund_id"], {"encounter_id": enc["encounter_id"]})
    return record


# --- endpoints ------------------------------------------------------------

@router.post("/api/claims")
def submit_claim(data: ClaimIn, request: Request):
    with db() as conn:
        return submit_claim_core(conn, actor(request), data)


@router.post("/api/claims/{claim_id}/decision")
def decide_claim(claim_id: int, data: ClaimDecisionIn, request: Request):
    with db() as conn:
        return decide_claim_core(conn, actor(request), claim_id, data)


@router.post("/api/claims/{claim_id}/resubmit")
def resubmit(claim_id: int, data: ResubmitIn, request: Request):
    with db() as conn:
        return resubmit_claim(conn, actor(request), claim_id, data)


@router.post("/api/invoices/{invoice_id}/shortfall")
def shortfall(invoice_id: int, data: ShortfallIn, request: Request):
    with db() as conn:
        return move_shortfall(conn, actor(request), invoice_id, data)


@router.post("/api/receipts")
def add_receipt(data: ReceiptIn, request: Request):
    with db() as conn:
        return record_receipt(conn, actor(request), data)


@router.post("/api/receipts/{receipt_id}/outcome")
def receipt_outcome(receipt_id: int, data: OutcomeIn, request: Request):
    with db() as conn:
        return payment_outcome(conn, actor(request), receipt_id, data.outcome)


@router.post("/api/receipts/{receipt_id}/retry")
def receipt_retry(receipt_id: int, data: RetryIn, request: Request):
    with db() as conn:
        return retry_payment(conn, actor(request), receipt_id, data.method)


@router.post("/api/invoices/{invoice_id}/remind")
def remind(invoice_id: int, request: Request):
    with db() as conn:
        return send_reminder(conn, actor(request), invoice_id)


@router.post("/api/refunds")
def add_refund(data: RefundIn, request: Request):
    with db() as conn:
        return refund_core(conn, actor(request), data)

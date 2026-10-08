"""Reception desk: registration (ABHA), insurance policy and verification, appointment, check-in, deposit."""

from __future__ import annotations

from datetime import date, datetime
import re

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .core import actor, audit, db, encounter_for, need, notify, one, rows

router = APIRouter()
ABHA_PATTERN = re.compile(r"\d{2}-?\d{4}-?\d{4}-?\d{4}")


class PatientIn(BaseModel):
    display_label: str = Field(min_length=2, max_length=80)
    dob: date
    sex: str = Field(default="", max_length=20)
    contact_masked: str = Field(default="", max_length=20)
    city: str = Field(default="", max_length=60)
    blood_group: str = Field(default="", max_length=5)
    allergies: str = Field(default="", max_length=200)
    history_summary: str = Field(default="", max_length=600)
    abha_number: str = Field(default="", max_length=17)
    abha_address: str = Field(default="", max_length=60)


class PolicyIn(BaseModel):
    payer_route: str
    provider_name: str = Field(min_length=2, max_length=80)
    policy_no: str = Field(min_length=3, max_length=40)
    coverage_type: str = "INDIVIDUAL"
    valid_from: date
    valid_to: date
    coverage_amount_paise: int = Field(ge=0)
    nominee: str = Field(default="", max_length=80)
    copay_percent: int = Field(default=0, ge=0, le=100)


class AppointmentIn(BaseModel):
    patient_id: str
    doctor_id: str
    slot_at: datetime
    reason: str = Field(default="", max_length=200)


class CheckInIn(BaseModel):
    setting: str = "OPD"
    payment_mode: str = "SELF"
    policy_id: str = ""


class WalkInIn(CheckInIn):
    patient_id: str
    doctor_id: str = ""


class AdvanceIn(BaseModel):
    encounter_id: str
    amount_paise: int = Field(gt=0)
    method: str = "UPI"
    reference_no: str = ""


# --- core functions (also used by the seed data) ---------------------------

def register_patient(conn, who: str, data: PatientIn, patient_id: str | None = None) -> dict:
    need(data.dob <= date.today(), "Date of birth cannot be in the future")
    abha = data.abha_number.strip()
    if abha:
        need(ABHA_PATTERN.fullmatch(abha), "ABHA number must have 14 digits (XX-XXXX-XXXX-XXXX)")
        digits = re.sub(r"\D", "", abha)
        abha = f"{digits[:2]}-{digits[2:6]}-{digits[6:10]}-{digits[10:]}"
        need(not one(conn, "SELECT 1 FROM patients WHERE abha_number=%s", (abha,)),
             "A patient with this ABHA number is already registered", 409)
    seq = one(conn, "SELECT count(*)+1 AS n FROM patients")["n"]
    pid = patient_id or f"P-{seq:04d}"
    while one(conn, "SELECT 1 FROM patients WHERE patient_id=%s", (pid,)):
        seq += 1
        pid = f"P-{seq:04d}"
    mrn = f"MRN-{date.today().year}-{seq:05d}"
    patient = one(conn, """INSERT INTO patients(patient_id,mrn,display_label,dob,sex,blood_group,contact_masked,city,
        allergies,history_summary,abha_number,abha_address) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (pid, mrn, data.display_label.strip(), data.dob, data.sex, data.blood_group, data.contact_masked, data.city,
         data.allergies, data.history_summary, abha or None, data.abha_address.strip() or None))
    audit(conn, who, "PATIENT_REGISTERED", "patients", pid, {"mrn": mrn, "abha": bool(abha)})
    return patient


def add_policy(conn, who: str, patient_id: str, data: PolicyIn, policy_id: str | None = None) -> dict:
    need(data.payer_route in {"PRIVATE", "PMJAY", "CGHS", "CORPORATE"}, "Choose a payer route for the policy")
    need(data.valid_to >= data.valid_from, "Policy end date is before its start date")
    need(one(conn, "SELECT 1 FROM patients WHERE patient_id=%s", (patient_id,)), "Patient not found", 404)
    seq = one(conn, "SELECT count(*)+1 AS n FROM insurance_policies")["n"]
    policy = one(conn, """INSERT INTO insurance_policies(policy_id,patient_id,payer_route,provider_name,policy_no,
        coverage_type,valid_from,valid_to,coverage_amount_paise,nominee,copay_bps)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (policy_id or f"POL-{seq:04d}", patient_id, data.payer_route, data.provider_name.strip(), data.policy_no.strip(),
         data.coverage_type, data.valid_from, data.valid_to, data.coverage_amount_paise, data.nominee,
         data.copay_percent * 100))
    audit(conn, who, "POLICY_ADDED", "insurance_policies", policy["policy_id"], {"patient_id": patient_id})
    return policy


def book_appointment(conn, who: str, data: AppointmentIn) -> dict:
    patient = need(one(conn, "SELECT * FROM patients WHERE patient_id=%s", (data.patient_id,)), "Patient not found", 404)
    doctor = need(one(conn, "SELECT * FROM doctors WHERE doctor_id=%s", (data.doctor_id,)), "Doctor not found", 404)
    appt = one(conn, """INSERT INTO appointments(patient_id,doctor_id,slot_at,reason) VALUES (%s,%s,%s,%s) RETURNING *""",
               (data.patient_id, data.doctor_id, data.slot_at, data.reason.strip()))
    audit(conn, who, "APPOINTMENT_BOOKED", "appointments", appt["appointment_id"], {"patient_id": data.patient_id})
    notify(conn, who, patient["patient_id"], "APPOINTMENT",
           f"Appointment with {doctor['name']} on {data.slot_at:%d %b %Y at %H:%M}.", appointment_id=appt["appointment_id"])
    return appt


def open_visit(conn, who: str, patient_id: str, data: CheckInIn, *, doctor_id: str | None = None,
               appointment_id: int | None = None, encounter_id: str | None = None) -> dict:
    """Creates the Registration (encounter) and the coverage used for it."""
    need(data.setting in {"OPD", "EMERGENCY", "DAY_CARE"},
         "Check in as OPD, emergency or day care; the doctor admits a patient to IPD")
    need(data.payment_mode in {"SELF", "CASHLESS", "REIMBURSEMENT"}, "Choose self-pay, cashless or reimbursement")
    patient = need(one(conn, "SELECT * FROM patients WHERE patient_id=%s FOR UPDATE", (patient_id,)), "Patient not found", 404)
    need(not one(conn, "SELECT 1 FROM encounters WHERE patient_id=%s AND status IN ('OPEN','DISCHARGED')", (patient_id,)),
         "This patient already has an active visit", 409)
    policy = None
    if data.payment_mode in {"CASHLESS", "REIMBURSEMENT"}:
        policy = need(one(conn, "SELECT * FROM insurance_policies WHERE policy_id=%s AND patient_id=%s",
                          (data.policy_id, patient_id)), "Choose one of the patient's insurance policies")
    if data.payment_mode == "CASHLESS":
        route, label, copay = policy["payer_route"], policy["provider_name"], policy["copay_bps"]
    else:
        route, label, copay = "SELF", "Self pay", 0
    seq = one(conn, "SELECT count(*)+1 AS n FROM encounters")["n"]
    eid = encounter_id or f"E-{date.today():%y%m%d}-{seq:04d}"
    enc = one(conn, """INSERT INTO encounters(encounter_id,patient_id,doctor_id,appointment_id,policy_id,setting,
        payment_mode,payer_route,payer_label,bill_to_gstin) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (eid, patient_id, doctor_id or None, appointment_id, policy["policy_id"] if policy else None, data.setting,
         data.payment_mode, route, label, "29ABCDE1234F1Z5" if route == "CORPORATE" else ""))
    one(conn, """INSERT INTO coverages(coverage_id,encounter_id,policy_id,payer_route,payer_label,member_ref,copay_bps)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING coverage_id""",
        (f"C-{eid}", eid, policy["policy_id"] if policy and data.payment_mode == "CASHLESS" else None, route, label,
         policy["policy_no"] if policy else "", copay))
    audit(conn, who, "VISIT_OPENED", "encounters", eid,
          {"patient_id": patient["patient_id"], "setting": data.setting, "payment_mode": data.payment_mode})
    return enc


def verify_coverage_core(conn, who: str, encounter_id: str) -> dict:
    enc = encounter_for(conn, encounter_id, True)
    need(enc["payment_mode"] == "CASHLESS", "Self-pay and reimbursement visits have nothing to verify at the hospital")
    cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", (encounter_id,))
    policy = need(one(conn, "SELECT * FROM insurance_policies WHERE policy_id=%s", (cov["policy_id"],)), "No policy on this visit")
    today = date.today()
    ok = policy["valid_from"] <= today <= policy["valid_to"] and policy["coverage_amount_paise"] > 0
    status = "VERIFIED" if ok else "NOT_ELIGIBLE"
    updated = one(conn, """UPDATE coverages SET eligibility_status=%s,verified_at=now(),member_ref=%s
        WHERE encounter_id=%s RETURNING *""", (status, policy["policy_no"], encounter_id))
    audit(conn, who, "COVERAGE_VERIFIED_SIMULATED", "coverages", updated["coverage_id"], {"result": status})
    return updated


def take_deposit(conn, who: str, data: AdvanceIn) -> dict:
    enc = encounter_for(conn, data.encounter_id, True)
    need(enc["status"] == "OPEN", "Deposits are taken while the visit is open")
    need(enc["payer_route"] != "PMJAY", "PM-JAY beneficiaries are not charged a deposit")
    need(data.method in {"UPI", "CASH", "CARD"}, "Choose UPI, cash or card")
    record = one(conn, """INSERT INTO advances(encounter_id,amount_paise,method,reference_no,received_by)
        VALUES (%s,%s,%s,%s,%s) RETURNING *""", (data.encounter_id, data.amount_paise, data.method, data.reference_no, who))
    audit(conn, who, "DEPOSIT_RECEIVED", "advances", record["advance_id"], {"encounter_id": data.encounter_id})
    return record


# --- endpoints -------------------------------------------------------------

@router.post("/api/patients")
def create_patient(data: PatientIn, request: Request):
    with db() as conn:
        return register_patient(conn, actor(request), data)


@router.post("/api/patients/{patient_id}/policies")
def create_policy(patient_id: str, data: PolicyIn, request: Request):
    with db() as conn:
        return add_policy(conn, actor(request), patient_id, data)


@router.post("/api/appointments")
def create_appointment(data: AppointmentIn, request: Request):
    with db() as conn:
        return book_appointment(conn, actor(request), data)


@router.post("/api/appointments/{appointment_id}/check-in")
def check_in(appointment_id: int, data: CheckInIn, request: Request):
    with db() as conn:
        appt = need(one(conn, "SELECT * FROM appointments WHERE appointment_id=%s FOR UPDATE", (appointment_id,)),
                    "Appointment not found", 404)
        need(appt["status"] == "BOOKED", "This appointment is already checked in or cancelled", 409)
        enc = open_visit(conn, actor(request), appt["patient_id"], data, doctor_id=appt["doctor_id"],
                         appointment_id=appointment_id)
        conn.execute("UPDATE appointments SET status='CHECKED_IN',encounter_id=%s WHERE appointment_id=%s",
                     (enc["encounter_id"], appointment_id))
        audit(conn, actor(request), "APPOINTMENT_CHECKED_IN", "appointments", appointment_id)
        return enc


@router.post("/api/encounters")
def walk_in(data: WalkInIn, request: Request):
    with db() as conn:
        return open_visit(conn, actor(request), data.patient_id, data, doctor_id=data.doctor_id or None)


@router.post("/api/coverage/{encounter_id}/verify")
def verify_coverage(encounter_id: str, request: Request):
    with db() as conn:
        return verify_coverage_core(conn, actor(request), encounter_id)


@router.post("/api/advances")
def add_advance(data: AdvanceIn, request: Request):
    with db() as conn:
        return take_deposit(conn, actor(request), data)


@router.get("/api/appointments")
def appointment_list():
    with db() as conn:
        return {"appointments": rows(conn, """SELECT a.*,p.display_label AS patient_label,d.name AS doctor_name
            FROM appointments a JOIN patients p USING(patient_id) JOIN doctors d USING(doctor_id)
            ORDER BY a.slot_at DESC LIMIT 100""")}

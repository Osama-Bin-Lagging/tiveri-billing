"""Doctor, Diagnostics (lab + radiology) and Pharmacy desks. Each completed service posts its own charge."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .core import actor, audit, create_charge, db, encounter_for, need, one, rows, tax_for

router = APIRouter()


class ConsultationIn(BaseModel):
    encounter_id: str
    notes: str = Field(min_length=10, max_length=2000)


class RadiologyLine(BaseModel):
    service_code: str
    clinical_notes: str = Field(default="", max_length=300)


class MedicineLine(BaseModel):
    item_code: str
    quantity: int = Field(ge=1, le=100)
    instruction: str = Field(default="", max_length=300)


class AdmitIn(BaseModel):
    ward_id: str


class PrescriptionIn(BaseModel):
    encounter_id: str
    icd_code: str
    notes: str = Field(default="", max_length=600)
    labs: list[str] = []
    radiology: list[RadiologyLine] = []
    procedures: list[str] = []
    medicines: list[MedicineLine] = []
    admit: AdmitIn | None = None


class PerformIn(BaseModel):
    outcome_notes: str = Field(default="Completed without complications.", max_length=600)


class LabResultIn(BaseModel):
    result_value: float = Field(gt=0, lt=100000)


class RadiologyReportIn(BaseModel):
    findings: str = Field(min_length=5, max_length=1000)


class DispenseIn(BaseModel):
    pharm_order_id: int
    quantity: int = Field(ge=1, le=100)
    source_event_id: str = Field(min_length=3, max_length=100)


class CancelOrderIn(BaseModel):
    kind: str
    order_id: int
    reason: str = Field(min_length=3, max_length=200)


ORDER_TABLES = {"LAB": ("lab_orders", "lab_order_id", "ORDERED"),
                "RADIOLOGY": ("radiology_orders", "rad_order_id", "ORDERED"),
                "PROCEDURE": ("procedure_orders", "proc_order_id", "ORDERED"),
                "PHARMACY": ("pharmacy_orders", "pharm_order_id", "ORDERED")}


class HisEventIn(BaseModel):
    encounter_id: str
    service_code: str
    quantity: int = Field(ge=1, le=1000)
    source_event_id: str = Field(min_length=3, max_length=100)


def doctor_of(conn, who: str) -> str:
    staff = one(conn, "SELECT doctor_id FROM staff_users WHERE username=%s", (who,))
    if staff and staff["doctor_id"]:
        return staff["doctor_id"]
    return one(conn, "SELECT doctor_id FROM doctors ORDER BY doctor_id LIMIT 1")["doctor_id"]


# --- doctor ---------------------------------------------------------------

def consult(conn, who: str, data: ConsultationIn) -> dict:
    enc = encounter_for(conn, data.encounter_id, True)
    need(enc["status"] == "OPEN", "The visit is closed")
    doctor = one(conn, "SELECT * FROM doctors WHERE doctor_id=%s", (doctor_of(conn, who),))
    record = one(conn, """INSERT INTO consultations(encounter_id,doctor_id,notes) VALUES (%s,%s,%s) RETURNING *""",
                 (data.encounter_id, doctor["doctor_id"], data.notes.strip()))
    charge = create_charge(conn, who, data.encounter_id, doctor["consult_service_code"], 1,
                           f"CONSULT-{record['consult_id']}", source_type="CONSULTATION",
                           source_id=str(record["consult_id"]))["charge"]
    record = one(conn, "UPDATE consultations SET charge_id=%s WHERE consult_id=%s RETURNING *",
                 (charge["charge_id"], record["consult_id"]))
    if not enc["doctor_id"]:
        conn.execute("UPDATE encounters SET doctor_id=%s WHERE encounter_id=%s", (doctor["doctor_id"], data.encounter_id))
    audit(conn, who, "CONSULTATION_RECORDED", "consultations", record["consult_id"], {"encounter_id": data.encounter_id})
    return {"consultation": record, "charge": charge}


def prescribe(conn, who: str, data: PrescriptionIn) -> dict:
    """One prescription header (coded diagnosis) with any mix of orders; optional admission."""
    enc = encounter_for(conn, data.encounter_id, True)
    need(enc["status"] == "OPEN", "The visit is closed")
    consultation = need(one(conn, """SELECT * FROM consultations WHERE encounter_id=%s ORDER BY consult_id DESC LIMIT 1""",
                            (data.encounter_id,)), "Record the consultation before prescribing")
    dx = need(one(conn, "SELECT * FROM diagnosis_catalog WHERE icd_code=%s", (data.icd_code,)),
              "Pick a diagnosis from the ICD-10 list")
    need(data.labs or data.radiology or data.procedures or data.medicines or data.admit,
         "Add at least one order, medicine or admission")
    doctor_id = doctor_of(conn, who)
    rx = one(conn, """INSERT INTO prescriptions(encounter_id,consult_id,doctor_id,icd_code,snomed_code,notes)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (data.encounter_id, consultation["consult_id"], doctor_id, dx["icd_code"], dx["snomed_code"], data.notes.strip()))
    pid = rx["prescription_id"]
    result = {"prescription": rx, "lab_orders": [], "radiology_orders": [], "procedure_orders": [], "pharmacy_orders": []}
    for code in data.labs:
        need(one(conn, "SELECT 1 FROM lab_catalog WHERE service_code=%s", (code,)), f"Unknown lab test {code}")
        result["lab_orders"].append(one(conn, """INSERT INTO lab_orders(prescription_id,encounter_id,service_code)
            VALUES (%s,%s,%s) RETURNING *""", (pid, data.encounter_id, code)))
    for line in data.radiology:
        study = need(one(conn, "SELECT * FROM radiology_catalog WHERE service_code=%s", (line.service_code,)),
                     f"Unknown radiology study {line.service_code}")
        result["radiology_orders"].append(one(conn, """INSERT INTO radiology_orders(prescription_id,encounter_id,
            service_code,modality,clinical_notes) VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (pid, data.encounter_id, line.service_code, study["modality"], line.clinical_notes.strip())))
    for code in data.procedures:
        proc = need(one(conn, "SELECT * FROM procedure_catalog WHERE service_code=%s", (code,)), f"Unknown procedure {code}")
        result["procedure_orders"].append(one(conn, """INSERT INTO procedure_orders(prescription_id,encounter_id,
            service_code,snomed_code,outsourced) VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (pid, data.encounter_id, code, proc["snomed_code"], proc["outsourced"])))
    for med in data.medicines:
        need(one(conn, "SELECT 1 FROM pharmacy_items WHERE item_code=%s", (med.item_code,)), f"Unknown medicine {med.item_code}")
        result["pharmacy_orders"].append(one(conn, """INSERT INTO pharmacy_orders(prescription_id,encounter_id,item_code,
            quantity,instruction) VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (pid, data.encounter_id, med.item_code, med.quantity, med.instruction.strip())))
    if data.admit:
        result["room_stay"] = admit(conn, who, data.encounter_id, data.admit.ward_id)
    audit(conn, who, "PRESCRIPTION_CREATED", "prescriptions", pid,
          {"encounter_id": data.encounter_id, "icd_code": dx["icd_code"], "orders":
           sum(len(result[k]) for k in ("lab_orders", "radiology_orders", "procedure_orders", "pharmacy_orders"))})
    return result


def admit(conn, who: str, encounter_id: str, ward_id: str, start: date | None = None) -> dict:
    """ER: Registration 'admits' Ward. The bed-day charge is posted at discharge."""
    enc = encounter_for(conn, encounter_id, True)
    need(enc["status"] == "OPEN", "The visit is closed")
    need(not one(conn, "SELECT 1 FROM room_stays WHERE encounter_id=%s AND end_date IS NULL", (encounter_id,)),
         "The patient is already admitted", 409)
    need(one(conn, "SELECT 1 FROM wards WHERE ward_id=%s", (ward_id,)), "Ward not found", 404)
    stay = one(conn, """INSERT INTO room_stays(encounter_id,ward_id,start_date) VALUES (%s,%s,%s) RETURNING *""",
               (encounter_id, ward_id, start or date.today()))
    conn.execute("UPDATE encounters SET setting='IPD' WHERE encounter_id=%s", (encounter_id,))
    if enc["payment_mode"] == "CASHLESS" and enc["payer_route"] in {"PRIVATE", "PMJAY"}:
        conn.execute("UPDATE coverages SET preauth_required=true WHERE encounter_id=%s", (encounter_id,))
    audit(conn, who, "PATIENT_ADMITTED", "room_stays", stay["room_stay_id"], {"encounter_id": encounter_id, "ward_id": ward_id})
    return stay


def perform_procedure(conn, who: str, proc_order_id: int, data: PerformIn) -> dict:
    order = need(one(conn, "SELECT * FROM procedure_orders WHERE proc_order_id=%s FOR UPDATE", (proc_order_id,)),
                 "Procedure order not found", 404)
    if order["status"] == "PERFORMED":
        done = one(conn, "SELECT * FROM procedures_performed WHERE proc_order_id=%s", (proc_order_id,))
        return {"performed": done, "duplicate": True}
    need(order["status"] == "ORDERED", "This procedure order is cancelled")
    charge = create_charge(conn, who, order["encounter_id"], order["service_code"], 1, f"PROC-{proc_order_id}",
                           source_type="PROCEDURE", source_id=str(proc_order_id))["charge"]
    note = data.outcome_notes.strip()
    if order["outsourced"]:
        note = f"Outsourced: billed for the service used only. {note}"
    done = one(conn, """INSERT INTO procedures_performed(proc_order_id,snomed_code,outcome_notes,performed_by,charge_id)
        VALUES (%s,%s,%s,%s,%s) RETURNING *""", (proc_order_id, order["snomed_code"], note, who, charge["charge_id"]))
    conn.execute("UPDATE procedure_orders SET status='PERFORMED' WHERE proc_order_id=%s", (proc_order_id,))
    audit(conn, who, "PROCEDURE_PERFORMED", "procedures_performed", done["proc_perf_id"], {"proc_order_id": proc_order_id})
    return {"performed": done, "charge": charge, "duplicate": False}


def pending_orders(conn, encounter_id: str) -> int:
    return one(conn, """SELECT
        (SELECT count(*) FROM lab_orders WHERE encounter_id=%(e)s AND status='ORDERED') +
        (SELECT count(*) FROM radiology_orders WHERE encounter_id=%(e)s AND status='ORDERED') +
        (SELECT count(*) FROM procedure_orders WHERE encounter_id=%(e)s AND status='ORDERED') +
        (SELECT count(*) FROM pharmacy_orders WHERE encounter_id=%(e)s AND status IN ('ORDERED','PARTIAL')) AS n""",
        {"e": encounter_id})["n"]


def cancel_order(conn, who: str, data: CancelOrderIn) -> dict:
    """An order that will not be done (e.g. patient declined). Nothing is charged for it."""
    need(data.kind in ORDER_TABLES, "Kind must be LAB, RADIOLOGY, PROCEDURE or PHARMACY")
    table, pk, _ = ORDER_TABLES[data.kind]
    order = need(one(conn, f"SELECT * FROM {table} WHERE {pk}=%s FOR UPDATE", (data.order_id,)), "Order not found", 404)
    need(order["status"] in {"ORDERED", "PARTIAL"}, "Only a pending order can be cancelled")
    need(encounter_for(conn, order["encounter_id"])["status"] == "OPEN", "The visit is closed")
    updated = one(conn, f"UPDATE {table} SET status='CANCELLED' WHERE {pk}=%s RETURNING *", (data.order_id,))
    audit(conn, who, "ORDER_CANCELLED", table, data.order_id, {"reason": data.reason})
    return updated


def discharge(conn, who: str, encounter_id: str, on: date | None = None) -> dict:
    """End of visit: closes the ward stay, posts bed days, and makes the visit ready for the pre-bill audit."""
    enc = encounter_for(conn, encounter_id, True)
    need(enc["status"] == "OPEN", "The visit is already discharged or billed", 409)
    waiting = pending_orders(conn, encounter_id)
    need(not waiting, f"{waiting} order(s) are still pending. Complete or cancel them before discharge.")
    end = on or date.today()
    for stay in rows(conn, "SELECT * FROM room_stays WHERE encounter_id=%s AND end_date IS NULL", (encounter_id,)):
        stay_end = max(end, stay["start_date"] + timedelta(days=1))
        days = (stay_end - stay["start_date"]).days
        ward = one(conn, "SELECT * FROM wards WHERE ward_id=%s", (stay["ward_id"],))
        rule = "CARE_EXEMPT" if ward["ward_type"] == "ICU" else None
        charge = create_charge(conn, who, encounter_id, ward["room_service_code"], days, f"ROOM-{stay['room_stay_id']}",
                               source_type="ROOM_STAY", source_id=str(stay["room_stay_id"]),
                               room_stay_id=stay["room_stay_id"], tax_rule_override=rule)["charge"]
        conn.execute("UPDATE room_stays SET end_date=%s,charge_id=%s WHERE room_stay_id=%s",
                     (stay_end, charge["charge_id"], stay["room_stay_id"]))
    updated = one(conn, """UPDATE encounters SET status='DISCHARGED',discharged_at=now() WHERE encounter_id=%s RETURNING *""",
                  (encounter_id,))
    audit(conn, who, "VISIT_DISCHARGED", "encounters", encounter_id)
    return updated


# --- diagnostics ----------------------------------------------------------

def complete_lab(conn, who: str, lab_order_id: int, value: float) -> dict:
    order = need(one(conn, "SELECT * FROM lab_orders WHERE lab_order_id=%s FOR UPDATE", (lab_order_id,)),
                 "Lab order not found", 404)
    if order["status"] == "COMPLETED":
        done = one(conn, "SELECT * FROM lab_results WHERE lab_order_id=%s", (lab_order_id,))
        need(float(done["result_value"]) == value, "The result is already recorded and cannot be changed by repeating", 409)
        return {"result": done, "charge": one(conn, "SELECT * FROM charges WHERE charge_id=%s", (done["charge_id"],)),
                "duplicate": True}
    need(order["status"] == "ORDERED", "This lab order is cancelled")
    test = one(conn, "SELECT * FROM lab_catalog WHERE service_code=%s", (order["service_code"],))
    charge = create_charge(conn, who, order["encounter_id"], order["service_code"], 1, f"LAB-ORDER-{lab_order_id}",
                           source_type="LAB_RESULT", source_id=str(lab_order_id))["charge"]
    done = one(conn, """INSERT INTO lab_results(lab_order_id,loinc_code,result_value,result_unit,report_file,performed_by,charge_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (lab_order_id, test["loinc_code"], value, test["result_unit"], f"reports/lab-{lab_order_id}.pdf", who, charge["charge_id"]))
    conn.execute("UPDATE lab_orders SET status='COMPLETED' WHERE lab_order_id=%s", (lab_order_id,))
    audit(conn, who, "LAB_RESULT_RECORDED", "lab_results", done["result_id"], {"loinc": test["loinc_code"]})
    return {"result": done, "charge": charge, "duplicate": False}


def report_radiology(conn, who: str, rad_order_id: int, findings: str) -> dict:
    order = need(one(conn, "SELECT * FROM radiology_orders WHERE rad_order_id=%s FOR UPDATE", (rad_order_id,)),
                 "Radiology order not found", 404)
    if order["status"] == "COMPLETED":
        done = one(conn, "SELECT * FROM radiology_results WHERE rad_order_id=%s", (rad_order_id,))
        return {"result": done, "duplicate": True}
    need(order["status"] == "ORDERED", "This radiology order is cancelled")
    study = one(conn, "SELECT * FROM radiology_catalog WHERE service_code=%s", (order["service_code"],))
    charge = create_charge(conn, who, order["encounter_id"], order["service_code"], 1, f"RAD-ORDER-{rad_order_id}",
                           source_type="RADIOLOGY_RESULT", source_id=str(rad_order_id))["charge"]
    done = one(conn, """INSERT INTO radiology_results(rad_order_id,findings,snomed_code,report_file,reported_by,charge_id)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (rad_order_id, findings.strip(), study["snomed_code"], f"reports/rad-{rad_order_id}.pdf", who, charge["charge_id"]))
    conn.execute("UPDATE radiology_orders SET status='COMPLETED' WHERE rad_order_id=%s", (rad_order_id,))
    audit(conn, who, "RADIOLOGY_REPORTED", "radiology_results", done["result_id"], {"snomed": study["snomed_code"]})
    return {"result": done, "charge": charge, "duplicate": False}


# --- pharmacy -------------------------------------------------------------

def dispense_core(conn, who: str, data: DispenseIn) -> dict:
    existing = one(conn, """SELECT d.*,c.source_event_id FROM dispenses d JOIN charges c USING(charge_id)
        WHERE c.source_event_id=%s""", (data.source_event_id,))
    if existing:
        need((existing["pharm_order_id"], existing["quantity"]) == (data.pharm_order_id, data.quantity),
             "This dispense event ID has a different payload", 409)
        return {"dispense": existing, "duplicate": True}
    order = need(one(conn, "SELECT * FROM pharmacy_orders WHERE pharm_order_id=%s FOR UPDATE", (data.pharm_order_id,)),
                 "Pharmacy order not found", 404)
    need(order["status"] in {"ORDERED", "PARTIAL"}, "This pharmacy order is complete or cancelled")
    enc = encounter_for(conn, order["encounter_id"], True)
    need(enc["status"] == "OPEN", "Dispensing needs an open visit")
    item = one(conn, "SELECT * FROM pharmacy_items WHERE item_code=%s", (order["item_code"],))
    need(not item["controlled_stock"], "Controlled medicines need a separate register")
    given = one(conn, "SELECT COALESCE(sum(quantity),0)::bigint AS n FROM dispenses WHERE pharm_order_id=%s", (data.pharm_order_id,))["n"]
    need(given + data.quantity <= order["quantity"], "Quantity exceeds the doctor's prescription")
    batch = need(one(conn, """SELECT * FROM stock_batches WHERE item_code=%s AND expiry_date>%s AND quantity_available>=%s
        ORDER BY expiry_date,batch_id LIMIT 1 FOR UPDATE""", (order["item_code"], date.today(), data.quantity)),
                 "No unexpired batch has enough stock")
    service = one(conn, "SELECT * FROM services WHERE service_code=%s", (item["service_code"],))
    # Medicines supplied during an admission form part of exempt inpatient care; OPD sales follow the item rule.
    rule = "CARE_EXEMPT" if enc["setting"] == "IPD" else service["tax_rule_code"]
    need(tax_for(conn, rule)["tax_category"] != "REVIEW", "This item's GST classification needs review first")
    charge = create_charge(conn, who, order["encounter_id"], item["service_code"], data.quantity, data.source_event_id,
                           source_type="DISPENSE", source_id=str(data.pharm_order_id), tax_rule_override=rule)["charge"]
    conn.execute("UPDATE stock_batches SET quantity_available=quantity_available-%s WHERE batch_id=%s",
                 (data.quantity, batch["batch_id"]))
    disp = one(conn, """INSERT INTO dispenses(pharm_order_id,encounter_id,item_code,batch_id,charge_id,quantity,dispensed_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (data.pharm_order_id, order["encounter_id"], order["item_code"], batch["batch_id"], charge["charge_id"],
         data.quantity, who))
    conn.execute("UPDATE pharmacy_orders SET status=%s WHERE pharm_order_id=%s",
                 ("DISPENSED" if given + data.quantity == order["quantity"] else "PARTIAL", data.pharm_order_id))
    audit(conn, who, "MEDICINE_DISPENSED", "dispenses", disp["dispense_id"], {"batch_no": batch["batch_no"]})
    return {"dispense": disp, "charge": charge, "duplicate": False}


# --- endpoints ------------------------------------------------------------

@router.post("/api/clinical/consultations")
def create_consultation(data: ConsultationIn, request: Request):
    with db() as conn:
        return consult(conn, actor(request), data)


@router.post("/api/clinical/prescriptions")
def create_prescription(data: PrescriptionIn, request: Request):
    with db() as conn:
        return prescribe(conn, actor(request), data)


@router.post("/api/clinical/admissions")
def create_admission(data: AdmitIn, encounter_id: str, request: Request):
    with db() as conn:
        return admit(conn, actor(request), encounter_id, data.ward_id)


@router.post("/api/procedures/{proc_order_id}/perform")
def perform(proc_order_id: int, data: PerformIn, request: Request):
    with db() as conn:
        return perform_procedure(conn, actor(request), proc_order_id, data)


@router.post("/api/clinical/orders/cancel")
def cancel(data: CancelOrderIn, request: Request):
    with db() as conn:
        return cancel_order(conn, actor(request), data)


@router.post("/api/encounters/{encounter_id}/discharge")
def discharge_visit(encounter_id: str, request: Request):
    with db() as conn:
        return discharge(conn, actor(request), encounter_id)


@router.post("/api/his/events")
def his_event(data: HisEventIn, request: Request):
    """Generic HIS charge event (legacy/manual capture). The pre-bill audit flags charges with no completed source."""
    with db() as conn:
        return create_charge(conn, actor(request), data.encounter_id, data.service_code, data.quantity,
                             data.source_event_id, source_type="HIS_EVENT")


@router.post("/api/lab/orders/{lab_order_id}/complete")
def lab_complete(lab_order_id: int, data: LabResultIn, request: Request):
    with db() as conn:
        return complete_lab(conn, actor(request), lab_order_id, data.result_value)


@router.post("/api/radiology/orders/{rad_order_id}/report")
def radiology_report(rad_order_id: int, data: RadiologyReportIn, request: Request):
    with db() as conn:
        return report_radiology(conn, actor(request), rad_order_id, data.findings)


@router.post("/api/pharmacy/dispense")
def dispense(data: DispenseIn, request: Request):
    with db() as conn:
        return dispense_core(conn, actor(request), data)


@router.get("/api/diagnostics/queue")
def diagnostics_queue():
    with db() as conn:
        labs = rows(conn, """SELECT o.lab_order_id AS order_id,'LAB' AS kind,o.status,o.ordered_at,o.encounter_id,
            p.display_label AS patient_label,p.patient_id,s.description,c.loinc_code AS code,c.result_unit,c.reference_range
            FROM lab_orders o JOIN lab_catalog c USING(service_code) JOIN services s USING(service_code)
            JOIN encounters e USING(encounter_id) JOIN patients p USING(patient_id) ORDER BY o.ordered_at DESC LIMIT 100""")
        rads = rows(conn, """SELECT o.rad_order_id AS order_id,'RADIOLOGY' AS kind,o.status,o.ordered_at,o.encounter_id,
            p.display_label AS patient_label,p.patient_id,s.description,c.snomed_code AS code,o.modality,o.clinical_notes
            FROM radiology_orders o JOIN radiology_catalog c USING(service_code) JOIN services s USING(service_code)
            JOIN encounters e USING(encounter_id) JOIN patients p USING(patient_id) ORDER BY o.ordered_at DESC LIMIT 100""")
    return {"orders": sorted(labs + rads, key=lambda r: r["ordered_at"], reverse=True)}


@router.get("/api/pharmacy/queue")
def pharmacy_queue():
    with db() as conn:
        return {"orders": rows(conn, """SELECT o.*,p.display_label AS patient_label,p.patient_id,i.display_name,
            COALESCE((SELECT sum(d.quantity) FROM dispenses d WHERE d.pharm_order_id=o.pharm_order_id),0) AS dispensed_quantity
            FROM pharmacy_orders o JOIN pharmacy_items i USING(item_code) JOIN encounters e USING(encounter_id)
            JOIN patients p USING(patient_id) WHERE o.status IN ('ORDERED','PARTIAL') ORDER BY o.ordered_at DESC""")}


@router.get("/api/pharmacy/stock")
def pharmacy_stock():
    with db() as conn:
        items = rows(conn, """SELECT p.item_code,p.display_name AS description,p.requires_prescription,p.controlled_stock,
            s.base_unit_paise AS unit_price_paise,s.tax_rule_code,t.hsn_sac AS hsn_code,t.tax_category,t.rate_bps AS tax_rate_bps
            FROM pharmacy_items p JOIN services s USING(service_code) JOIN tax_rules t ON t.rule_code=s.tax_rule_code
            ORDER BY p.item_code""")
        for item in items:
            item["batches"] = rows(conn, "SELECT * FROM stock_batches WHERE item_code=%s ORDER BY expiry_date", (item["item_code"],))
            item["available_units"] = sum(b["quantity_available"] for b in item["batches"] if b["expiry_date"] > date.today())
        return {"items": items}

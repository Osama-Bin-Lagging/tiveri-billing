"""Read endpoints shared by every desk: catalog, patient record, visit detail."""

from __future__ import annotations

from fastapi import APIRouter

from .core import age_years, balance_for, db, encounter_for, need, one, rows, running_totals, split_shares, deposits_available

router = APIRouter()


@router.get("/api/catalog")
def catalog():
    with db() as conn:
        return {
            "diagnoses": rows(conn, "SELECT * FROM diagnosis_catalog ORDER BY icd_code"),
            "labs": rows(conn, """SELECT c.*,s.description,s.base_unit_paise FROM lab_catalog c JOIN services s USING(service_code)
                ORDER BY s.description"""),
            "radiology": rows(conn, """SELECT c.*,s.description,s.base_unit_paise FROM radiology_catalog c
                JOIN services s USING(service_code) ORDER BY s.description"""),
            "procedures": rows(conn, """SELECT c.*,s.description,s.base_unit_paise FROM procedure_catalog c
                JOIN services s USING(service_code) ORDER BY s.description"""),
            "medicines": rows(conn, """SELECT i.item_code,i.display_name,s.base_unit_paise FROM pharmacy_items i
                JOIN services s USING(service_code) WHERE i.requires_prescription ORDER BY i.display_name"""),
            "wards": rows(conn, """SELECT w.*,s.base_unit_paise FROM wards w JOIN services s ON s.service_code=w.room_service_code
                ORDER BY s.base_unit_paise"""),
            "doctors": rows(conn, """SELECT d.*,dep.name AS department FROM doctors d JOIN departments dep USING(department_id)
                ORDER BY d.doctor_id"""),
            "packages": rows(conn, "SELECT * FROM package_catalog ORDER BY package_code"),
        }


@router.get("/api/patients")
def patient_list():
    with db() as conn:
        patients = rows(conn, """SELECT p.*,e.encounter_id AS latest_encounter_id,e.status AS latest_status,
            e.setting AS latest_setting FROM patients p
            LEFT JOIN LATERAL (SELECT encounter_id,status,setting FROM encounters WHERE patient_id=p.patient_id
              ORDER BY opened_at DESC,encounter_id DESC LIMIT 1) e ON true ORDER BY p.patient_id""")
    for p in patients:
        p["age_years"] = age_years(p["dob"])
    return {"patients": patients}


@router.get("/api/patients/{patient_id}")
def patient_detail(patient_id: str):
    with db() as conn:
        patient = need(one(conn, "SELECT * FROM patients WHERE patient_id=%s", (patient_id,)), "Patient not found", 404)
        patient["age_years"] = age_years(patient["dob"])
        return {"patient": patient,
                "policies": rows(conn, "SELECT * FROM insurance_policies WHERE patient_id=%s ORDER BY policy_id", (patient_id,)),
                "appointments": rows(conn, """SELECT a.*,d.name AS doctor_name FROM appointments a JOIN doctors d USING(doctor_id)
                    WHERE patient_id=%s ORDER BY slot_at DESC""", (patient_id,)),
                "encounters": rows(conn, """SELECT encounter_id,setting,payment_mode,payer_route,payer_label,status,opened_at
                    FROM encounters WHERE patient_id=%s ORDER BY opened_at DESC,encounter_id DESC""", (patient_id,)),
                "notifications": rows(conn, """SELECT * FROM notifications WHERE patient_id=%s
                    ORDER BY created_at DESC,notification_id DESC""", (patient_id,))}


@router.get("/api/encounters/{encounter_id}")
def encounter_detail(encounter_id: str):
    with db() as conn:
        enc = encounter_for(conn, encounter_id)
        e = (encounter_id,)
        invoice = one(conn, "SELECT * FROM invoices WHERE encounter_id=%s", e)
        cov = one(conn, "SELECT * FROM coverages WHERE encounter_id=%s", e)
        charges = rows(conn, """SELECT c.*,s.kind,EXISTS (SELECT 1 FROM charges o WHERE o.reverses_charge_id=c.charge_id)
            AS offset_applied FROM charges c JOIN services s USING(service_code) WHERE encounter_id=%s ORDER BY charge_id""", e)
        totals = running_totals(conn, encounter_id)
        if invoice:
            balance = balance_for(conn, invoice)
        else:
            patient_share, payer_share = split_shares(enc, cov, totals["total_paise"])
            used = min(patient_share, max(0, deposits_available(conn, encounter_id)))
            balance = {"patient_share_paise": patient_share, "payer_share_paise": payer_share, "deposit_used_paise": used,
                       "patient_due_paise": patient_share - used, "payer_due_paise": payer_share,
                       "remaining_paise": totals["total_paise"] - used, "payment_status": "NOT_BILLED"}
        inv = (invoice["invoice_id"],) if invoice else None
        patient = one(conn, "SELECT * FROM patients WHERE patient_id=%s", (enc["patient_id"],))
        patient["age_years"] = age_years(patient["dob"])
        return {
            "encounter": enc, "patient": patient, "coverage": cov,
            "policy": one(conn, "SELECT * FROM insurance_policies WHERE policy_id=%s", (enc["policy_id"],)) if enc["policy_id"] else None,
            "doctor": one(conn, "SELECT * FROM doctors WHERE doctor_id=%s", (enc["doctor_id"],)) if enc["doctor_id"] else None,
            "consultations": rows(conn, """SELECT k.*,d.name AS doctor_name FROM consultations k JOIN doctors d USING(doctor_id)
                WHERE encounter_id=%s ORDER BY consult_id""", e),
            "prescriptions": rows(conn, """SELECT p.*,dx.title AS diagnosis FROM prescriptions p
                JOIN diagnosis_catalog dx USING(icd_code) WHERE encounter_id=%s ORDER BY prescription_id""", e),
            "lab_orders": rows(conn, """SELECT o.*,s.description,c.loinc_code,c.result_unit,c.reference_range,
                r.result_id,r.result_value,r.report_date FROM lab_orders o JOIN lab_catalog c USING(service_code)
                JOIN services s USING(service_code) LEFT JOIN lab_results r USING(lab_order_id)
                WHERE o.encounter_id=%s ORDER BY lab_order_id""", e),
            "radiology_orders": rows(conn, """SELECT o.*,s.description,c.snomed_code,r.result_id,r.findings,r.report_date
                FROM radiology_orders o JOIN radiology_catalog c USING(service_code) JOIN services s USING(service_code)
                LEFT JOIN radiology_results r USING(rad_order_id) WHERE o.encounter_id=%s ORDER BY rad_order_id""", e),
            "procedure_orders": rows(conn, """SELECT o.*,s.description,c.partner,p.proc_perf_id,p.outcome_notes,p.performed_at
                FROM procedure_orders o JOIN procedure_catalog c USING(service_code) JOIN services s USING(service_code)
                LEFT JOIN procedures_performed p USING(proc_order_id) WHERE o.encounter_id=%s ORDER BY proc_order_id""", e),
            "pharmacy_orders": rows(conn, """SELECT o.*,i.display_name,COALESCE((SELECT sum(d.quantity) FROM dispenses d
                WHERE d.pharm_order_id=o.pharm_order_id),0) AS dispensed_quantity FROM pharmacy_orders o
                JOIN pharmacy_items i USING(item_code) WHERE o.encounter_id=%s ORDER BY pharm_order_id""", e),
            "dispenses": rows(conn, "SELECT * FROM dispenses WHERE encounter_id=%s ORDER BY dispense_id", e),
            "room_stays": rows(conn, """SELECT r.*,w.ward_name,w.ward_type FROM room_stays r JOIN wards w USING(ward_id)
                WHERE encounter_id=%s ORDER BY room_stay_id""", e),
            "charges": charges,
            "preauths": rows(conn, "SELECT * FROM preauths WHERE encounter_id=%s ORDER BY preauth_id", e),
            "invoice": invoice,
            "invoice_lines": rows(conn, "SELECT * FROM invoice_lines WHERE invoice_id=%s ORDER BY line_no", inv) if inv else [],
            "claims": rows(conn, "SELECT * FROM claims WHERE invoice_id=%s ORDER BY attempt_no", inv) if inv else [],
            "adjustments": rows(conn, "SELECT * FROM balance_adjustments WHERE invoice_id=%s ORDER BY adjustment_id", inv) if inv else [],
            "receipts": rows(conn, "SELECT * FROM receipts WHERE invoice_id=%s ORDER BY receipt_id", inv) if inv else [],
            "advances": rows(conn, "SELECT * FROM advances WHERE encounter_id=%s ORDER BY advance_id", e),
            "refunds": rows(conn, "SELECT * FROM refunds WHERE encounter_id=%s ORDER BY refund_id", e),
            "notifications": rows(conn, "SELECT * FROM notifications WHERE encounter_id=%s ORDER BY notification_id DESC", e),
            "running_total_paise": totals["total_paise"], "running_subtotal_paise": totals["subtotal_paise"],
            "running_tax_paise": totals["tax_paise"], **balance}

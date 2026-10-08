"""Invented teaching data only. Every case is built through the same functions the desks use,
so the seeded records follow the same rules as live ones. Never import a real bill here."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import secrets

from . import billing, clinical, payer, reception
from .core import audit, create_charge

PASSWORD = "Demo@1234"


def password_digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def _many(conn, sql: str, data: list[tuple]) -> None:
    conn.cursor().executemany(sql, data)


def seed_reference(conn) -> None:
    _many(conn, "INSERT INTO departments(department_id,name,kind) VALUES (%s,%s,%s)", [
        ("GEN_MED", "General Medicine", "CLINICAL"), ("PULMO", "Pulmonology", "CLINICAL"),
        ("ORTHO", "Orthopaedics", "CLINICAL"), ("LAB", "Laboratory", "DIAGNOSTIC"),
        ("RADIOLOGY", "Radiology", "DIAGNOSTIC"), ("PHARMACY", "Pharmacy", "PHARMACY"),
        ("WARDS", "Wards", "SUPPORT"), ("BILLING", "Packages", "SUPPORT")])
    _many(conn, """INSERT INTO tax_rules(rule_code,effective_from,tax_category,rate_bps,hsn_sac,note)
        VALUES (%s,'2026-01-01',%s,%s,%s,%s)""", [
        ("CARE_EXEMPT", "EXEMPT", 0, "9993", "Healthcare services; exemption needs qualification review"),
        ("ROOM_5_DEMO", "TAXABLE", 500, "9993", "Teaching assumption: non-ICU room above Rs 5,000/day, CBIC conditions apply"),
        ("MED_5_DEMO", "TAXABLE", 500, "3004", "Teaching assumption for a separate (OPD) medicine sale; verify HSN and rate"),
        ("MED_NIL_DEMO", "NIL", 0, "3006", "Teaching assumption: nil-rated product; verify classification"),
        ("DEVICE_5_DEMO", "TAXABLE", 500, "9018", "Teaching assumption for a medical device; verify HSN and rate"),
        ("REVIEW_REQUIRED", "REVIEW", 0, "", "Finance must classify this item before billing")])
    _many(conn, """INSERT INTO services(service_code,description,department_id,kind,base_unit_paise,tax_rule_code)
        VALUES (%s,%s,%s,%s,%s,%s)""", [
        ("CONSULT", "Doctor consultation", "GEN_MED", "CARE", 50000, "CARE_EXEMPT"),
        ("CONSULT_SPEC", "Specialist consultation", "PULMO", "CARE", 75000, "CARE_EXEMPT"),
        ("CBC", "Complete blood count", "LAB", "LAB", 79000, "CARE_EXEMPT"),
        ("CRP", "C-reactive protein", "LAB", "LAB", 89000, "CARE_EXEMPT"),
        ("DENGUE_NS1", "Dengue NS1 antigen", "LAB", "LAB", 249000, "CARE_EXEMPT"),
        ("HBA1C", "HbA1c blood test", "LAB", "LAB", 65000, "CARE_EXEMPT"),
        ("LFT", "Liver function tests", "LAB", "LAB", 90000, "CARE_EXEMPT"),
        ("URINE_RM", "Urine routine examination", "LAB", "LAB", 25000, "CARE_EXEMPT"),
        ("XRAY_CHEST", "Chest X-ray", "RADIOLOGY", "RADIOLOGY", 90000, "CARE_EXEMPT"),
        ("USG_ABD", "Ultrasound abdomen", "RADIOLOGY", "RADIOLOGY", 188000, "CARE_EXEMPT"),
        ("CT_CHEST", "CT chest with contrast", "RADIOLOGY", "RADIOLOGY", 650000, "CARE_EXEMPT"),
        ("NEBULISATION", "Nebulisation", "PULMO", "PROCEDURE", 40000, "CARE_EXEMPT"),
        ("DRESSING", "Wound dressing", "GEN_MED", "PROCEDURE", 60000, "CARE_EXEMPT"),
        ("PHYSIO_OUT", "Physiotherapy session (outsourced)", "ORTHO", "PROCEDURE", 120000, "CARE_EXEMPT"),
        ("WARD_GENERAL", "General ward, per day", "WARDS", "ROOM", 230000, "CARE_EXEMPT"),
        ("WARD_SEMI", "Semi-private room, per day", "WARDS", "ROOM", 400000, "CARE_EXEMPT"),
        ("WARD_PRIVATE", "Private room, per day", "WARDS", "ROOM", 600000, "ROOM_5_DEMO"),
        ("WARD_ICU", "ICU bed, per day", "WARDS", "ROOM", 1200000, "CARE_EXEMPT"),
        ("MED_PCM", "Paracetamol 500 mg tablet", "PHARMACY", "PHARMACY", 200, "MED_5_DEMO"),
        ("MED_MET", "Metformin 500 mg tablet", "PHARMACY", "PHARMACY", 600, "MED_5_DEMO"),
        ("MED_AMOX", "Amoxicillin 500 mg capsule", "PHARMACY", "PHARMACY", 1200, "MED_5_DEMO"),
        ("MED_SAL", "Salbutamol inhaler", "PHARMACY", "PHARMACY", 18000, "MED_5_DEMO"),
        ("MED_ORS", "ORS sachet", "PHARMACY", "PHARMACY", 2000, "MED_5_DEMO"),
        ("MED_NIL", "Contraceptive product (nil-rated example)", "PHARMACY", "PHARMACY", 18000, "MED_NIL_DEMO"),
        ("DEVICE_BRACE", "Knee brace", "PHARMACY", "DEVICE", 250000, "DEVICE_5_DEMO"),
        ("MED_UNCLASSIFIED", "Unclassified pharmacy item", "PHARMACY", "PHARMACY", 10000, "REVIEW_REQUIRED"),
        ("PMJAY_PKG", "PM-JAY package (teaching rate)", "BILLING", "PACKAGE", 1200000, "CARE_EXEMPT"),
        ("DAY_PKG", "Day-care package", "BILLING", "PACKAGE", 600000, "CARE_EXEMPT")])
    _many(conn, "INSERT INTO payer_rates(service_code,payer_route,payer_label,unit_paise) VALUES (%s,%s,%s,%s)", [
        ("CONSULT", "PRIVATE", "", 45000), ("CONSULT", "PRIVATE", "Alpha TPA", 43000),
        ("CONSULT", "PRIVATE", "Bharat TPA", 44000), ("CONSULT", "CGHS", "", 40000), ("CONSULT", "CORPORATE", "", 45000),
        ("CONSULT_SPEC", "PRIVATE", "", 70000), ("CBC", "CGHS", "", 60000), ("WARD_GENERAL", "PRIVATE", "", 220000),
        ("PMJAY_PKG", "PMJAY", "", 1200000)])
    # ICD-10 -> SNOMED CT teaching map; verify codes in the official browsers before real use.
    _many(conn, "INSERT INTO diagnosis_catalog(icd_code,title,snomed_code) VALUES (%s,%s,%s)", [
        ("A09", "Gastroenteritis and colitis, infectious origin", "25374005"),
        ("A90", "Dengue fever", "38362002"),
        ("E11.9", "Type 2 diabetes mellitus without complications", "44054006"),
        ("I10", "Essential (primary) hypertension", "59621000"),
        ("J18.9", "Pneumonia, unspecified organism", "233604007"),
        ("J45.9", "Asthma, unspecified", "195967001"),
        ("M17.9", "Osteoarthritis of knee, unspecified", "239873007"),
        ("R50.9", "Fever, unspecified", "386661006")])
    _many(conn, """INSERT INTO lab_catalog(service_code,loinc_code,result_unit,specimen,reference_range,cpt_reference)
        VALUES (%s,%s,%s,%s,%s,%s)""", [
        ("CBC", "58410-2", "g/dL (Hb)", "Blood", "12-16", "85025"),
        ("CRP", "1988-5", "mg/L", "Serum", "< 5", "86140"),
        ("DENGUE_NS1", "75377-9", "index", "Serum", "< 0.9 negative", ""),
        ("HBA1C", "4548-4", "%", "Blood", "4.0-5.6", "83036"),
        ("LFT", "24325-3", "U/L (ALT)", "Serum", "7-56", "80076"),
        ("URINE_RM", "24356-8", "pH", "Urine", "4.5-8", "81001")])
    _many(conn, "INSERT INTO radiology_catalog(service_code,snomed_code,modality,body_site) VALUES (%s,%s,%s,%s)", [
        ("XRAY_CHEST", "399208008", "XRAY", "Chest"), ("USG_ABD", "16310003", "USG", "Abdomen"),
        ("CT_CHEST", "363680008", "CT", "Chest")])
    _many(conn, "INSERT INTO procedure_catalog(service_code,snomed_code,outsourced,partner) VALUES (%s,%s,%s,%s)", [
        ("NEBULISATION", "56251003", False, ""), ("DRESSING", "182531007", False, ""),
        ("PHYSIO_OUT", "91251008", True, "City Physio Centre (partner)")])
    _many(conn, """INSERT INTO pharmacy_items(item_code,service_code,display_name,requires_prescription,controlled_stock)
        VALUES (%s,%s,%s,%s,%s)""", [
        ("MED-PCM", "MED_PCM", "Paracetamol 500 mg tablet", True, False),
        ("MED-MET", "MED_MET", "Metformin 500 mg tablet", True, False),
        ("MED-AMOX", "MED_AMOX", "Amoxicillin 500 mg capsule", True, False),
        ("MED-SAL", "MED_SAL", "Salbutamol inhaler", True, False),
        ("MED-ORS", "MED_ORS", "ORS sachet", True, False),
        ("MED-NIL", "MED_NIL", "Contraceptive product (nil-rated example)", True, False),
        ("DEVICE-BRACE", "DEVICE_BRACE", "Knee brace", False, False),
        ("MED-X", "MED_UNCLASSIFIED", "Unclassified pharmacy item", True, False)])
    today = date.today()
    _many(conn, "INSERT INTO stock_batches(item_code,batch_no,expiry_date,quantity_available) VALUES (%s,%s,%s,%s)", [
        ("MED-PCM", "PCM-2601", today + timedelta(days=300), 400), ("MED-PCM", "PCM-2602", today + timedelta(days=540), 400),
        ("MED-MET", "MET-2601", today + timedelta(days=365), 500), ("MED-AMOX", "AMX-2601", today + timedelta(days=200), 300),
        ("MED-SAL", "SAL-2601", today + timedelta(days=400), 40), ("MED-ORS", "ORS-2601", today + timedelta(days=500), 200),
        ("MED-NIL", "NIL-2601", today + timedelta(days=365), 24), ("DEVICE-BRACE", "BRC-2601", today + timedelta(days=900), 12),
        ("MED-X", "MX-2601", today + timedelta(days=365), 10), ("MED-AMOX", "AMX-OLD", today - timedelta(days=5), 50)])
    _many(conn, """INSERT INTO package_catalog(package_code,service_code,payer_route,included_kinds,preauth_required,note)
        VALUES (%s,%s,%s,%s,%s,%s)""", [
        ("HBP-DEMO-01", "PMJAY_PKG", "PMJAY", ["ROOM", "LAB", "RADIOLOGY", "PROCEDURE", "PHARMACY", "CARE"], True,
         "Invented teaching package, not an official HBP rate"),
        ("DAY-DEMO-01", "DAY_PKG", "SELF", ["PROCEDURE", "LAB"], False, "Invented day-care package")])
    _many(conn, "INSERT INTO wards(ward_id,ward_name,ward_type,room_service_code,beds) VALUES (%s,%s,%s,%s,%s)", [
        ("W-GEN", "General ward", "GENERAL", "WARD_GENERAL", 20), ("W-SEMI", "Semi-private", "SEMI_PRIVATE", "WARD_SEMI", 8),
        ("W-PVT", "Private room", "PRIVATE", "WARD_PRIVATE", 6), ("W-ICU", "ICU", "ICU", "WARD_ICU", 4)])
    _many(conn, """INSERT INTO doctors(doctor_id,name,specialization,department_id,contact_masked,consult_service_code)
        VALUES (%s,%s,%s,%s,%s,%s)""", [
        ("D-01", "Dr Mira Sen", "General physician", "GEN_MED", "9XXXXX3101", "CONSULT"),
        ("D-02", "Dr Arvind Rao", "Pulmonologist", "PULMO", "9XXXXX3102", "CONSULT_SPEC"),
        ("D-03", "Dr Kavya Iyer", "Orthopaedic surgeon", "ORTHO", "9XXXXX3103", "CONSULT_SPEC")])


def seed_staff(conn) -> None:
    for username, name, role, doctor in [
        ("reception", "Priya Das", "RECEPTION", None), ("admin", "Riya Menon", "ADMIN", None),
        ("doctor", "Dr Mira Sen", "DOCTOR", "D-01"), ("doctor2", "Dr Arvind Rao", "DOCTOR", "D-02"),
        ("doctor3", "Dr Kavya Iyer", "DOCTOR", "D-03"), ("lab", "Arjun Nair", "LAB", None),
        ("pharmacy", "Nisha Shah", "PHARMACY", None)]:
        salt = secrets.token_hex(16)
        conn.execute("""INSERT INTO staff_users(username,display_name,role,doctor_id,password_salt,password_hash)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (username) DO NOTHING""",
            (username, name, role, doctor, salt, password_digest(PASSWORD, salt)))


PATIENTS = [
    ("P-DEMO-01", "Ananya Rao", "1998-03-14", "Female", "B+", "Bengaluru", "No known drug allergies",
     "Fever for three days with body ache.", "91-2345-6789-0101"),
    ("P-DEMO-02", "Dev Mehta", "1980-07-02", "Male", "O+", "Mysuru", "Penicillin listed",
     "Cough and breathlessness for five days.", "91-2345-6789-0102"),
    ("P-DEMO-03", "Farah Khan", "1989-11-20", "Female", "A+", "Bengaluru", "No known drug allergies",
     "Vomiting and loose stools since yesterday; PM-JAY beneficiary.", "91-2345-6789-0103"),
    ("P-DEMO-04", "Kiran Das", "1964-01-09", "Male", "AB+", "Hubballi", "Sulfa listed",
     "Hypertension on long-term follow-up; CGHS beneficiary.", ""),
    ("P-DEMO-05", "Leela Nair", "1993-05-30", "Female", "O-", "Bengaluru", "No known drug allergies",
     "Corporate OPD visit with fever; employer pays.", ""),
    ("P-DEMO-06", "Manoj Shah", "1975-09-18", "Male", "B-", "Tumakuru", "No known drug allergies",
     "Type 2 diabetes on follow-up.", "91-2345-6789-0106"),
    ("P-DEMO-07", "Nadia Roy", "1983-04-11", "Female", "A-", "Mysuru", "No known drug allergies",
     "Acute asthma episode; admitted overnight.", ""),
    ("P-DEMO-08", "Rohan Iyer", "1987-12-05", "Male", "O+", "Bengaluru", "No known drug allergies",
     "Knee pain; admitted for observation and physiotherapy.", ""),
    ("P-DEMO-09", "Asha Kulkarni", "1974-06-21", "Female", "O+", "Bengaluru", "No known drug allergies",
     "Known type 2 diabetes. Coming in today for review of high glucose readings.", "91-2345-6789-0109"),
    ("P-DEMO-10", "Sanjay Kumar", "1969-02-27", "Male", "B+", "Mandya", "No known drug allergies",
     "Past OPD visit with an unpaid balance.", ""),
]


def _policy(conn, pid: str, policy_id: str, route: str, provider: str, number: str, cover: int, copay: int = 0) -> None:
    today = date.today()
    reception.add_policy(conn, "reception", pid, reception.PolicyIn(
        payer_route=route, provider_name=provider, policy_no=number, valid_from=today - timedelta(days=200),
        valid_to=today + timedelta(days=165), coverage_amount_paise=cover, nominee="Spouse", copay_percent=copay),
        policy_id=policy_id)


def _visit(conn, pid: str, eid: str, mode: str = "SELF", policy: str = "", setting: str = "OPD") -> None:
    reception.open_visit(conn, "reception", pid, reception.CheckInIn(setting=setting, payment_mode=mode, policy_id=policy),
                         encounter_id=eid)
    if mode == "CASHLESS":
        reception.verify_coverage_core(conn, "reception", eid)


def _consult(conn, eid: str, who: str, notes: str, icd: str, **orders) -> dict:
    clinical.consult(conn, who, clinical.ConsultationIn(encounter_id=eid, notes=notes))
    return clinical.prescribe(conn, who, clinical.PrescriptionIn(encounter_id=eid, icd_code=icd, **orders))


def _complete_all(conn, eid: str, rx: dict) -> None:
    for o in rx["lab_orders"]:
        clinical.complete_lab(conn, "lab", o["lab_order_id"], 11.8)
    for o in rx["radiology_orders"]:
        clinical.report_radiology(conn, "lab", o["rad_order_id"], "No acute abnormality reported (synthetic report).")
    for o in rx["procedure_orders"]:
        clinical.perform_procedure(conn, "doctor", o["proc_order_id"], clinical.PerformIn())
    for o in rx["pharmacy_orders"]:
        clinical.dispense_core(conn, "pharmacy", clinical.DispenseIn(pharm_order_id=o["pharm_order_id"],
                               quantity=o["quantity"], source_event_id=f"SEED-DISP-{o['pharm_order_id']}"))


def _backdate_bill(conn, eid: str, days: int) -> None:
    conn.execute("""UPDATE invoices SET issued_at=now()-make_interval(days=>%s), due_date=current_date-%s+15
        WHERE encounter_id=%s""", (days, days, eid))


def seed_demo(conn) -> None:
    seed_reference(conn)
    seed_staff(conn)
    for pid, name, dob, sex, blood, city, allergies, history, abha in PATIENTS:
        reception.register_patient(conn, "reception", reception.PatientIn(
            display_label=name, dob=date.fromisoformat(dob), sex=sex, blood_group=blood, city=city,
            contact_masked=f"9XXXXX{pid[-2:]}00", allergies=allergies, history_summary=history, abha_number=abha,
            abha_address=f"{name.split()[0].lower()}{pid[-2:]}@abdm" if abha else ""), patient_id=pid)
    _policy(conn, "P-DEMO-02", "POL-ALPHA-0102", "PRIVATE", "Alpha TPA", "ALP-55120102", 50000000, 10)
    _policy(conn, "P-DEMO-03", "POL-PMJAY-0103", "PMJAY", "PM-JAY", "PMJAY-KA-0103", 50000000)
    _policy(conn, "P-DEMO-04", "POL-CGHS-0104", "CGHS", "CGHS Bengaluru", "CGHS-BLR-0104", 10000000)
    _policy(conn, "P-DEMO-05", "POL-CORP-0105", "CORPORATE", "Demo Employer Pvt Ltd", "EMP-0105", 5000000)
    _policy(conn, "P-DEMO-07", "POL-BHARAT-0107", "PRIVATE", "Bharat TPA", "BHT-77810107", 30000000)
    _policy(conn, "P-DEMO-09", "POL-ALPHA-0109", "PRIVATE", "Alpha TPA", "ALP-55120109", 50000000)

    # 1. Ananya: appointment -> OPD, CBC done, NS1 and paracetamol still pending (fills the work queues).
    appt = reception.book_appointment(conn, "reception", reception.AppointmentIn(
        patient_id="P-DEMO-01", doctor_id="D-01",
        slot_at=datetime.now(timezone.utc).replace(hour=4, minute=30, second=0, microsecond=0), reason="Fever"))
    reception.open_visit(conn, "reception", "P-DEMO-01", reception.CheckInIn(), doctor_id="D-01",
                         appointment_id=appt["appointment_id"], encounter_id="E-OPD-01")
    conn.execute("UPDATE appointments SET status='CHECKED_IN',encounter_id='E-OPD-01' WHERE appointment_id=%s",
                 (appt["appointment_id"],))
    rx = _consult(conn, "E-OPD-01", "doctor", "Fever for three days, myalgia. Rule out dengue.", "R50.9",
                  labs=["CBC", "DENGUE_NS1"], medicines=[clinical.MedicineLine(item_code="MED-PCM", quantity=10,
                  instruction="One tablet if fever, up to three a day")])
    clinical.complete_lab(conn, "lab", rx["lab_orders"][0]["lab_order_id"], 12.6)

    # 2. Dev: Alpha TPA cashless pneumonia admission, billed, claim awaiting decision (partial-approval demo).
    _visit(conn, "P-DEMO-02", "E-IPD-02", "CASHLESS", "POL-ALPHA-0102")
    rx = _consult(conn, "E-IPD-02", "doctor2", "Productive cough, fever, crackles right base. Admit.", "J18.9",
                  labs=["CBC", "CRP"], radiology=[clinical.RadiologyLine(service_code="XRAY_CHEST", clinical_notes="Rule out consolidation")],
                  medicines=[clinical.MedicineLine(item_code="MED-AMOX", quantity=15, instruction="Three times a day")],
                  admit=clinical.AdmitIn(ward_id="W-GEN"))
    pa = billing.request_preauth(conn, "admin", billing.PreauthIn(encounter_id="E-IPD-02", requested_paise=2000000))
    billing.decide_preauth_core(conn, "admin", pa["preauth_id"], billing.PreauthDecisionIn(outcome="APPROVED"))
    _complete_all(conn, "E-IPD-02", rx)
    clinical.discharge(conn, "doctor2", "E-IPD-02")
    bill = billing.finalize_bill(conn, "admin", "E-IPD-02")
    payer.submit_claim_core(conn, "admin", payer.ClaimIn(invoice_id=bill["invoice_id"],
                            discharge_summary="Community-acquired pneumonia treated with oral antibiotics; discharged stable."))

    # 3. Farah: PM-JAY admission with package applied; open for the live discharge.
    _visit(conn, "P-DEMO-03", "E-IPD-03", "CASHLESS", "POL-PMJAY-0103")
    rx = _consult(conn, "E-IPD-03", "doctor", "Acute gastroenteritis with dehydration. Admit for IV fluids.", "A09",
                  labs=["CBC"], medicines=[clinical.MedicineLine(item_code="MED-ORS", quantity=6, instruction="After each loose stool")],
                  admit=clinical.AdmitIn(ward_id="W-GEN"))
    pa = billing.request_preauth(conn, "admin", billing.PreauthIn(encounter_id="E-IPD-03", requested_paise=1200000))
    billing.decide_preauth_core(conn, "admin", pa["preauth_id"], billing.PreauthDecisionIn(outcome="APPROVED"))
    billing.apply_package(conn, "admin", "E-IPD-03", "HBP-DEMO-01")
    clinical.complete_lab(conn, "lab", rx["lab_orders"][0]["lab_order_id"], 13.1)

    # 4. Kiran: CGHS OPD, billed, claim approved and paid -> settled.
    _visit(conn, "P-DEMO-04", "E-OPD-04", "CASHLESS", "POL-CGHS-0104")
    rx = _consult(conn, "E-OPD-04", "doctor", "BP 150/94 on two readings. Continue medication, review in a month.", "I10",
                  labs=["CBC"])
    _complete_all(conn, "E-OPD-04", rx)
    clinical.discharge(conn, "doctor", "E-OPD-04")
    bill = billing.finalize_bill(conn, "admin", "E-OPD-04")
    claim = payer.submit_claim_core(conn, "admin", payer.ClaimIn(invoice_id=bill["invoice_id"],
                                    discharge_summary="Hypertension review, OPD. No change in treatment."))
    payer.decide_claim_core(conn, "admin", claim["claim_id"], payer.ClaimDecisionIn(outcome="APPROVED"))
    payer.record_receipt(conn, "admin", payer.ReceiptIn(invoice_id=bill["invoice_id"], payer_kind="SCHEME",
                         amount_paise=claim["submitted_paise"], method="TRANSFER", reference_no="SYN-CGHS-0104"))
    _backdate_bill(conn, "E-OPD-04", 12)

    # 5. Leela: corporate OPD (B2B bill with a taxable OPD medicine line); claim approved, payment awaited.
    _visit(conn, "P-DEMO-05", "E-OPD-05", "CASHLESS", "POL-CORP-0105")
    rx = _consult(conn, "E-OPD-05", "doctor", "Low-grade fever, no focus. Symptomatic care.", "R50.9",
                  medicines=[clinical.MedicineLine(item_code="MED-PCM", quantity=10, instruction="If fever")])
    _complete_all(conn, "E-OPD-05", rx)
    clinical.discharge(conn, "doctor", "E-OPD-05")
    bill = billing.finalize_bill(conn, "admin", "E-OPD-05")
    claim = payer.submit_claim_core(conn, "admin", payer.ClaimIn(invoice_id=bill["invoice_id"],
                                    discharge_summary="Corporate OPD consultation; no admission."))
    payer.decide_claim_core(conn, "admin", claim["claim_id"], payer.ClaimDecisionIn(outcome="APPROVED"))

    # 6. Manoj: self-pay OPD with 5% GST medicine, billed; a UPI payment is pending (failure/retry demo).
    _visit(conn, "P-DEMO-06", "E-OPD-06")
    rx = _consult(conn, "E-OPD-06", "doctor", "Diabetes follow-up. Continue metformin; repeat HbA1c.", "E11.9",
                  labs=["HBA1C"], medicines=[clinical.MedicineLine(item_code="MED-MET", quantity=30, instruction="Twice a day after food")])
    _complete_all(conn, "E-OPD-06", rx)
    clinical.discharge(conn, "doctor", "E-OPD-06")
    bill = billing.finalize_bill(conn, "admin", "E-OPD-06")
    payer.record_receipt(conn, "admin", payer.ReceiptIn(invoice_id=bill["invoice_id"], payer_kind="PATIENT",
                         amount_paise=bill["patient_share_paise"], method="UPI", reference_no="UPI-SYN-0106"))

    # 7. Nadia: Bharat TPA asthma admission, billed, claim REJECTED (resubmission demo).
    _visit(conn, "P-DEMO-07", "E-IPD-07", "CASHLESS", "POL-BHARAT-0107")
    rx = _consult(conn, "E-IPD-07", "doctor2", "Acute asthma, SpO2 92%. Nebulise and observe overnight.", "J45.9",
                  procedures=["NEBULISATION"], medicines=[clinical.MedicineLine(item_code="MED-SAL", quantity=1, instruction="Two puffs as needed")],
                  admit=clinical.AdmitIn(ward_id="W-SEMI"))
    pa = billing.request_preauth(conn, "admin", billing.PreauthIn(encounter_id="E-IPD-07", requested_paise=1500000))
    billing.decide_preauth_core(conn, "admin", pa["preauth_id"], billing.PreauthDecisionIn(outcome="APPROVED"))
    _complete_all(conn, "E-IPD-07", rx)
    clinical.discharge(conn, "doctor2", "E-IPD-07")
    bill = billing.finalize_bill(conn, "admin", "E-IPD-07")
    claim = payer.submit_claim_core(conn, "admin", payer.ClaimIn(invoice_id=bill["invoice_id"],
                                    discharge_summary="Acute asthma, nebulised, stable at discharge."))
    payer.decide_claim_core(conn, "admin", claim["claim_id"], payer.ClaimDecisionIn(
        outcome="REJECTED", reason="Discharge summary missing SpO2 trend and nebulisation chart"))

    # 8. Rohan: self-pay admission, discharged, with a duplicate CBC charge -> pre-bill audit fails (correction demo).
    _visit(conn, "P-DEMO-08", "E-IPD-08")
    reception.take_deposit(conn, "reception", reception.AdvanceIn(encounter_id="E-IPD-08", amount_paise=500000, method="CARD"))
    rx = _consult(conn, "E-IPD-08", "doctor3", "Knee pain, osteoarthritis. Physiotherapy and observation.", "M17.9",
                  labs=["CBC"], procedures=["PHYSIO_OUT"], admit=clinical.AdmitIn(ward_id="W-SEMI"))
    _complete_all(conn, "E-IPD-08", rx)
    # A second HIS feed sends the same CBC again (manual capture, no completed order behind it).
    create_charge(conn, "doctor3", "E-IPD-08", "CBC", 1, "HIS:MANUAL-CBC-0808", source_type="HIS_EVENT")
    clinical.discharge(conn, "doctor3", "E-IPD-08")

    # 10. Sanjay: past self-pay OPD bill, 40 days old and unpaid (reminder demo).
    _visit(conn, "P-DEMO-10", "E-OPD-10")
    rx = _consult(conn, "E-OPD-10", "doctor", "Fever settled. Review complete.", "R50.9", labs=["URINE_RM"])
    _complete_all(conn, "E-OPD-10", rx)
    clinical.discharge(conn, "doctor", "E-OPD-10")
    billing.finalize_bill(conn, "admin", "E-OPD-10")
    _backdate_bill(conn, "E-OPD-10", 40)

    audit(conn, "system", "DEMO_SEEDED", "system", "synthetic", {"patients": len(PATIENTS)})

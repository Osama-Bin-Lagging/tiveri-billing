"""End-to-end API scenarios against a disposable PostgreSQL 16 database (all data synthetic)."""

from fastapi.testclient import TestClient
import pytest

from backend.app.main import app


def call(client, method, path, body=None, expected=200):
    result = client.request(method, path, json=body)
    assert result.status_code == expected, (path, result.status_code, result.text)
    return result.json()


def as_role(client, username):
    login = call(client, "POST", "/api/auth/login", {"username": username, "password": "Demo@1234"})
    client.headers.update({"Authorization": f"Bearer {login['token']}"})


@pytest.fixture()
def client():
    with TestClient(app) as c:
        as_role(c, "admin")
        call(c, "POST", "/api/demo/reset", {})
        yield c


def blocks(audit):
    return {f["rule"] for f in audit["findings"] if f["severity"] == "BLOCK"}


def test_a_self_pay_opd_full_workflow_with_payment_retry(client):
    as_role(client, "reception")
    patient = call(client, "POST", "/api/patients", {"display_label": "Test Patient A", "dob": "1990-01-15",
                   "sex": "Female", "abha_number": "12345678901234"})
    assert patient["abha_number"] == "12-3456-7890-1234" and patient["mrn"].startswith("MRN-")
    call(client, "POST", "/api/patients", {"display_label": "Dup", "dob": "1990-01-15", "abha_number": "12-3456-7890-1234"}, 409)
    appt = call(client, "POST", "/api/appointments", {"patient_id": patient["patient_id"], "doctor_id": "D-01",
                "slot_at": "2026-10-09T10:30:00+05:30", "reason": "Cough"})
    enc = call(client, "POST", f"/api/appointments/{appt['appointment_id']}/check-in", {"setting": "OPD", "payment_mode": "SELF"})
    eid = enc["encounter_id"]
    call(client, "POST", "/api/advances", {"encounter_id": eid, "amount_paise": 20000, "method": "CASH"})
    call(client, "POST", "/api/clinical/consultations", {"encounter_id": eid, "notes": "Doctor desk only"}, 403)

    as_role(client, "doctor")
    call(client, "POST", "/api/patients", {"display_label": "Nope", "dob": "1990-01-01"}, 403)
    call(client, "POST", "/api/clinical/prescriptions", {"encounter_id": eid, "icd_code": "J18.9", "labs": ["CBC"]}, 400)
    call(client, "POST", "/api/clinical/consultations", {"encounter_id": eid, "notes": "Cough and fever for four days."})
    call(client, "POST", "/api/clinical/prescriptions", {"encounter_id": eid, "icd_code": "XX.9", "labs": ["CBC"]}, 400)
    rx = call(client, "POST", "/api/clinical/prescriptions", {"encounter_id": eid, "icd_code": "J18.9", "labs": ["CBC"],
              "radiology": [{"service_code": "XRAY_CHEST", "clinical_notes": "Consolidation?"}],
              "medicines": [{"item_code": "MED-PCM", "quantity": 10, "instruction": "If fever"}]})
    assert rx["prescription"]["snomed_code"] == "233604007"

    as_role(client, "lab")
    lab = call(client, "POST", f"/api/lab/orders/{rx['lab_orders'][0]['lab_order_id']}/complete", {"result_value": 11.2})
    assert call(client, "POST", f"/api/lab/orders/{rx['lab_orders'][0]['lab_order_id']}/complete", {"result_value": 11.2})["duplicate"]
    call(client, "POST", f"/api/lab/orders/{rx['lab_orders'][0]['lab_order_id']}/complete", {"result_value": 9.0}, 409)
    assert lab["result"]["loinc_code"] == "58410-2"
    call(client, "POST", f"/api/radiology/orders/{rx['radiology_orders'][0]['rad_order_id']}/report",
         {"findings": "Right lower zone consolidation (synthetic)."})

    as_role(client, "pharmacy")
    call(client, "POST", "/api/pharmacy/dispense", {"pharm_order_id": rx["pharmacy_orders"][0]["pharm_order_id"],
         "quantity": 11, "source_event_id": "T-A-DISP-X"}, 400)
    call(client, "POST", "/api/pharmacy/dispense", {"pharm_order_id": rx["pharmacy_orders"][0]["pharm_order_id"],
         "quantity": 10, "source_event_id": "T-A-DISP"})

    as_role(client, "admin")
    assert "NOT_DISCHARGED" in blocks(call(client, "GET", f"/api/encounters/{eid}/audit"))
    call(client, "POST", "/api/invoices", {"encounter_id": eid}, 400)
    as_role(client, "doctor")
    call(client, "POST", f"/api/encounters/{eid}/discharge", {})
    as_role(client, "admin")
    assert call(client, "GET", f"/api/encounters/{eid}/audit")["passed"]
    bill = call(client, "POST", "/api/invoices", {"encounter_id": eid})
    # 500 consult + 790 CBC + 900 X-ray + 10 x 2 paracetamol (+5% OPD GST = 1) = 2,211.00
    assert bill["total_paise"] == 221100 and bill["tax_paise"] == 100
    detail = call(client, "GET", f"/api/encounters/{eid}")
    assert detail["patient_due_paise"] == 201100 and detail["deposit_used_paise"] == 20000
    upi = call(client, "POST", "/api/receipts", {"invoice_id": bill["invoice_id"], "payer_kind": "PATIENT",
               "amount_paise": 201100, "method": "UPI"})
    assert upi["status"] == "PENDING"
    call(client, "POST", "/api/receipts", {"invoice_id": bill["invoice_id"], "payer_kind": "PATIENT",
         "amount_paise": 1, "method": "CASH"}, 400)  # pending UPI already covers the due amount
    call(client, "POST", f"/api/receipts/{upi['receipt_id']}/outcome", {"outcome": "FAILED"})
    assert call(client, "GET", f"/api/encounters/{eid}")["patient_due_paise"] == 201100
    card = call(client, "POST", f"/api/receipts/{upi['receipt_id']}/retry", {"method": "CARD"})
    assert card["attempt_no"] == 2 and card["retry_of"] == upi["receipt_id"]
    call(client, "POST", f"/api/receipts/{card['receipt_id']}/outcome", {"outcome": "SUCCEEDED"})
    final = call(client, "GET", f"/api/encounters/{eid}")
    assert final["remaining_paise"] == 0 and final["payment_status"] == "PAID"
    kinds = {n["kind"] for n in call(client, "GET", f"/api/patients/{patient['patient_id']}")["notifications"]}
    assert {"APPOINTMENT", "SETTLED"} <= kinds
    call(client, "POST", f"/api/invoices/{bill['invoice_id']}/remind", {}, 400)


def test_b_cashless_admission_audit_correction_partial_claim(client):
    as_role(client, "reception")
    enc = call(client, "POST", "/api/encounters", {"patient_id": "P-DEMO-09", "setting": "OPD",
               "payment_mode": "CASHLESS", "policy_id": "POL-ALPHA-0109"})
    eid = enc["encounter_id"]
    call(client, "POST", "/api/encounters", {"patient_id": "P-DEMO-09", "setting": "OPD", "payment_mode": "SELF"}, 409)
    call(client, "POST", f"/api/coverage/{eid}/verify", {})

    as_role(client, "doctor")
    call(client, "POST", "/api/clinical/consultations", {"encounter_id": eid, "notes": "High glucose readings for two weeks."})
    rx = call(client, "POST", "/api/clinical/prescriptions", {"encounter_id": eid, "icd_code": "E11.9", "labs": ["HBA1C"],
              "medicines": [{"item_code": "MED-MET", "quantity": 10}], "admit": {"ward_id": "W-PVT"}})
    call(client, "POST", "/api/his/events", {"encounter_id": eid, "service_code": "HBA1C", "quantity": 1,
         "source_event_id": "T-B-MANUAL-HBA1C"})

    as_role(client, "admin")
    pre = call(client, "POST", "/api/preauth", {"encounter_id": eid, "requested_paise": 1000000})
    call(client, "POST", f"/api/preauth/{pre['preauth_id']}/decision", {"outcome": "APPROVED"})
    as_role(client, "lab")
    call(client, "POST", f"/api/lab/orders/{rx['lab_orders'][0]['lab_order_id']}/complete", {"result_value": 8.1})
    as_role(client, "pharmacy")
    disp = call(client, "POST", "/api/pharmacy/dispense", {"pharm_order_id": rx["pharmacy_orders"][0]["pharm_order_id"],
                "quantity": 10, "source_event_id": "T-B-DISP"})
    assert disp["charge"]["tax_rate_bps"] == 0  # inpatient medicine: part of exempt care
    as_role(client, "doctor")
    call(client, "POST", f"/api/encounters/{eid}/discharge", {})

    as_role(client, "admin")
    audit = call(client, "GET", f"/api/encounters/{eid}/audit")
    dup = [f for f in audit["findings"] if f["rule"] == "DUPLICATE_OR_UNSUPPORTED"]
    assert len(dup) == 1 and not audit["passed"]
    call(client, "POST", "/api/invoices", {"encounter_id": eid}, 400)
    call(client, "POST", f"/api/charges/{dup[0]['charge_id']}/reverse", {"reason": "Duplicate HIS feed"})
    call(client, "POST", f"/api/charges/{dup[0]['charge_id']}/reverse", {"reason": "Duplicate HIS feed"}, 409)
    assert call(client, "GET", f"/api/encounters/{eid}/audit")["passed"]
    bill = call(client, "POST", "/api/invoices", {"encounter_id": eid})
    # Alpha rate consult 430 + HbA1c 650 + metformin 60 + private room 6,000 (+5% = 300) = 7,440.00
    assert bill["total_paise"] == 744000 and bill["patient_share_paise"] == 0 and bill["payer_share_paise"] == 744000
    detail = call(client, "GET", f"/api/encounters/{eid}")
    assert sum(l["total_paise"] for l in detail["invoice_lines"]) == bill["total_paise"]
    assert any(l["charge_type"] == "REVERSAL" and l["total_paise"] < 0 for l in detail["invoice_lines"])

    claim = call(client, "POST", "/api/claims", {"invoice_id": bill["invoice_id"]})
    assert claim["diagnosis_code"] == "E11.9" and claim["submitted_paise"] == 744000
    call(client, "POST", f"/api/claims/{claim['claim_id']}/decision", {"outcome": "PARTIAL", "approved_paise": 600000}, 400)
    call(client, "POST", f"/api/claims/{claim['claim_id']}/decision",
         {"outcome": "PARTIAL", "approved_paise": 600000, "reason": "Room rent above policy room limit"})
    call(client, "POST", "/api/receipts", {"invoice_id": bill["invoice_id"], "payer_kind": "INSURER",
         "amount_paise": 600001, "method": "TRANSFER"}, 400)
    call(client, "POST", "/api/receipts", {"invoice_id": bill["invoice_id"], "payer_kind": "INSURER",
         "amount_paise": 600000, "method": "TRANSFER"})
    call(client, "POST", f"/api/invoices/{bill['invoice_id']}/shortfall", {"action": "TO_PATIENT"})
    detail = call(client, "GET", f"/api/encounters/{eid}")
    assert detail["patient_due_paise"] == 144000 and detail["payer_due_paise"] == 0
    reminder = call(client, "POST", f"/api/invoices/{bill['invoice_id']}/remind", {})
    assert "1,440.00" in reminder["message"]
    call(client, "POST", "/api/receipts", {"invoice_id": bill["invoice_id"], "payer_kind": "PATIENT",
         "amount_paise": 144000, "method": "CASH"})
    assert call(client, "GET", f"/api/encounters/{eid}")["payment_status"] == "PAID"


def test_c_rejected_claim_resubmitted_then_approved(client):
    as_role(client, "admin")
    detail = call(client, "GET", "/api/encounters/E-IPD-07")
    rejected = detail["claims"][-1]
    assert rejected["status"] == "REJECTED"
    call(client, "POST", "/api/claims", {"invoice_id": detail["invoice"]["invoice_id"]}, 409)
    second = call(client, "POST", f"/api/claims/{rejected['claim_id']}/resubmit",
                  {"correction_note": "Attached SpO2 trend and nebulisation chart."})
    assert second["attempt_no"] == 2 and second["parent_claim_id"] == rejected["claim_id"]
    call(client, "POST", f"/api/claims/{second['claim_id']}/decision", {"outcome": "APPROVED"})
    call(client, "POST", "/api/receipts", {"invoice_id": detail["invoice"]["invoice_id"], "payer_kind": "INSURER",
         "amount_paise": second["submitted_paise"], "method": "TRANSFER"})
    final = call(client, "GET", "/api/encounters/E-IPD-07")
    assert final["remaining_paise"] == 0 and len(final["claims"]) == 2


def test_d_pmjay_package_keeps_original_prices(client):
    as_role(client, "admin")
    before = call(client, "GET", "/api/encounters/E-IPD-03")
    adj = [c for c in before["charges"] if c["charge_type"] == "PACKAGE_ADJ"]
    assert adj and all(c["unit_price_paise"] > 0 and c["subtotal_paise"] < 0 for c in adj)
    as_role(client, "doctor")
    call(client, "POST", "/api/encounters/E-IPD-03/discharge", {}, 400)  # ORS order still pending
    as_role(client, "pharmacy")
    ors = next(o for o in before["pharmacy_orders"] if o["item_code"] == "MED-ORS")
    call(client, "POST", "/api/pharmacy/dispense", {"pharm_order_id": ors["pharm_order_id"], "quantity": 6,
         "source_event_id": "T-D-ORS"})
    as_role(client, "doctor")
    call(client, "POST", "/api/encounters/E-IPD-03/discharge", {})
    as_role(client, "admin")
    assert call(client, "GET", "/api/encounters/E-IPD-03/audit")["passed"]
    bill = call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-03"})
    assert bill["total_paise"] == 1200000 and bill["patient_share_paise"] == 0
    call(client, "POST", "/api/receipts", {"invoice_id": bill["invoice_id"], "payer_kind": "PATIENT",
         "amount_paise": 100, "method": "CASH"}, 400)


def test_his_events_cannot_bypass_desks_or_squat_event_ids(client):
    as_role(client, "doctor")
    detail = call(client, "GET", "/api/encounters/E-OPD-01")
    ns1 = next(o for o in detail["lab_orders"] if o["status"] == "ORDERED")
    for code in ("MED_PCM", "PMJAY_PKG", "WARD_PRIVATE"):
        call(client, "POST", "/api/his/events", {"encounter_id": "E-OPD-01", "service_code": code, "quantity": 1,
             "source_event_id": f"T-BYPASS-{code}"}, 400)
    # Try to pre-claim the ID the lab desk will use for this order.
    squat = call(client, "POST", "/api/his/events", {"encounter_id": "E-OPD-01", "service_code": "DENGUE_NS1",
                 "quantity": 1, "source_event_id": f"LAB-ORDER-{ns1['lab_order_id']}"})
    assert squat["charge"]["source_event_id"].startswith("HIS:")
    as_role(client, "lab")
    done = call(client, "POST", f"/api/lab/orders/{ns1['lab_order_id']}/complete", {"result_value": 1.2})
    assert not done["duplicate"] and done["charge"]["charge_id"] != squat["charge"]["charge_id"]


def test_cancelled_order_is_not_charged(client):
    as_role(client, "doctor")
    detail = call(client, "GET", "/api/encounters/E-OPD-01")
    ns1 = next(o for o in detail["lab_orders"] if o["status"] == "ORDERED")
    call(client, "POST", "/api/clinical/orders/cancel", {"kind": "LAB", "order_id": ns1["lab_order_id"],
         "reason": "Patient declined the test"})
    pcm = detail["pharmacy_orders"][0]
    call(client, "POST", "/api/clinical/orders/cancel", {"kind": "PHARMACY", "order_id": pcm["pharm_order_id"],
         "reason": "Patient has paracetamol at home"})
    call(client, "POST", "/api/encounters/E-OPD-01/discharge", {})
    as_role(client, "admin")
    assert call(client, "GET", "/api/encounters/E-OPD-01/audit")["passed"]
    assert call(client, "POST", "/api/invoices", {"encounter_id": "E-OPD-01"})["total_paise"] == 50000 + 79000


def test_e_seeded_audit_case_and_deposit(client):
    as_role(client, "admin")
    audit = call(client, "GET", "/api/encounters/E-IPD-08/audit")
    assert blocks(audit) == {"DUPLICATE_OR_UNSUPPORTED"}
    charge_id = next(f["charge_id"] for f in audit["findings"] if f["charge_id"])
    call(client, "POST", f"/api/charges/{charge_id}/reverse", {"reason": "Same CBC sent twice by the HIS feed"})
    bill = call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-08"})
    # specialist 750 + CBC 790 + outsourced physio 1,200 + semi-private 4,000 = 6,740; deposit 5,000 applied
    detail = call(client, "GET", "/api/encounters/E-IPD-08")
    assert bill["total_paise"] == 674000 and detail["patient_due_paise"] == 174000
    assert any("Outsourced" in p["outcome_notes"] for p in detail["procedure_orders"])


def test_f_pending_payment_timeout_and_overdue_reminder(client):
    as_role(client, "admin")
    manoj = call(client, "GET", "/api/encounters/E-OPD-06")
    pending = manoj["receipts"][0]
    assert pending["status"] == "PENDING" and manoj["invoice"]["tax_paise"] > 0  # OPD medicine at 5%
    call(client, "POST", f"/api/receipts/{pending['receipt_id']}/outcome", {"outcome": "TIMEOUT"})
    retry = call(client, "POST", f"/api/receipts/{pending['receipt_id']}/retry", {"method": "CASH"})
    assert retry["status"] == "SUCCEEDED"
    assert call(client, "GET", "/api/encounters/E-OPD-06")["remaining_paise"] == 0
    sanjay = call(client, "GET", "/api/encounters/E-OPD-10")
    call(client, "POST", f"/api/invoices/{sanjay['invoice']['invoice_id']}/remind", {})
    ar = call(client, "GET", "/api/ar")
    assert any(r["encounter_id"] == "E-OPD-10" and r["age_bucket"] == "days_31_60" for r in ar["rows"])


def test_g_data_map_covers_every_er_entity(client):
    as_role(client, "pharmacy")
    schema = call(client, "GET", "/api/datamap/schema")
    names = {e["er_name"] for e in schema["entities"]}
    assert {"Patient", "Registration", "Doctor", "Consultation", "Prescription", "Ward", "Radiology Order",
            "Lab Order", "Pharmacy Order", "Procedure Order", "Radiology Result", "Lab Result", "Medication Issue",
            "Procedure Performed", "Bill", "Charge", "Payment", "Insurance", "Insurance Claim",
            "Service", "Payer Rate"} <= names
    charge = next(e for e in schema["entities"] if e["key"] == "charge")
    assert any(a["name"] == "service_code" and a["fk"]["entity"] == "service" for a in charge["attributes"])
    assert any(a["name"] == "invoice_id" and a["fk"]["entity"] == "bill" for a in charge["attributes"])
    assert not names & {"Bill Line", "Tax Rule"}  # not in the team's ER diagram
    data = call(client, "GET", "/api/datamap/P-DEMO-02")
    counts = {k: v["count"] for k, v in data["entities"].items()}
    assert counts["registration"] == 1 and counts["bill"] == 1 and counts["claim"] == 1 and counts["lab_result"] == 2
    assert counts["radiology_result"] == 1 and counts["admits"] == 1 and counts["ward"] == 1 and counts["insurance"] == 1
    assert data["timeline"] and all(e["actor"] for e in data["timeline"])
    assert all(r["invoice_id"] for r in data["entities"]["charge"]["rows"])  # every charge on Dev's bill
    assert all("gst_rate_bps" in r and "hsn_sac" in r for r in data["entities"]["service"]["rows"])


def test_h_reports_and_reference_reads(client):
    as_role(client, "admin")
    for path in ("/api/dashboard", "/api/gstr1", "/api/analytics", "/api/audit", "/api/catalog", "/api/patients",
                 "/api/appointments", "/api/diagnostics/queue", "/api/pharmacy/queue", "/api/pharmacy/stock"):
        call(client, "GET", path)
    gst = call(client, "GET", "/api/gstr1")
    assert gst["tables"]["table4"]  # corporate B2B bill with a taxable OPD medicine line
    assert call(client, "GET", "/api/health")["schema_version"] == 2


def test_contact_is_ten_digits_and_stored_masked_and_short_notes_are_allowed(client):
    as_role(client, "reception")
    base = {"display_label": "Contact Test", "dob": "1995-05-05"}
    for bad in ("98765", "98765abc12", "+919876543210"):
        call(client, "POST", "/api/patients", {**base, "contact": bad}, 400 if len(bad) <= 10 else 422)
    patient = call(client, "POST", "/api/patients", {**base, "contact": "9876543210"})
    assert patient["contact_masked"] == "9XXXXX3210"
    enc = call(client, "POST", "/api/encounters", {"patient_id": patient["patient_id"], "setting": "OPD", "payment_mode": "SELF"})
    as_role(client, "doctor")
    call(client, "POST", "/api/clinical/consultations", {"encounter_id": enc["encounter_id"], "notes": "ok"})


def test_removing_a_package_restores_the_original_bill(client):
    as_role(client, "admin")
    before = call(client, "GET", "/api/encounters/E-IPD-03")
    pkg = next(c for c in before["charges"] if c["kind"] == "PACKAGE" and c["charge_type"] == "CHARGE")
    absorbed = [c for c in before["charges"] if c["charge_type"] == "PACKAGE_ADJ"]
    assert absorbed
    call(client, "POST", f"/api/charges/{pkg['charge_id']}/reverse", {"reason": "Wrong package"})
    after = call(client, "GET", "/api/encounters/E-IPD-03")
    restored = [c for c in after["charges"] if c["source_type"] == "REPOST"]
    assert sorted(c["service_code"] for c in restored) == sorted(c["service_code"] for c in absorbed)
    # Total is back to the sum of the original item prices (package line and its reversal cancel out).
    items = sum(c["quantity"] * c["unit_price_paise"] for c in absorbed)
    assert sum(c["subtotal_paise"] for c in after["charges"]) == items
    # The package can be applied again, and its new offsets absorb the restored copies.
    call(client, "POST", "/api/packages/apply", {"encounter_id": "E-IPD-03", "package_code": "HBP-DEMO-01"})
    again = call(client, "GET", "/api/encounters/E-IPD-03")
    assert sum(c["subtotal_paise"] for c in again["charges"]) == sum(c["subtotal_paise"] for c in before["charges"])


def test_data_map_timeline_lists_each_event_once(client):
    as_role(client, "admin")
    for pid in ("P-DEMO-01", "P-DEMO-02", "P-DEMO-03"):
        ids = [t["audit_id"] for t in call(client, "GET", f"/api/datamap/{pid}")["timeline"]]
        assert len(ids) == len(set(ids))

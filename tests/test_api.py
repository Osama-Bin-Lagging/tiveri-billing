"""End-to-end API scenarios against the local PostgreSQL demo database."""

from fastapi.testclient import TestClient
from backend.app.main import app


def call(client, method, path, body=None, expected=200):
    result = client.request(method, path, json=body)
    assert result.status_code == expected, (path, result.status_code, result.text)
    return result.json()


def as_role(client, username):
    login = call(client, "POST", "/api/auth/login", {"username": username, "password": "Demo@1234"})
    client.headers.update({"Authorization": f"Bearer {login['token']}"})


def test_small_hospital_workflows():
    with TestClient(app) as client:
        as_role(client, "admin")
        call(client, "POST", "/api/demo/reset", {})
        as_role(client, "admin")
        assert call(client, "GET", "/api/health")["database"] == "postgresql"
        assert call(client, "GET", "/api/dashboard")["open_encounters"] == 6

        # OPD: idempotent HIS capture, stock-linked pharmacy, advance and patient receipt.
        event = {"encounter_id": "E-OPD-01", "service_code": "XRAY", "quantity": 1, "source_event_id": "TEST-XRAY-1"}
        as_role(client, "doctor")
        assert call(client, "POST", "/api/his/events", event)["duplicate"] is False
        assert call(client, "POST", "/api/his/events", event)["duplicate"] is True
        call(client, "POST", "/api/his/events", {**event, "quantity": 2}, 409)
        stock_before = next(i for i in call(client, "GET", "/api/pharmacy/stock")["items"] if i["item_code"] == "MED-A")["available_units"]
        rx = {"encounter_id": "E-OPD-01", "item_code": "MED-A", "quantity": 2,
              "source_event_id": "TEST-RX-1", "prescription_ref": "RX-DEMO-01"}
        as_role(client, "pharmacy")
        assert call(client, "POST", "/api/pharmacy/dispense", rx)["duplicate"] is False
        assert call(client, "POST", "/api/pharmacy/dispense", rx)["duplicate"] is True
        assert next(i for i in call(client, "GET", "/api/pharmacy/stock")["items"] if i["item_code"] == "MED-A")["available_units"] == stock_before - 2
        as_role(client, "admin")
        call(client, "POST", "/api/advances", {"encounter_id": "E-OPD-01", "amount_paise": 10000, "method": "UPI"})
        opd = call(client, "POST", "/api/invoices", {"encounter_id": "E-OPD-01"})
        assert opd["tax_paise"] == 1000  # two synthetic medicines, 5% demo tax
        assert opd["advance_allocated_paise"] == 10000
        due = opd["total_paise"] - opd["advance_allocated_paise"]
        call(client, "POST", "/api/receipts", {"invoice_id": opd["invoice_id"], "payer_kind": "PATIENT", "amount_paise": due, "method": "UPI"})
        assert call(client, "GET", "/api/encounters/E-OPD-01")["remaining_paise"] == 0

        # Private TPA IPD: preauth, immutable invoice, document checklist, approval, then cash receipt.
        call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-02"}, 400)
        pre = call(client, "POST", "/api/preauth", {"encounter_id": "E-IPD-02", "requested_paise": 1500000})
        call(client, "POST", f"/api/preauth/{pre['preauth_id']}/decision", {"approved_paise": 1500000, "reference_no": "SYN-PRE-2"})
        tpa_inv = call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-02"})
        claim = call(client, "POST", "/api/claims", {"invoice_id": tpa_inv["invoice_id"],
            "discharge_summary": "Synthetic inpatient discharge summary",
            "documents": {"itemised_bill": True, "discharge_summary": True}})
        assert claim["diagnosis_code"] == "Z00.0"
        call(client, "POST", f"/api/claims/{claim['claim_id']}/decision", {"approved_paise": tpa_inv["total_paise"], "reference_no": "SYN-CLM-2"})
        call(client, "POST", "/api/receipts", {"invoice_id": tpa_inv["invoice_id"], "payer_kind": "INSURER", "amount_paise": tpa_inv["total_paise"], "method": "TRANSFER"})

        # PM-JAY: simulated eligibility, package, zero patient collection.
        call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-03"}, 400)
        call(client, "POST", "/api/coverage/E-IPD-03/verify", {"member_ref": "SYN-AB-03"})
        pre3 = call(client, "POST", "/api/preauth", {"encounter_id": "E-IPD-03", "requested_paise": 1200000})
        call(client, "POST", f"/api/preauth/{pre3['preauth_id']}/decision", {"approved_paise": 1200000})
        pm_inv = call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-03"})
        call(client, "POST", "/api/receipts", {"invoice_id": pm_inv["invoice_id"], "payer_kind": "PATIENT", "amount_paise": 100, "method": "CASH"}, 400)
        pm_claim = call(client, "POST", "/api/claims", {"invoice_id": pm_inv["invoice_id"],
            "discharge_summary": "Synthetic scheme discharge summary",
            "documents": {"itemised_bill": True, "discharge_summary": True}})
        call(client, "POST", f"/api/claims/{pm_claim['claim_id']}/decision", {"approved_paise": pm_inv["total_paise"]})
        call(client, "POST", "/api/receipts", {"invoice_id": pm_inv["invoice_id"], "payer_kind": "SCHEME", "amount_paise": pm_inv["total_paise"], "method": "TRANSFER"})

        # Reports include exempt lines, taxable HSN and an aged historic TPA balance.
        period = opd["issued_at"][:7]
        gstr = call(client, "GET", f"/api/gstr1?month={period}")
        assert gstr["tables"]["table7"]
        assert gstr["tables"]["table8"]
        assert gstr["tables"]["table12"]
        assert "Review packet" in gstr["warnings"][0]
        ar = call(client, "GET", "/api/ar")
        assert ar["totals"]["days_31_60"] > 0
        assert call(client, "GET", f"/api/analytics?month={period}")["revenue_paise"] > 0
        assert call(client, "GET", "/api/audit")["events"]


def test_rates_rooms_packages_and_credit():
    with TestClient(app) as client:
        as_role(client, "admin")
        call(client, "POST", "/api/demo/reset", {})
        as_role(client, "admin")
        call(client, "POST", "/api/rates", {"service_code": "CONSULT", "payer_route": "PRIVATE", "payer_label": "Alpha TPA", "unit_paise": 42000})
        new = call(client, "POST", "/api/encounters", {"display_label": "Synthetic Patient X", "setting": "IPD", "payer_route": "SELF"})
        eid = new["encounter_id"]
        stay = call(client, "POST", f"/api/encounters/{eid}/room-stays", {"room_code": "PRIVATE_ROOM", "start_date": "2026-10-01", "end_date": "2026-10-03"})
        assert stay["charges"][0]["quantity"] == 2
        assert stay["charges"][0]["tax_rate_bps"] == 500
        call(client, "POST", f"/api/encounters/{eid}/room-stays", {"room_code": "WARD", "start_date": "2026-10-02", "end_date": "2026-10-04"}, 409)
        call(client, "POST", "/api/advances", {"encounter_id": eid, "amount_paise": 2000000, "method": "CARD"})
        inv = call(client, "POST", "/api/invoices", {"encounter_id": eid})
        assert inv["tax_paise"] == 60000
        assert inv["advance_allocated_paise"] == inv["total_paise"]
        refund = 2000000 - inv["total_paise"]
        call(client, "POST", "/api/refunds", {"encounter_id": eid, "amount_paise": refund, "method": "CARD"})
        call(client, "POST", "/api/refunds", {"encounter_id": eid, "amount_paise": 1, "method": "CARD"}, 400)
        day = call(client, "POST", "/api/encounters", {"display_label": "Synthetic Patient Y", "setting": "DAY_CARE", "payer_route": "SELF"})
        deid = day["encounter_id"]
        as_role(client, "doctor")
        call(client, "POST", "/api/his/events", {"encounter_id": deid, "service_code": "CBC", "quantity": 1, "source_event_id": "TEST-DAY-CBC"})
        as_role(client, "admin")
        call(client, "POST", "/api/packages/apply", {"encounter_id": deid, "package_code": "DAY-DEMO-01"})
        charges = call(client, "GET", f"/api/encounters/{deid}")["charges"]
        assert any(c["included_in_package"] and c["subtotal_paise"] == 0 for c in charges)
        assert call(client, "POST", "/api/invoices", {"encounter_id": deid})["total_paise"] == 600000


def test_staff_handoffs_and_tax_examples():
    with TestClient(app) as client:
        as_role(client, "admin")
        call(client, "POST", "/api/demo/reset", {})
        as_role(client, "admin")
        patient = call(client, "GET", "/api/encounters/E-OPD-01")
        assert patient["patient"]["history_summary"]
        assert patient["clinical_notes"][0]["provisional_icd_code"] == "R50.9"
        assert "staff_users" not in call(client, "GET", "/api/bootstrap")
        call(client, "POST", "/api/clinical/notes", {"encounter_id": "E-OPD-01", "note_text": "This action belongs to a doctor"}, 403)

        as_role(client, "doctor")
        call(client, "POST", "/api/clinical/notes", {"encounter_id": "E-OPD-01",
            "note_text": "Fever reviewed and follow-up explained", "provisional_icd_code": "R50.9",
            "procedure_code": "CBC"})
        rx = call(client, "POST", "/api/clinical/prescriptions", {"encounter_id": "E-OPD-05",
            "item_code": "MED-N", "quantity": 1, "instruction": "Training example only"})
        call(client, "POST", "/api/auth/login", {"username": "coder", "password": "Demo@1234"}, 401)

        as_role(client, "pharmacy")
        disp = call(client, "POST", "/api/pharmacy/dispense", {"encounter_id": "E-OPD-05",
            "item_code": "MED-N", "quantity": 1, "prescription_ref": rx["prescription_ref"],
            "source_event_id": "TEST-NIL-MED"})
        assert disp["charge"]["tax_category"] == "NIL"
        assert disp["charge"]["tax_rate_bps"] == 0
        call(client, "POST", "/api/pharmacy/dispense", {"encounter_id": "E-OPD-05",
            "item_code": "MED-N", "quantity": 1, "prescription_ref": rx["prescription_ref"],
            "source_event_id": "TEST-NIL-OVER"}, 400)

        as_role(client, "admin")
        nil_invoice = call(client, "POST", "/api/invoices", {"encounter_id": "E-OPD-05"})
        nil_period = nil_invoice["issued_at"][:7]
        tax_review = call(client, "GET", f"/api/gstr1?month={nil_period}")
        assert any(group["category"] == "NIL" for group in tax_review["tables"]["table8"])
        as_role(client, "doctor")
        ipd_rx = call(client, "POST", "/api/clinical/prescriptions", {"encounter_id": "E-IPD-08",
            "item_code": "MED-A", "quantity": 1, "instruction": "Synthetic inpatient order"})
        as_role(client, "pharmacy")
        ipd_disp = call(client, "POST", "/api/pharmacy/dispense", {"encounter_id": "E-IPD-08",
            "item_code": "MED-A", "quantity": 1, "prescription_ref": ipd_rx["prescription_ref"],
            "source_event_id": "TEST-IPD-MED"})
        assert ipd_disp["charge"]["tax_category"] == "EXEMPT"
        assert ipd_disp["charge"]["tax_rate_bps"] == 0
        as_role(client, "admin")
        room = call(client, "POST", "/api/encounters/E-IPD-08/room-stays", {"room_code": "PRIVATE_ROOM",
            "start_date": "2026-10-07", "end_date": "2026-10-08"})
        assert room["charges"][0]["tax_rate_bps"] == 500


def test_doctor_lab_pharmacy_invoice_handoff():
    with TestClient(app) as client:
        as_role(client, "admin")
        call(client, "POST", "/api/demo/reset", {})
        as_role(client, "admin")
        directory = call(client, "GET", "/api/patients")["patients"]
        patient = next(row for row in directory if row["patient_id"] == "P-DEMO-09")
        assert patient["latest_encounter_id"] is None
        start = {"patient_id": "P-DEMO-09", "case_code": "DIABETES_OBSERVATION",
                 "note_text": "Known type 2 diabetes without documented complications; inpatient assessment completed.",
                 "medicine_item_code": "MED-M", "medicine_quantity": 10}
        call(client, "POST", "/api/clinical/demo-encounters", start, 403)
        as_role(client, "doctor")
        visit = call(client, "POST", "/api/clinical/demo-encounters", start)
        eid = visit["encounter_id"]
        assert visit["note"]["provisional_icd_code"] == "E11.9"
        assert visit["note"]["procedure_code"] == "83036"
        assert visit["consultation_charge"]["subtotal_paise"] == 50000
        call(client, "POST", "/api/clinical/demo-encounters", start, 409)
        before = call(client, "GET", f"/api/encounters/{eid}")
        assert before["encounter"]["setting"] == "IPD"
        assert len(before["charges"]) == 1
        assert before["lab_orders"][0]["loinc_code"] == "4548-4"
        order_id = before["lab_orders"][0]["lab_order_id"]
        call(client, "POST", f"/api/lab/orders/{order_id}/complete", {"result_value": 7.2}, 403)

        as_role(client, "lab")
        assert any(order["lab_order_id"] == order_id for order in call(client, "GET", "/api/lab/queue")["orders"])
        completed = call(client, "POST", f"/api/lab/orders/{order_id}/complete", {"result_value": 7.2})
        assert completed["charge"]["service_code"] == "HBA1C"
        assert completed["charge"]["subtotal_paise"] == 65000
        assert call(client, "POST", f"/api/lab/orders/{order_id}/complete", {"result_value": 7.2})["duplicate"]
        call(client, "POST", f"/api/lab/orders/{order_id}/complete", {"result_value": 7.3}, 409)

        as_role(client, "pharmacy")
        prescription = visit["prescription"]
        dispensed = call(client, "POST", "/api/pharmacy/dispense", {
            "encounter_id": eid, "item_code": "MED-M", "quantity": 10,
            "prescription_ref": prescription["prescription_ref"], "source_event_id": "TEST-METFORMIN-DISPENSE"})
        assert dispensed["charge"]["tax_rate_bps"] == 0
        assert dispensed["charge"]["subtotal_paise"] == 6000
        detail = call(client, "GET", f"/api/encounters/{eid}")
        assert {charge["service_code"] for charge in detail["charges"]} == {"CONSULT", "HBA1C", "MED_M"}
        assert detail["running_total_paise"] == 121000

        as_role(client, "admin")
        stay = call(client, "POST", f"/api/encounters/{eid}/room-stays", {
            "room_code": "PRIVATE_ROOM", "start_date": "2026-10-08", "end_date": "2026-10-09"})
        assert stay["charges"][0]["tax_rate_bps"] == 500
        assert stay["charges"][0]["subtotal_paise"] == 600000
        invoice = call(client, "POST", "/api/invoices", {"encounter_id": eid})
        assert invoice["total_paise"] == 751000
        final = call(client, "GET", f"/api/encounters/{eid}")
        assert len(final["invoice_lines"]) == 4
        assert final["lab_orders"][0]["status"] == "COMPLETED"

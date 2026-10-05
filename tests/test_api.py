"""End-to-end API scenarios against the local PostgreSQL demo database."""

from fastapi.testclient import TestClient
from backend.app.main import app


def call(client, method, path, body=None, expected=200):
    result = client.request(method, path, json=body)
    assert result.status_code == expected, (path, result.status_code, result.text)
    return result.json()


def test_small_hospital_workflows():
    with TestClient(app) as client:
        call(client, "POST", "/api/demo/reset", {})
        assert call(client, "GET", "/api/health")["database"] == "postgresql"
        assert call(client, "GET", "/api/dashboard")["open_encounters"] == 5

        # OPD: idempotent HIS capture, stock-linked pharmacy, advance and patient receipt.
        event = {"encounter_id": "E-OPD-01", "service_code": "XRAY", "quantity": 1, "source_event_id": "TEST-XRAY-1"}
        assert call(client, "POST", "/api/his/events", event)["duplicate"] is False
        assert call(client, "POST", "/api/his/events", event)["duplicate"] is True
        call(client, "POST", "/api/his/events", {**event, "quantity": 2}, 409)
        stock_before = next(i for i in call(client, "GET", "/api/pharmacy/stock")["items"] if i["item_code"] == "MED-A")["available_units"]
        rx = {"encounter_id": "E-OPD-01", "item_code": "MED-A", "quantity": 2,
              "source_event_id": "TEST-RX-1", "prescription_ref": "RX-001"}
        assert call(client, "POST", "/api/pharmacy/dispense", rx)["duplicate"] is False
        assert call(client, "POST", "/api/pharmacy/dispense", rx)["duplicate"] is True
        assert next(i for i in call(client, "GET", "/api/pharmacy/stock")["items"] if i["item_code"] == "MED-A")["available_units"] == stock_before - 2
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
        claim = call(client, "POST", "/api/claims", {"invoice_id": tpa_inv["invoice_id"], "diagnosis_code": "Z00",
            "discharge_summary": "Synthetic inpatient discharge summary", "documents": {"itemised_bill": True, "discharge_summary": True}})
        call(client, "POST", f"/api/claims/{claim['claim_id']}/decision", {"approved_paise": tpa_inv["total_paise"], "reference_no": "SYN-CLM-2"})
        call(client, "POST", "/api/receipts", {"invoice_id": tpa_inv["invoice_id"], "payer_kind": "INSURER", "amount_paise": tpa_inv["total_paise"], "method": "TRANSFER"})

        # PM-JAY: simulated eligibility, package, zero patient collection.
        call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-03"}, 400)
        call(client, "POST", "/api/coverage/E-IPD-03/verify", {"member_ref": "SYN-AB-03"})
        pre3 = call(client, "POST", "/api/preauth", {"encounter_id": "E-IPD-03", "requested_paise": 1200000})
        call(client, "POST", f"/api/preauth/{pre3['preauth_id']}/decision", {"approved_paise": 1200000})
        pm_inv = call(client, "POST", "/api/invoices", {"encounter_id": "E-IPD-03"})
        call(client, "POST", "/api/receipts", {"invoice_id": pm_inv["invoice_id"], "payer_kind": "PATIENT", "amount_paise": 100, "method": "CASH"}, 400)
        pm_claim = call(client, "POST", "/api/claims", {"invoice_id": pm_inv["invoice_id"], "diagnosis_code": "Z00",
            "discharge_summary": "Synthetic scheme discharge summary", "documents": {"itemised_bill": True, "discharge_summary": True}})
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
        call(client, "POST", "/api/demo/reset", {})
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
        call(client, "POST", "/api/his/events", {"encounter_id": deid, "service_code": "CBC", "quantity": 1, "source_event_id": "TEST-DAY-CBC"})
        call(client, "POST", "/api/packages/apply", {"encounter_id": deid, "package_code": "DAY-DEMO-01"})
        charges = call(client, "GET", f"/api/encounters/{deid}")["charges"]
        assert any(c["included_in_package"] and c["subtotal_paise"] == 0 for c in charges)
        assert call(client, "POST", "/api/invoices", {"encounter_id": deid})["total_paise"] == 600000

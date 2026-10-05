"""HTTP and SQLite integration checks for the teaching prototype."""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BillingApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp.name) / "integration.sqlite3"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = os.environ.copy()
        env["TIVERI_DB"] = str(cls.db_path)
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "backend" / "server.py"), "--port", str(cls.port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with urllib.request.urlopen(cls.base + "/api/health", timeout=1) as response:
                    if json.load(response)["ok"]:
                        break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError("Test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        self.post("/api/demo/reset", {})

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, json.load(response)

    def post(self, path, body):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_initial_cases_and_payer_price_snapshot(self):
        _, state = self.get("/api/state")
        self.assertEqual(len(state["encounter"]), 5)
        self.assertEqual(len(state["charge"]), 7)
        private = [row for row in state["charge"] if row["encounter_id"] == "E-IPD-02"]
        self.assertEqual(sum(row["amount_paise"] for row in private), 1310000)
        self.assertEqual(next(row for row in private if row["service_code"] == "BED")["unit_price_paise"], 230000)

    def test_self_pay_event_retry_invoice_lock_and_receipt_limit(self):
        code, created = self.post("/api/encounters", {"display_label": "Demo Patient Test", "setting": "OPD", "payer_route": "SELF"})
        self.assertEqual(code, 201)
        event = {"source_event_id": "HIS-TEST-001", "encounter_id": created["encounter_id"], "service_code": "CONSULT", "quantity": 1}
        self.assertEqual(self.post("/api/his/events", event)[0], 201)
        code, duplicate = self.post("/api/his/events", event)
        self.assertEqual((code, duplicate["duplicate"]), (200, True))
        self.assertEqual(self.post("/api/his/events", {**event, "quantity": 2})[0], 409)
        code, invoice = self.post("/api/invoices", {"encounter_id": created["encounter_id"]})
        self.assertEqual((code, invoice["total_paise"]), (201, 50000))
        self.assertEqual(self.post("/api/invoices", {"encounter_id": created["encounter_id"]})[0], 409)
        self.assertEqual(self.post("/api/his/events", {**event, "source_event_id": "HIS-TEST-002"})[0], 409)
        self.assertEqual(self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "PATIENT", "amount_paise": 60000, "method": "UPI"})[0], 400)
        code, receipt = self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "PATIENT", "amount_paise": 50000, "method": "UPI"})
        self.assertEqual((code, receipt["remaining_paise"]), (201, 0))

    def test_private_preauth_claim_and_actual_receipt(self):
        code, auth = self.post("/api/preauth", {"encounter_id": "E-IPD-02", "coverage_id": "C-DEMO-02", "requested_paise": 1400000})
        self.assertEqual(code, 201)
        self.assertEqual(self.post("/api/preauth/" + str(auth["preauth_id"]) + "/decision", {"approved_paise": 1400000})[0], 201)
        _, invoice = self.post("/api/invoices", {"encounter_id": "E-IPD-02"})
        code, claim = self.post("/api/claims", {"invoice_id": invoice["invoice_id"], "coverage_id": "C-DEMO-02"})
        self.assertEqual(code, 201)
        self.assertEqual(self.post("/api/claims/" + str(claim["claim_id"]) + "/decision", {"approved_paise": 1000000})[0], 201)
        _, state = self.get("/api/state")
        self.assertFalse(any(row["invoice_id"] == invoice["invoice_id"] for row in state["payment"]))
        self.assertEqual(self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "INSURER", "amount_paise": 1100000, "method": "settlement"})[0], 400)
        code, receipt = self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "INSURER", "amount_paise": 1000000, "method": "settlement"})
        self.assertEqual((code, receipt["remaining_paise"]), (201, 310000))
        self.assertEqual(self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "PATIENT", "amount_paise": 310000, "method": "UPI"})[1]["remaining_paise"], 0)

    def test_pmjay_no_patient_copay_and_cghs_no_demo_preauth(self):
        _, auth = self.post("/api/preauth", {"encounter_id": "E-IPD-03", "coverage_id": "C-DEMO-03", "requested_paise": 1200000})
        self.post("/api/preauth/" + str(auth["preauth_id"]) + "/decision", {"approved_paise": 1200000})
        _, invoice = self.post("/api/invoices", {"encounter_id": "E-IPD-03"})
        _, claim = self.post("/api/claims", {"invoice_id": invoice["invoice_id"], "coverage_id": "C-DEMO-03"})
        self.post("/api/claims/" + str(claim["claim_id"]) + "/decision", {"approved_paise": 1200000})
        self.assertEqual(self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "PATIENT", "amount_paise": 100, "method": "cash"})[0], 400)
        self.assertEqual(self.post("/api/payments", {"invoice_id": invoice["invoice_id"], "payer_kind": "SCHEME", "amount_paise": 1200000, "method": "demo settlement"})[1]["remaining_paise"], 0)
        _, cghs_invoice = self.post("/api/invoices", {"encounter_id": "E-OPD-04"})
        self.assertEqual(cghs_invoice["total_paise"], 40000)
        self.assertEqual(self.post("/api/claims", {"invoice_id": cghs_invoice["invoice_id"], "coverage_id": "C-DEMO-04"})[0], 201)

    def test_database_foreign_keys(self):
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()

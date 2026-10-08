"""Data map: the ER diagram as a live, clickable view of one patient's records."""

from __future__ import annotations

from fastapi import APIRouter

from .core import age_years, balance_for, db, need, one, rows

router = APIRouter()

# key, ER name, table, kind (entity | weak | relationship | reference), colour group, x, y, scope query.
# Scope queries receive %(p)s = patient_id and %(e)s = list of encounter ids in view.
E = "encounter_id = ANY(%(e)s::text[])"
INV = f"invoice_id IN (SELECT invoice_id FROM invoices WHERE {E})"
ENTITIES = [
    # Lane: patient and visit (HIS core)
    ("patient", "Patient", "patients", "entity", "HIS", 30, 50, "patient_id=%(p)s"),
    ("registration", "Registration", "encounters", "entity", "HIS", 30, 150, E),
    ("consultation", "Consultation", "consultations", "entity", "HIS", 30, 250, E),
    ("prescription", "Prescription", "prescriptions", "entity", "HIS", 30, 350, E),
    ("doctor", "Doctor", "doctors", "reference", "HIS", 195, 250,
     f"doctor_id IN (SELECT doctor_id FROM encounters WHERE {E} UNION SELECT doctor_id FROM consultations WHERE {E})"),
    ("admits", "admits", "room_stays", "relationship", "HIS", 215, 150, E),
    ("ward", "Ward", "wards", "reference", "HIS", 360, 150, f"ward_id IN (SELECT ward_id FROM room_stays WHERE {E})"),
    # Lane: clinical orders and results
    ("radiology_order", "Radiology Order", "radiology_orders", "entity", "RIS", 30, 480, E),
    ("lab_order", "Lab Order", "lab_orders", "entity", "LIS", 195, 480, E),
    ("pharmacy_order", "Pharmacy Order", "pharmacy_orders", "entity", "PHARMACY", 360, 480, E),
    ("procedure_order", "Procedure Order", "procedure_orders", "entity", "HIS", 525, 480, E),
    ("radiology_result", "Radiology Result", "radiology_results", "entity", "RIS", 30, 580,
     f"rad_order_id IN (SELECT rad_order_id FROM radiology_orders WHERE {E})"),
    ("lab_result", "Lab Result", "lab_results", "entity", "LIS", 195, 580,
     f"lab_order_id IN (SELECT lab_order_id FROM lab_orders WHERE {E})"),
    ("medication_issue", "Medication Issue", "dispenses", "entity", "PHARMACY", 360, 580, E),
    ("procedure_performed", "Procedure Performed", "procedures_performed", "entity", "HIS", 525, 580,
     f"proc_order_id IN (SELECT proc_order_id FROM procedure_orders WHERE {E})"),
    # Lane: billing
    ("charge", "Charge", "charges", "entity", "BILLING", 870, 250, E),
    ("bill", "Bill", "invoices", "entity", "BILLING", 870, 150, E),
    ("payment", "Payment", "receipts", "entity", "BILLING", 1035, 150, INV),
    ("service", "Service", "services", "reference", "BILLING", 870, 370,
     f"service_code IN (SELECT service_code FROM charges WHERE {E})"),
    ("payer_rate", "Payer Rate", "payer_rates", "reference", "BILLING", 1035, 370,
     f"service_code IN (SELECT service_code FROM charges WHERE {E}) AND (payer_route, payer_label) IN "
     f"(SELECT payer_route, payer_label FROM encounters WHERE {E} UNION SELECT payer_route, '' FROM encounters WHERE {E})"),
    # Lane: payer
    ("claim", "Insurance Claim", "claims", "entity", "INSURANCE", 870, 50, INV),
    ("insurance", "Insurance", "insurance_policies", "entity", "INSURANCE", 1035, 50, "patient_id=%(p)s"),
]
# Timeline only (not drawn): workflow tables the ER diagram leaves out.
_VISIT = "encounter_id = ANY(%(e)s)"
WORKFLOW_LOG = [
    ("appointments", "appointment_id", "patient_id = %(p)s AND (encounter_id IS NULL OR encounter_id = ANY(%(e)s))"),
    ("notifications", "notification_id", "patient_id = %(p)s AND (encounter_id IS NULL OR encounter_id = ANY(%(e)s))"),
    ("coverages", "coverage_id", _VISIT), ("advances", "advance_id", _VISIT), ("preauths", "preauth_id", _VISIT),
    ("refunds", "refund_id", _VISIT),
    ("balance_adjustments", "adjustment_id", "invoice_id IN (SELECT invoice_id FROM invoices WHERE " + _VISIT + ")"),
]

LANES = [
    {"label": "PATIENT & VISIT · HIS", "x": 14, "y": 18, "w": 506, "h": 400},
    {"label": "CLINICAL ORDERS → RESULTS", "x": 14, "y": 446, "w": 666, "h": 228},
    {"label": "PAYER", "x": 855, "y": 18, "w": 330, "h": 100},
    {"label": "BILLING", "x": 690, "y": 126, "w": 495, "h": 420},
]
# Timestamp columns used when a record has no audit event of its own (oldest first wins).
KEYS = {e[0] for e in ENTITIES}
TABLE_TO_KEY = {}
for _e in ENTITIES:
    TABLE_TO_KEY.setdefault(_e[2], _e[0])

# from, to, label, cardinality at "from", cardinality at "to"
RELATIONS = [
    ("patient", "registration", "has", "1", "N"),
    ("registration", "consultation", "includes", "1", "N"),
    ("doctor", "consultation", "conducts", "1", "N"),
    ("consultation", "prescription", "leads to", "1", "N"),
    ("doctor", "prescription", "prescribes", "1", "N"),
    ("registration", "admits", "", "N", ""),
    ("admits", "ward", "", "", "1"),
    ("prescription", "radiology_order", "orders", "1", "N"),
    ("prescription", "lab_order", "orders", "1", "N"),
    ("prescription", "pharmacy_order", "orders", "1", "N"),
    ("prescription", "procedure_order", "orders", "1", "N"),
    ("radiology_order", "radiology_result", "generates", "1", "1"),
    ("lab_order", "lab_result", "generates", "1", "1"),
    ("pharmacy_order", "medication_issue", "generates", "1", "N"),
    ("procedure_order", "procedure_performed", "generates", "1", "1"),
    ("consultation", "charge", "charges", "1", "1"),
    ("radiology_result", "charge", "charges", "1", "1"),
    ("lab_result", "charge", "charges", "1", "1"),
    ("medication_issue", "charge", "charges", "1", "1"),
    ("procedure_performed", "charge", "charges", "1", "1"),
    ("admits", "charge", "bed charges", "1", "1"),
    ("registration", "charge", "accrues", "1", "N"),
    ("service", "charge", "charged as", "1", "N"),
    ("service", "payer_rate", "priced by", "1", "N"),
    ("registration", "bill", "generates", "1", "0..1"),
    ("charge", "bill", "billed on", "N", "0..1"),
    ("bill", "payment", "pays", "1", "N"),
    ("bill", "claim", "claims", "1", "N"),
    ("claim", "insurance", "claimed under", "N", "1"),
    ("claim", "payment", "settles", "1", "N"),
]
EXTRA_LINKS: dict = {}
# Attributes the ER diagram / schema slides show that are derived or live in a joined table here (see _enrich).
VIRTUAL = {
    "patients": [("age", "integer", None)],
    "doctors": [("fees_paise", "bigint", None)],
    "lab_orders": [("test_name", "text", None), ("loinc_code", "text", None)],
    "radiology_orders": [("study_name", "text", None)],
    "procedure_orders": [("procedure_name", "text", None)],
    "pharmacy_orders": [("medicine_name", "text", None)],
    "dispenses": [("status", "text", None)],
    "services": [("gst_rate_bps", "integer", None), ("hsn_sac", "text", None)],
    "charges": [("item_type", "text", None), ("invoice_id", "bigint", ("bill", "invoice_id"))],
    "invoices": [("payment_status", "text", None)],
}
# key -> (id column on the row, SQL returning id + extra columns for a list of ids)
_LOOKUPS = {
    "doctor": ("doctor_id", """SELECT d.doctor_id AS id, s.base_unit_paise AS fees_paise FROM doctors d
        JOIN services s ON s.service_code=d.consult_service_code WHERE d.doctor_id = ANY(%s)"""),
    "lab_order": ("lab_order_id", """SELECT o.lab_order_id AS id, s.description AS test_name, c.loinc_code FROM lab_orders o
        JOIN services s USING(service_code) JOIN lab_catalog c USING(service_code) WHERE o.lab_order_id = ANY(%s)"""),
    "radiology_order": ("rad_order_id", """SELECT o.rad_order_id AS id, s.description AS study_name FROM radiology_orders o
        JOIN services s USING(service_code) WHERE o.rad_order_id = ANY(%s)"""),
    "procedure_order": ("proc_order_id", """SELECT o.proc_order_id AS id, s.description AS procedure_name
        FROM procedure_orders o JOIN services s USING(service_code) WHERE o.proc_order_id = ANY(%s)"""),
    "pharmacy_order": ("pharm_order_id", """SELECT o.pharm_order_id AS id, i.display_name AS medicine_name
        FROM pharmacy_orders o JOIN pharmacy_items i USING(item_code) WHERE o.pharm_order_id = ANY(%s)"""),
    "medication_issue": ("dispense_id", """SELECT d.dispense_id AS id, CASE o.status WHEN 'CANCELLED' THEN 'CANCELLED'
        ELSE 'ISSUED' END AS status FROM dispenses d JOIN pharmacy_orders o USING(pharm_order_id) WHERE d.dispense_id = ANY(%s)"""),
    "service": ("service_code", """SELECT s.service_code AS id, t.rate_bps AS gst_rate_bps, t.hsn_sac FROM services s
        JOIN tax_rules t ON t.rule_code=s.tax_rule_code WHERE s.service_code = ANY(%s)"""),
    "charge": ("charge_id", """SELECT c.charge_id AS id, s.kind AS item_type, l.invoice_id FROM charges c
        JOIN services s USING(service_code) LEFT JOIN invoice_lines l ON l.charge_id=c.charge_id WHERE c.charge_id = ANY(%s)"""),
}


def _enrich(conn, data: dict) -> None:
    """Fill in the derived / joined attributes listed in VIRTUAL so each record matches the schema slides."""
    for key, (col, sql) in _LOOKUPS.items():
        recs = data.get(key, {}).get("rows") or []
        if not recs:
            continue
        extra = {str(r.pop("id")): r for r in rows(conn, sql, ([r[col] for r in recs],))}
        for r in recs:
            r.update(extra.get(str(r[col]), {}))
    for r in data.get("patient", {}).get("rows") or []:
        r["age"] = age_years(r["dob"])
    for r in data.get("bill", {}).get("rows") or []:
        r["payment_status"] = balance_for(conn, r)["payment_status"]


def _schema(conn) -> dict:
    tables = [e[2] for e in ENTITIES]
    cols = rows(conn, """SELECT table_name,column_name,data_type,ordinal_position FROM information_schema.columns
        WHERE table_schema='public' AND table_name = ANY(%s) ORDER BY table_name,ordinal_position""", (tables,))
    pks = rows(conn, """SELECT tc.table_name,kcu.column_name FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu USING(constraint_name,table_schema)
        WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema='public' AND tc.table_name = ANY(%s)""", (tables,))
    fks = rows(conn, """SELECT conrelid::regclass::text AS table_name,a.attname AS column_name,
        confrelid::regclass::text AS ref_table,af.attname AS ref_column FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
        JOIN pg_attribute af ON af.attrelid=c.confrelid AND af.attnum=c.confkey[1]
        WHERE c.contype='f' AND conrelid::regclass::text = ANY(%s)""", (tables,))
    pk_set = {(p["table_name"], p["column_name"]) for p in pks}
    fk_map = {(f["table_name"], f["column_name"]): (TABLE_TO_KEY.get(f["ref_table"]), f["ref_column"]) for f in fks}
    fk_map.update(EXTRA_LINKS)
    entities = []
    for key, er_name, table, kind, group, x, y, _ in ENTITIES:
        attrs = []
        for c in cols:
            if c["table_name"] != table:
                continue
            link = fk_map.get((table, c["column_name"]))
            attrs.append({"name": c["column_name"], "type": c["data_type"], "pk": (table, c["column_name"]) in pk_set,
                          "fk": {"entity": link[0], "column": link[1]} if link and link[0] else None})
        for name, typ, link in VIRTUAL.get(table, []):
            if not any(a["name"] == name for a in attrs):
                attrs.append({"name": name, "type": typ, "pk": False,
                              "fk": {"entity": link[0], "column": link[1]} if link else None})
        pk = next((a["name"] for a in attrs if a["pk"]), attrs[0]["name"] if attrs else None)
        entities.append({"key": key, "er_name": er_name, "table": table, "kind": kind, "group": group,
                         "x": x, "y": y, "pk": pk, "attributes": attrs})
    return {"entities": entities,
            "relations": [{"from": a, "to": b, "label": l, "card_from": cf, "card_to": ct} for a, b, l, cf, ct in RELATIONS],
            "lanes": LANES, "canvas": {"width": 1200, "height": 690}}


@router.get("/api/datamap/schema")
def datamap_schema():
    with db() as conn:
        return _schema(conn)


@router.get("/api/datamap/{patient_id}")
def datamap(patient_id: str, encounter_id: str = ""):
    with db() as conn:
        need(one(conn, "SELECT 1 FROM patients WHERE patient_id=%s", (patient_id,)), "Patient not found", 404)
        if encounter_id:
            need(one(conn, "SELECT 1 FROM encounters WHERE encounter_id=%s AND patient_id=%s", (encounter_id, patient_id)),
                 "Visit not found for this patient", 404)
            encounters = [encounter_id]
        else:
            encounters = [r["encounter_id"] for r in rows(conn, "SELECT encounter_id FROM encounters WHERE patient_id=%s",
                                                           (patient_id,))]
        params = {"p": patient_id, "e": encounters}
        schema = _schema(conn)
        pk_of = {e["key"]: e["pk"] for e in schema["entities"]}
        data, pairs = {}, [("patients", patient_id)]
        for key, _, table, _, _, _, _, scope in ENTITIES:
            records = rows(conn, f"SELECT * FROM {table} WHERE {scope} ORDER BY 1", params)
            data[key] = {"count": len(records), "rows": records}
            pk = pk_of[key]
            pairs += [(table, str(r[pk])) for r in records if pk in r]
        _enrich(conn, data)
        # Workflow tables are not on the diagram, but their events belong in the who-did-what timeline.
        log_pairs = list(pairs)
        for table, pk, scope in WORKFLOW_LOG:
            log_pairs += [(table, str(r[pk])) for r in rows(conn, f"SELECT {pk} FROM {table} WHERE {scope}", params)]
        # The first audit event of each record: shows who created it and when.
        first_seen = {(r["entity"], r["entity_id"]): r["seq"] for r in rows(conn, """SELECT a.entity, a.entity_id,
            min(a.audit_id) AS seq FROM audit_events a JOIN unnest(%s::text[], %s::text[]) AS t(entity, entity_id)
            USING (entity, entity_id) GROUP BY 1, 2""", ([p[0] for p in pairs], [p[1] for p in pairs]))}
        seq_of = lambda table, value: first_seen.get((table, str(value)))
        parents = {"lab_orders": ("prescriptions", "prescription_id"), "radiology_orders": ("prescriptions", "prescription_id"),
                   "procedure_orders": ("prescriptions", "prescription_id"), "pharmacy_orders": ("prescriptions", "prescription_id"),
                   "invoice_lines": ("invoices", "invoice_id"), "coverages": ("encounters", "encounter_id")}
        for key, _, table, kind, *_rest in ENTITIES:
            for r in data[key]["rows"]:
                seq = None if kind == "reference" else seq_of(table, r.get(pk_of[key]))
                if seq is None and table in parents:
                    seq = seq_of(parents[table][0], r.get(parents[table][1]))
                r["_seq"] = seq
        timeline = rows(conn, """SELECT a.* FROM audit_events a
            WHERE (a.entity, a.entity_id) IN (SELECT * FROM unnest(%s::text[], %s::text[]))
            ORDER BY a.audit_id LIMIT 400""", ([p[0] for p in log_pairs], [p[1] for p in log_pairs]))
        return {"patient_id": patient_id, "encounter_ids": encounters, "entities": data, "timeline": timeline}

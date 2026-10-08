"""Data map: the ER diagram as a live, clickable view of one patient's records."""

from __future__ import annotations

from fastapi import APIRouter

from .core import db, need, one, rows

router = APIRouter()

# key, ER name, table, kind (entity | weak | relationship | workflow), colour group, x, y, scope query.
# Scope queries receive %(p)s = patient_id and %(e)s = list of encounter ids in view.
E = "encounter_id = ANY(%(e)s::text[])"
INV = f"invoice_id IN (SELECT invoice_id FROM invoices WHERE {E})"
ENTITIES = [
    ("patient", "Patient", "patients", "entity", "HIS", 40, 40, "patient_id=%(p)s"),
    ("registration", "Registration", "encounters", "entity", "HIS", 260, 40, E),
    ("doctor", "Doctor", "doctors", "entity", "HIS", 40, 150,
     f"doctor_id IN (SELECT doctor_id FROM encounters WHERE {E} UNION SELECT doctor_id FROM consultations WHERE {E})"),
    ("consultation", "Consultation", "consultations", "entity", "HIS", 260, 150, E),
    ("prescription", "Prescription", "prescriptions", "entity", "HIS", 260, 265, E),
    ("admits", "admits", "room_stays", "relationship", "HIS", 480, 105, E),
    ("ward", "Ward", "wards", "entity", "HIS", 460, 190, f"ward_id IN (SELECT ward_id FROM room_stays WHERE {E})"),
    ("radiology_order", "Radiology Order", "radiology_orders", "entity", "RIS", 40, 385, E),
    ("lab_order", "Lab Order", "lab_orders", "entity", "LIS", 230, 385, E),
    ("pharmacy_order", "Pharmacy Order", "pharmacy_orders", "entity", "PHARMACY", 420, 385, E),
    ("procedure_order", "Procedure Order", "procedure_orders", "entity", "HIS", 610, 385, E),
    ("radiology_result", "Radiology Result", "radiology_results", "entity", "RIS", 40, 500,
     f"rad_order_id IN (SELECT rad_order_id FROM radiology_orders WHERE {E})"),
    ("lab_result", "Lab Result", "lab_results", "entity", "LIS", 230, 500,
     f"lab_order_id IN (SELECT lab_order_id FROM lab_orders WHERE {E})"),
    ("medication_issue", "Medication Issue", "dispenses", "entity", "PHARMACY", 420, 500, E),
    ("procedure_performed", "Procedure Performed", "procedures_performed", "entity", "HIS", 610, 500,
     f"proc_order_id IN (SELECT proc_order_id FROM procedure_orders WHERE {E})"),
    ("bill", "Bill", "invoices", "entity", "BILLING", 830, 40, E),
    ("payment", "Payment", "receipts", "entity", "BILLING", 1030, 40, INV),
    ("claim", "Insurance Claim", "claims", "entity", "INSURANCE", 830, 160, INV),
    ("insurance", "Insurance", "insurance_policies", "entity", "INSURANCE", 1030, 160, "patient_id=%(p)s"),
    ("charge", "Charge", "charges", "entity", "BILLING", 830, 300, E),
    ("bill_line", "Bill Line", "invoice_lines", "weak", "BILLING", 1030, 300, INV),
    ("service", "Service", "services", "entity", "BILLING", 830, 430,
     f"service_code IN (SELECT service_code FROM charges WHERE {E})"),
    ("payer_rate", "Payer Rate", "payer_rates", "entity", "BILLING", 1030, 430,
     f"service_code IN (SELECT service_code FROM charges WHERE {E}) AND (payer_route, payer_label) IN "
     f"(SELECT payer_route, payer_label FROM encounters WHERE {E} UNION SELECT payer_route, '' FROM encounters WHERE {E})"),
    ("appointment", "Appointment", "appointments", "workflow", "WORKFLOW", 40, 640, "patient_id=%(p)s"),
    ("coverage", "Coverage check", "coverages", "workflow", "WORKFLOW", 185, 640, E),
    ("preauth", "Pre-authorisation", "preauths", "workflow", "WORKFLOW", 330, 640, E),
    ("deposit", "Deposit", "advances", "workflow", "WORKFLOW", 475, 640, E),
    ("adjustment", "Shortfall / write-off", "balance_adjustments", "workflow", "WORKFLOW", 620, 640, INV),
    ("refund", "Refund", "refunds", "workflow", "WORKFLOW", 765, 640, E),
    ("notification", "Notification", "notifications", "workflow", "WORKFLOW", 910, 640, "patient_id=%(p)s"),
    ("tax_rule", "Tax Rule", "tax_rules", "workflow", "WORKFLOW", 1055, 640,
     f"rule_code IN (SELECT tax_rule_code FROM charges WHERE {E})"),
]
KEYS = {e[0] for e in ENTITIES}
TABLE_TO_KEY = {}
for _e in ENTITIES:
    TABLE_TO_KEY.setdefault(_e[2], _e[0])

# from, to, label, cardinality at "from", cardinality at "to"
RELATIONS = [
    ("patient", "registration", "has", "1", "N"),
    ("patient", "insurance", "holds", "1", "N"),
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
    ("admits", "charge", "bed days", "1", "1"),
    ("registration", "charge", "accrues", "1", "N"),
    ("service", "charge", "charged as", "1", "N"),
    ("service", "payer_rate", "priced by", "1", "N"),
    ("registration", "bill", "generates", "1", "0..1"),
    ("charge", "bill_line", "printed as", "1", "0..1"),
    ("bill", "bill_line", "contains", "1", "N"),
    ("bill", "payment", "pays", "1", "N"),
    ("bill", "claim", "claims", "1", "N"),
    ("claim", "insurance", "claimed under", "N", "1"),
    ("insurance", "payment", "settles", "1", "N"),
]
EXTRA_LINKS = {("services", "tax_rule_code"): ("tax_rule", "rule_code"),
               ("charges", "tax_rule_code"): ("tax_rule", "rule_code")}


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
        pk = next((a["name"] for a in attrs if a["pk"]), attrs[0]["name"] if attrs else None)
        entities.append({"key": key, "er_name": er_name, "table": table, "kind": kind, "group": group,
                         "x": x, "y": y, "pk": pk, "attributes": attrs})
    return {"entities": entities,
            "relations": [{"from": a, "to": b, "label": l, "card_from": cf, "card_to": ct} for a, b, l, cf, ct in RELATIONS],
            "canvas": {"width": 1200, "height": 710}}


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
        timeline = rows(conn, """SELECT a.* FROM audit_events a
            JOIN unnest(%s::text[], %s::text[]) AS t(entity, entity_id) USING (entity, entity_id)
            ORDER BY a.created_at DESC, a.audit_id DESC LIMIT 200""", ([p[0] for p in pairs], [p[1] for p in pairs]))
        return {"patient_id": patient_id, "encounter_ids": encounters, "entities": data, "timeline": timeline}

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS patient (
  patient_id TEXT PRIMARY KEY,
  display_label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS encounter (
  encounter_id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patient(patient_id),
  setting TEXT NOT NULL CHECK (setting IN ('OPD','IPD','EMERGENCY','DAY_CARE')),
  payer_route TEXT NOT NULL CHECK (payer_route IN ('SELF','PRIVATE','PMJAY','CGHS','CORPORATE')),
  opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage (
  coverage_id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patient(patient_id),
  payer_kind TEXT NOT NULL CHECK (payer_kind IN ('PRIVATE','PMJAY','CGHS','CORPORATE')),
  payer_label TEXT NOT NULL,
  reference_code TEXT NOT NULL,
  preauth_required INTEGER NOT NULL CHECK (preauth_required IN (0,1)),
  verification_status TEXT NOT NULL CHECK (verification_status IN ('UNVERIFIED_DEMO'))
);

CREATE TABLE IF NOT EXISTS service_catalog (
  service_code TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  list_price_paise INTEGER NOT NULL CHECK (list_price_paise >= 0),
  tax_code TEXT NOT NULL CHECK (tax_code IN ('EXEMPT_DEMO','REVIEW_REQUIRED')),
  active INTEGER NOT NULL CHECK (active IN (0,1))
);

CREATE TABLE IF NOT EXISTS payer_rate (
  service_code TEXT NOT NULL REFERENCES service_catalog(service_code),
  payer_kind TEXT NOT NULL CHECK (payer_kind IN ('PRIVATE','PMJAY','CGHS','CORPORATE')),
  unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise >= 0),
  PRIMARY KEY (service_code,payer_kind)
);

CREATE TABLE IF NOT EXISTS charge (
  charge_id INTEGER PRIMARY KEY AUTOINCREMENT,
  encounter_id TEXT NOT NULL REFERENCES encounter(encounter_id),
  service_code TEXT NOT NULL REFERENCES service_catalog(service_code),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise >= 0),
  amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
  source_event_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preauth (
  preauth_id INTEGER PRIMARY KEY AUTOINCREMENT,
  encounter_id TEXT NOT NULL UNIQUE REFERENCES encounter(encounter_id),
  coverage_id TEXT NOT NULL REFERENCES coverage(coverage_id),
  status TEXT NOT NULL CHECK (status IN ('SUBMITTED_DEMO','APPROVED_DEMO','REJECTED_DEMO')),
  requested_paise INTEGER NOT NULL CHECK (requested_paise > 0),
  approved_paise INTEGER CHECK (approved_paise >= 0),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoice (
  invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
  encounter_id TEXT NOT NULL UNIQUE REFERENCES encounter(encounter_id),
  status TEXT NOT NULL CHECK (status IN ('FINAL')),
  subtotal_paise INTEGER NOT NULL CHECK (subtotal_paise >= 0),
  tax_paise INTEGER NOT NULL CHECK (tax_paise >= 0),
  total_paise INTEGER NOT NULL CHECK (total_paise >= 0),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoice_line (
  invoice_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoice(invoice_id),
  charge_id INTEGER NOT NULL UNIQUE REFERENCES charge(charge_id),
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise >= 0),
  amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0)
);

CREATE TABLE IF NOT EXISTS claim (
  claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL UNIQUE REFERENCES invoice(invoice_id),
  coverage_id TEXT NOT NULL REFERENCES coverage(coverage_id),
  preauth_id INTEGER REFERENCES preauth(preauth_id),
  status TEXT NOT NULL CHECK (status IN ('SUBMITTED_DEMO','APPROVED_DEMO','REJECTED_DEMO')),
  requested_paise INTEGER NOT NULL CHECK (requested_paise >= 0),
  approved_paise INTEGER CHECK (approved_paise >= 0),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment (
  payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoice(invoice_id),
  payer_kind TEXT NOT NULL CHECK (payer_kind IN ('PATIENT','INSURER','SCHEME','CORPORATE')),
  method TEXT NOT NULL,
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_event (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_encounter_patient ON encounter(patient_id);
CREATE INDEX IF NOT EXISTS idx_coverage_patient ON coverage(patient_id);
CREATE INDEX IF NOT EXISTS idx_charge_encounter ON charge(encounter_id);
CREATE INDEX IF NOT EXISTS idx_payment_invoice ON payment(invoice_id);

CREATE TABLE IF NOT EXISTS patients (
  patient_id TEXT PRIMARY KEY,
  display_label TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE patients ADD COLUMN IF NOT EXISTS age_years INTEGER;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS sex TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS blood_group TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS contact_masked TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS city TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS allergies TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS history_summary TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS staff_users (
  username TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('ADMIN','DOCTOR','LAB','PHARMACY')),
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL
);
ALTER TABLE staff_users DROP CONSTRAINT IF EXISTS staff_users_role_check;
CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL REFERENCES staff_users(username),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TABLE IF EXISTS coding_reviews;
DELETE FROM auth_sessions WHERE username IN ('coder','billing');
DELETE FROM staff_users WHERE username IN ('coder','billing');
ALTER TABLE staff_users ADD CONSTRAINT staff_users_role_check CHECK (role IN ('ADMIN','DOCTOR','LAB','PHARMACY'));

CREATE TABLE IF NOT EXISTS encounters (
  encounter_id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  setting TEXT NOT NULL CHECK (setting IN ('OPD','IPD','EMERGENCY','DAY_CARE')),
  payer_route TEXT NOT NULL CHECK (payer_route IN ('SELF','PRIVATE','PMJAY','CGHS','CORPORATE')),
  payer_label TEXT NOT NULL DEFAULT '',
  bill_to_gstin TEXT NOT NULL DEFAULT '',
  state_code TEXT NOT NULL DEFAULT '29',
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','DISCHARGED','BILLED')),
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  discharged_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS clinical_notes (
  note_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  author_username TEXT NOT NULL REFERENCES staff_users(username),
  note_type TEXT NOT NULL DEFAULT 'PROGRESS',
  note_text TEXT NOT NULL,
  provisional_icd_code TEXT NOT NULL DEFAULT '',
  procedure_code TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE clinical_notes ADD COLUMN IF NOT EXISTS provisional_icd_code TEXT NOT NULL DEFAULT '';
ALTER TABLE clinical_notes ADD COLUMN IF NOT EXISTS procedure_code TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS prescriptions (
  prescription_ref TEXT PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  item_code TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  instruction TEXT NOT NULL DEFAULT '',
  author_username TEXT NOT NULL REFERENCES staff_users(username),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverages (
  coverage_id TEXT PRIMARY KEY,
  encounter_id TEXT NOT NULL UNIQUE REFERENCES encounters(encounter_id),
  payer_route TEXT NOT NULL,
  payer_label TEXT NOT NULL,
  member_ref TEXT NOT NULL DEFAULT '',
  referral_ref TEXT NOT NULL DEFAULT '',
  eligibility_status TEXT NOT NULL DEFAULT 'UNVERIFIED_DEMO',
  preauth_required BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS tax_rules (
  rule_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  rule_code TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  tax_category TEXT NOT NULL CHECK (tax_category IN ('EXEMPT','NIL','TAXABLE','REVIEW')),
  rate_bps INTEGER NOT NULL CHECK (rate_bps >= 0 AND rate_bps <= 10000),
  hsn_sac TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  UNIQUE (rule_code,effective_from)
);

CREATE TABLE IF NOT EXISTS services (
  service_code TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('CARE','LAB','ROOM','PROCEDURE','PHARMACY','PACKAGE','DEVICE')),
  base_unit_paise BIGINT NOT NULL CHECK (base_unit_paise >= 0),
  tax_rule_code TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS lab_catalog (
  service_code TEXT PRIMARY KEY REFERENCES services(service_code),
  loinc_code TEXT NOT NULL,
  cpt_reference TEXT NOT NULL DEFAULT '',
  result_unit TEXT NOT NULL,
  specimen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_orders (
  lab_order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  service_code TEXT NOT NULL REFERENCES lab_catalog(service_code),
  status TEXT NOT NULL DEFAULT 'ORDERED' CHECK (status IN ('ORDERED','COMPLETED')),
  ordered_by TEXT NOT NULL REFERENCES staff_users(username),
  performed_by TEXT REFERENCES staff_users(username),
  result_value NUMERIC(6,2),
  charge_id BIGINT,
  ordered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (encounter_id,service_code)
);

CREATE TABLE IF NOT EXISTS payer_rates (
  service_code TEXT NOT NULL REFERENCES services(service_code),
  payer_route TEXT NOT NULL,
  payer_label TEXT NOT NULL DEFAULT '',
  unit_paise BIGINT NOT NULL CHECK (unit_paise >= 0),
  PRIMARY KEY (service_code,payer_route,payer_label)
);

CREATE TABLE IF NOT EXISTS pharmacy_items (
  item_code TEXT PRIMARY KEY,
  service_code TEXT NOT NULL UNIQUE REFERENCES services(service_code),
  display_name TEXT NOT NULL,
  requires_prescription BOOLEAN NOT NULL DEFAULT true,
  controlled_stock BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS stock_batches (
  batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_code TEXT NOT NULL REFERENCES pharmacy_items(item_code),
  batch_no TEXT NOT NULL,
  expiry_date DATE NOT NULL,
  quantity_available INTEGER NOT NULL CHECK (quantity_available >= 0),
  UNIQUE (item_code,batch_no)
);

CREATE TABLE IF NOT EXISTS package_catalog (
  package_code TEXT PRIMARY KEY,
  service_code TEXT NOT NULL UNIQUE REFERENCES services(service_code),
  payer_route TEXT NOT NULL,
  included_departments TEXT[] NOT NULL DEFAULT '{}',
  preauth_required BOOLEAN NOT NULL DEFAULT false,
  note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS room_stays (
  room_stay_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  room_code TEXT NOT NULL REFERENCES services(service_code),
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (end_date > start_date),
  UNIQUE (encounter_id,room_code,start_date,end_date)
);

CREATE TABLE IF NOT EXISTS charges (
  charge_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  source_event_id TEXT NOT NULL UNIQUE,
  service_code TEXT NOT NULL REFERENCES services(service_code),
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_paise BIGINT NOT NULL CHECK (unit_price_paise >= 0),
  subtotal_paise BIGINT GENERATED ALWAYS AS (quantity * unit_price_paise) STORED,
  tax_rule_code TEXT NOT NULL,
  tax_category TEXT NOT NULL,
  tax_rate_bps INTEGER NOT NULL CHECK (tax_rate_bps >= 0),
  hsn_sac TEXT NOT NULL,
  included_in_package BOOLEAN NOT NULL DEFAULT false,
  room_stay_id BIGINT REFERENCES room_stays(room_stay_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS lab_orders_charge_id_unique ON lab_orders(charge_id) WHERE charge_id IS NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'lab_orders_charge_fk') THEN
    ALTER TABLE lab_orders ADD CONSTRAINT lab_orders_charge_fk
      FOREIGN KEY (charge_id) REFERENCES charges(charge_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS dispenses (
  dispense_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  item_code TEXT NOT NULL REFERENCES pharmacy_items(item_code),
  batch_id BIGINT NOT NULL REFERENCES stock_batches(batch_id),
  charge_id BIGINT NOT NULL UNIQUE REFERENCES charges(charge_id),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  prescription_ref TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS preauths (
  preauth_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  coverage_id TEXT NOT NULL REFERENCES coverages(coverage_id),
  request_type TEXT NOT NULL DEFAULT 'INITIAL' CHECK (request_type IN ('INITIAL','ENHANCEMENT')),
  requested_paise BIGINT NOT NULL CHECK (requested_paise > 0),
  approved_paise BIGINT NOT NULL DEFAULT 0 CHECK (approved_paise >= 0),
  status TEXT NOT NULL DEFAULT 'SUBMITTED_DEMO',
  reference_no TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS invoices (
  invoice_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL UNIQUE REFERENCES encounters(encounter_id),
  invoice_no TEXT NOT NULL UNIQUE,
  subtotal_paise BIGINT NOT NULL CHECK (subtotal_paise >= 0),
  tax_paise BIGINT NOT NULL CHECK (tax_paise >= 0),
  total_paise BIGINT NOT NULL CHECK (total_paise >= 0),
  advance_allocated_paise BIGINT NOT NULL DEFAULT 0 CHECK (advance_allocated_paise >= 0),
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoice_lines (
  invoice_line_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  charge_id BIGINT NOT NULL UNIQUE REFERENCES charges(charge_id),
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price_paise BIGINT NOT NULL,
  taxable_paise BIGINT NOT NULL,
  tax_category TEXT NOT NULL,
  tax_rate_bps INTEGER NOT NULL,
  tax_paise BIGINT NOT NULL,
  total_paise BIGINT NOT NULL,
  hsn_sac TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
  claim_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL UNIQUE REFERENCES invoices(invoice_id),
  coverage_id TEXT NOT NULL REFERENCES coverages(coverage_id),
  preauth_id BIGINT REFERENCES preauths(preauth_id),
  status TEXT NOT NULL DEFAULT 'SUBMITTED_DEMO',
  submitted_paise BIGINT NOT NULL CHECK (submitted_paise > 0),
  approved_paise BIGINT NOT NULL DEFAULT 0 CHECK (approved_paise >= 0),
  diagnosis_code TEXT NOT NULL DEFAULT '',
  procedure_code TEXT NOT NULL DEFAULT '',
  discharge_summary TEXT NOT NULL DEFAULT '',
  documents JSONB NOT NULL DEFAULT '{}'::jsonb,
  reference_no TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);
ALTER TABLE claims ADD COLUMN IF NOT EXISTS procedure_code TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS advances (
  advance_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  method TEXT NOT NULL,
  reference_no TEXT NOT NULL DEFAULT '',
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS receipts (
  receipt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  payer_kind TEXT NOT NULL CHECK (payer_kind IN ('PATIENT','INSURER','SCHEME','CORPORATE')),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  method TEXT NOT NULL,
  reference_no TEXT NOT NULL DEFAULT '',
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS refunds (
  refund_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  method TEXT NOT NULL,
  reference_no TEXT NOT NULL DEFAULT '',
  refunded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_events (
  audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_charges_encounter ON charges(encounter_id);
CREATE INDEX IF NOT EXISTS idx_invoices_issued ON invoices(issued_at);
CREATE INDEX IF NOT EXISTS idx_receipts_invoice ON receipts(invoice_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_encounter ON clinical_notes(encounter_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rx_encounter ON prescriptions(encounter_id,created_at DESC);

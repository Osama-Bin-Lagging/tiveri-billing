-- Schema version 2. Applied only on a fresh database or when schema_meta.version is older;
-- main.initialise() drops the previous tables first. All data is synthetic.
-- ER-diagram names are noted beside each table (see docs/er_mapping.md).

CREATE TABLE schema_meta (version INTEGER NOT NULL);

-- Reference data -----------------------------------------------------------

CREATE TABLE departments (                         -- Doctor.department attribute
  department_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('CLINICAL','DIAGNOSTIC','PHARMACY','SUPPORT'))
);

CREATE TABLE tax_rules (                           -- Service.gst_rate / hsn_sac
  rule_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  rule_code TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  tax_category TEXT NOT NULL CHECK (tax_category IN ('EXEMPT','NIL','TAXABLE','REVIEW')),
  rate_bps INTEGER NOT NULL CHECK (rate_bps BETWEEN 0 AND 10000),
  hsn_sac TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  UNIQUE (rule_code, effective_from)
);

CREATE TABLE services (                            -- ER: Service
  service_code TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  department_id TEXT NOT NULL REFERENCES departments(department_id),
  kind TEXT NOT NULL CHECK (kind IN ('CARE','LAB','RADIOLOGY','ROOM','PROCEDURE','PHARMACY','PACKAGE','DEVICE')),
  base_unit_paise BIGINT NOT NULL CHECK (base_unit_paise >= 0),
  tax_rule_code TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE payer_rates (                         -- ER: Payer Rate
  service_code TEXT NOT NULL REFERENCES services(service_code),
  payer_route TEXT NOT NULL,
  payer_label TEXT NOT NULL DEFAULT '',
  unit_paise BIGINT NOT NULL CHECK (unit_paise >= 0),
  PRIMARY KEY (service_code, payer_route, payer_label)
);

CREATE TABLE diagnosis_catalog (                   -- ICD-10 picker for Prescription.icd_code
  icd_code TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  snomed_code TEXT NOT NULL
);

CREATE TABLE lab_catalog (
  service_code TEXT PRIMARY KEY REFERENCES services(service_code),
  loinc_code TEXT NOT NULL,
  result_unit TEXT NOT NULL,
  specimen TEXT NOT NULL,
  reference_range TEXT NOT NULL DEFAULT '',
  cpt_reference TEXT NOT NULL DEFAULT ''
);

CREATE TABLE radiology_catalog (
  service_code TEXT PRIMARY KEY REFERENCES services(service_code),
  snomed_code TEXT NOT NULL,
  modality TEXT NOT NULL CHECK (modality IN ('XRAY','CT','USG','MRI')),
  body_site TEXT NOT NULL
);

CREATE TABLE procedure_catalog (
  service_code TEXT PRIMARY KEY REFERENCES services(service_code),
  snomed_code TEXT NOT NULL,
  outsourced BOOLEAN NOT NULL DEFAULT false,
  partner TEXT NOT NULL DEFAULT ''
);

CREATE TABLE pharmacy_items (
  item_code TEXT PRIMARY KEY,
  service_code TEXT NOT NULL UNIQUE REFERENCES services(service_code),
  display_name TEXT NOT NULL,
  requires_prescription BOOLEAN NOT NULL DEFAULT true,
  controlled_stock BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE stock_batches (
  batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_code TEXT NOT NULL REFERENCES pharmacy_items(item_code),
  batch_no TEXT NOT NULL,
  expiry_date DATE NOT NULL,
  quantity_available INTEGER NOT NULL CHECK (quantity_available >= 0),
  UNIQUE (item_code, batch_no)
);

CREATE TABLE package_catalog (
  package_code TEXT PRIMARY KEY,
  service_code TEXT NOT NULL UNIQUE REFERENCES services(service_code),
  payer_route TEXT NOT NULL,
  included_kinds TEXT[] NOT NULL DEFAULT '{}',
  preauth_required BOOLEAN NOT NULL DEFAULT false,
  note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE wards (                               -- ER: Ward
  ward_id TEXT PRIMARY KEY,
  ward_name TEXT NOT NULL,
  ward_type TEXT NOT NULL CHECK (ward_type IN ('GENERAL','SEMI_PRIVATE','PRIVATE','ICU')),
  room_service_code TEXT NOT NULL REFERENCES services(service_code),
  beds INTEGER NOT NULL CHECK (beds > 0)
);

CREATE TABLE doctors (                             -- ER: Doctor
  doctor_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  specialization TEXT NOT NULL,
  department_id TEXT NOT NULL REFERENCES departments(department_id),
  contact_masked TEXT NOT NULL DEFAULT '',
  consult_service_code TEXT NOT NULL REFERENCES services(service_code)
);

-- Staff and sessions ---------------------------------------------------------

CREATE TABLE staff_users (
  username TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('ADMIN','DOCTOR','LAB','PHARMACY','RECEPTION')),
  doctor_id TEXT REFERENCES doctors(doctor_id),
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL
);

CREATE TABLE auth_sessions (
  token_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL REFERENCES staff_users(username),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Patients, insurance and visits -------------------------------------------

CREATE TABLE patients (                            -- ER: Patient (age is derived from dob)
  patient_id TEXT PRIMARY KEY,
  mrn TEXT NOT NULL UNIQUE,
  display_label TEXT NOT NULL,
  dob DATE NOT NULL,
  sex TEXT NOT NULL DEFAULT '',
  blood_group TEXT NOT NULL DEFAULT '',
  contact_masked TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  allergies TEXT NOT NULL DEFAULT '',
  history_summary TEXT NOT NULL DEFAULT '',
  abha_number TEXT UNIQUE,
  abha_address TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE insurance_policies (                  -- ER: Insurance
  policy_id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  payer_route TEXT NOT NULL CHECK (payer_route IN ('PRIVATE','PMJAY','CGHS','CORPORATE')),
  provider_name TEXT NOT NULL,
  policy_no TEXT NOT NULL,
  coverage_type TEXT NOT NULL DEFAULT 'INDIVIDUAL',
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  coverage_amount_paise BIGINT NOT NULL CHECK (coverage_amount_paise >= 0),
  nominee TEXT NOT NULL DEFAULT '',
  copay_bps INTEGER NOT NULL DEFAULT 0 CHECK (copay_bps BETWEEN 0 AND 10000),
  CHECK (valid_to >= valid_from)
);

CREATE TABLE appointments (                        -- workflow: Appointment schedule
  appointment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  doctor_id TEXT NOT NULL REFERENCES doctors(doctor_id),
  slot_at TIMESTAMPTZ NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'BOOKED' CHECK (status IN ('BOOKED','CHECKED_IN','CANCELLED')),
  encounter_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE encounters (                          -- ER: Registration
  encounter_id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  doctor_id TEXT REFERENCES doctors(doctor_id),
  appointment_id BIGINT REFERENCES appointments(appointment_id),
  policy_id TEXT REFERENCES insurance_policies(policy_id),
  setting TEXT NOT NULL CHECK (setting IN ('OPD','IPD','EMERGENCY','DAY_CARE')),
  payment_mode TEXT NOT NULL DEFAULT 'SELF' CHECK (payment_mode IN ('SELF','CASHLESS','REIMBURSEMENT')),
  payer_route TEXT NOT NULL CHECK (payer_route IN ('SELF','PRIVATE','PMJAY','CGHS','CORPORATE')),
  payer_label TEXT NOT NULL DEFAULT '',
  bill_to_gstin TEXT NOT NULL DEFAULT '',
  state_code TEXT NOT NULL DEFAULT '29',
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','DISCHARGED','BILLED')),
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  discharged_at TIMESTAMPTZ
);
ALTER TABLE appointments ADD CONSTRAINT appointments_encounter_fk
  FOREIGN KEY (encounter_id) REFERENCES encounters(encounter_id);
CREATE UNIQUE INDEX one_active_visit ON encounters(patient_id) WHERE status IN ('OPEN','DISCHARGED');

CREATE TABLE coverages (                           -- the Insurance used for one Registration
  coverage_id TEXT PRIMARY KEY,
  encounter_id TEXT NOT NULL UNIQUE REFERENCES encounters(encounter_id),
  policy_id TEXT REFERENCES insurance_policies(policy_id),
  payer_route TEXT NOT NULL,
  payer_label TEXT NOT NULL,
  member_ref TEXT NOT NULL DEFAULT '',
  eligibility_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (eligibility_status IN ('UNVERIFIED','VERIFIED','NOT_ELIGIBLE')),
  verified_at TIMESTAMPTZ,
  preauth_required BOOLEAN NOT NULL DEFAULT false,
  copay_bps INTEGER NOT NULL DEFAULT 0 CHECK (copay_bps BETWEEN 0 AND 10000)
);

-- Clinical ------------------------------------------------------------------

CREATE TABLE charges (                             -- ER: Charge (was Bill Item)
  charge_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  source_event_id TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL DEFAULT 'HIS_EVENT',
  source_id TEXT NOT NULL DEFAULT '',
  charge_type TEXT NOT NULL DEFAULT 'CHARGE' CHECK (charge_type IN ('CHARGE','REVERSAL','PACKAGE_ADJ')),
  reverses_charge_id BIGINT REFERENCES charges(charge_id),
  service_code TEXT NOT NULL REFERENCES services(service_code),
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_paise BIGINT NOT NULL CHECK (unit_price_paise >= 0),
  subtotal_paise BIGINT GENERATED ALWAYS AS
    ((CASE WHEN charge_type = 'CHARGE' THEN 1 ELSE -1 END) * quantity * unit_price_paise) STORED,
  tax_rule_code TEXT NOT NULL,
  tax_category TEXT NOT NULL,
  tax_rate_bps INTEGER NOT NULL CHECK (tax_rate_bps >= 0),
  hsn_sac TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((charge_type = 'CHARGE') = (reverses_charge_id IS NULL))
);
CREATE UNIQUE INDEX charges_offset_once ON charges(reverses_charge_id) WHERE reverses_charge_id IS NOT NULL;

CREATE TABLE consultations (                       -- ER: Consultation
  consult_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  doctor_id TEXT NOT NULL REFERENCES doctors(doctor_id),
  consult_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'COMPLETED',
  charge_id BIGINT REFERENCES charges(charge_id)
);

CREATE TABLE prescriptions (                       -- ER: Prescription (order header)
  prescription_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  consult_id BIGINT NOT NULL REFERENCES consultations(consult_id),
  doctor_id TEXT NOT NULL REFERENCES doctors(doctor_id),
  icd_code TEXT NOT NULL REFERENCES diagnosis_catalog(icd_code),
  snomed_code TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  prescribed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE lab_orders (                          -- ER: Lab Order
  lab_order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  prescription_id BIGINT NOT NULL REFERENCES prescriptions(prescription_id),
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  service_code TEXT NOT NULL REFERENCES lab_catalog(service_code),
  status TEXT NOT NULL DEFAULT 'ORDERED' CHECK (status IN ('ORDERED','COMPLETED','CANCELLED')),
  ordered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE lab_results (                         -- ER: Lab Result
  result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lab_order_id BIGINT NOT NULL UNIQUE REFERENCES lab_orders(lab_order_id),
  loinc_code TEXT NOT NULL,
  result_value NUMERIC(10,2) NOT NULL,
  result_unit TEXT NOT NULL,
  report_file TEXT NOT NULL DEFAULT '',
  performed_by TEXT NOT NULL,
  report_date TIMESTAMPTZ NOT NULL DEFAULT now(),
  charge_id BIGINT REFERENCES charges(charge_id)
);

CREATE TABLE radiology_orders (                    -- ER: Radiology Order
  rad_order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  prescription_id BIGINT NOT NULL REFERENCES prescriptions(prescription_id),
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  service_code TEXT NOT NULL REFERENCES radiology_catalog(service_code),
  modality TEXT NOT NULL,
  clinical_notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ORDERED' CHECK (status IN ('ORDERED','COMPLETED','CANCELLED')),
  ordered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE radiology_results (                   -- ER: Radiology Result
  result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  rad_order_id BIGINT NOT NULL UNIQUE REFERENCES radiology_orders(rad_order_id),
  findings TEXT NOT NULL,
  snomed_code TEXT NOT NULL,
  report_file TEXT NOT NULL DEFAULT '',
  reported_by TEXT NOT NULL,
  report_date TIMESTAMPTZ NOT NULL DEFAULT now(),
  charge_id BIGINT REFERENCES charges(charge_id)
);

CREATE TABLE procedure_orders (                    -- ER: Procedure Order
  proc_order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  prescription_id BIGINT NOT NULL REFERENCES prescriptions(prescription_id),
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  service_code TEXT NOT NULL REFERENCES procedure_catalog(service_code),
  snomed_code TEXT NOT NULL,
  outsourced BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'ORDERED' CHECK (status IN ('ORDERED','PERFORMED','CANCELLED')),
  ordered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE procedures_performed (                -- ER: Procedure Performed
  proc_perf_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proc_order_id BIGINT NOT NULL UNIQUE REFERENCES procedure_orders(proc_order_id),
  snomed_code TEXT NOT NULL,
  outcome_notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'COMPLETED',
  performed_by TEXT NOT NULL,
  performed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  charge_id BIGINT REFERENCES charges(charge_id)
);

CREATE TABLE pharmacy_orders (                     -- ER: Pharmacy Order
  pharm_order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  prescription_id BIGINT NOT NULL REFERENCES prescriptions(prescription_id),
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  item_code TEXT NOT NULL REFERENCES pharmacy_items(item_code),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  instruction TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ORDERED' CHECK (status IN ('ORDERED','PARTIAL','DISPENSED','CANCELLED')),
  ordered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dispenses (                           -- ER: Medication Issue
  dispense_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pharm_order_id BIGINT NOT NULL REFERENCES pharmacy_orders(pharm_order_id),
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  item_code TEXT NOT NULL REFERENCES pharmacy_items(item_code),
  batch_id BIGINT NOT NULL REFERENCES stock_batches(batch_id),
  charge_id BIGINT NOT NULL UNIQUE REFERENCES charges(charge_id),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  dispensed_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE room_stays (                          -- ER: Registration "admits" Ward (with dates)
  room_stay_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  ward_id TEXT NOT NULL REFERENCES wards(ward_id),
  start_date DATE NOT NULL,
  end_date DATE,
  charge_id BIGINT REFERENCES charges(charge_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (end_date IS NULL OR end_date > start_date)
);
ALTER TABLE charges ADD COLUMN room_stay_id BIGINT REFERENCES room_stays(room_stay_id);

-- Billing and payer ---------------------------------------------------------

CREATE TABLE invoices (                            -- ER: Bill
  invoice_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL UNIQUE REFERENCES encounters(encounter_id),
  invoice_no TEXT NOT NULL UNIQUE,
  subtotal_paise BIGINT NOT NULL,
  tax_paise BIGINT NOT NULL,
  discount_paise BIGINT NOT NULL DEFAULT 0 CHECK (discount_paise >= 0),
  total_paise BIGINT NOT NULL CHECK (total_paise >= 0),
  patient_share_paise BIGINT NOT NULL CHECK (patient_share_paise >= 0),
  payer_share_paise BIGINT NOT NULL CHECK (payer_share_paise >= 0),
  status TEXT NOT NULL DEFAULT 'FINAL' CHECK (status IN ('FINAL')),
  due_date DATE NOT NULL,
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoice_lines (                       -- ER: Bill Line (weak entity of Bill)
  invoice_line_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  line_no INTEGER NOT NULL,
  charge_id BIGINT NOT NULL UNIQUE REFERENCES charges(charge_id),
  charge_type TEXT NOT NULL,
  description TEXT NOT NULL,
  department TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price_paise BIGINT NOT NULL,
  taxable_paise BIGINT NOT NULL,
  tax_category TEXT NOT NULL,
  tax_rate_bps INTEGER NOT NULL,
  tax_paise BIGINT NOT NULL,
  total_paise BIGINT NOT NULL,
  hsn_sac TEXT NOT NULL,
  UNIQUE (invoice_id, line_no)
);

CREATE TABLE preauths (                            -- workflow: Pre-authorisation
  preauth_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  coverage_id TEXT NOT NULL REFERENCES coverages(coverage_id),
  request_type TEXT NOT NULL DEFAULT 'INITIAL' CHECK (request_type IN ('INITIAL','ENHANCEMENT')),
  requested_paise BIGINT NOT NULL CHECK (requested_paise > 0),
  approved_paise BIGINT NOT NULL DEFAULT 0 CHECK (approved_paise >= 0),
  status TEXT NOT NULL DEFAULT 'SUBMITTED' CHECK (status IN ('SUBMITTED','APPROVED','REJECTED')),
  reference_no TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE TABLE claims (                              -- ER: Insurance Claim
  claim_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  attempt_no INTEGER NOT NULL DEFAULT 1,
  parent_claim_id BIGINT REFERENCES claims(claim_id),
  coverage_id TEXT NOT NULL REFERENCES coverages(coverage_id),
  preauth_id BIGINT REFERENCES preauths(preauth_id),
  status TEXT NOT NULL DEFAULT 'SUBMITTED' CHECK (status IN ('SUBMITTED','APPROVED','PARTIAL','REJECTED')),
  submitted_paise BIGINT NOT NULL CHECK (submitted_paise > 0),
  approved_paise BIGINT NOT NULL DEFAULT 0 CHECK (approved_paise >= 0),
  rejection_reason TEXT NOT NULL DEFAULT '',
  diagnosis_code TEXT NOT NULL DEFAULT '',
  procedure_code TEXT NOT NULL DEFAULT '',
  discharge_summary TEXT NOT NULL DEFAULT '',
  documents JSONB NOT NULL DEFAULT '{}'::jsonb,
  reference_no TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ,
  UNIQUE (invoice_id, attempt_no)
);

CREATE TABLE balance_adjustments (                 -- claim shortfall moved to patient or written off
  adjustment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  claim_id BIGINT REFERENCES claims(claim_id),
  kind TEXT NOT NULL CHECK (kind IN ('TO_PATIENT','WRITE_OFF')),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  reason TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE advances (                            -- workflow: Deposit
  advance_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  method TEXT NOT NULL,
  reference_no TEXT NOT NULL DEFAULT '',
  received_by TEXT NOT NULL DEFAULT '',
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE receipts (                            -- ER: Payment
  receipt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  payer_kind TEXT NOT NULL CHECK (payer_kind IN ('PATIENT','INSURER','SCHEME','CORPORATE')),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  method TEXT NOT NULL,
  reference_no TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'SUCCEEDED' CHECK (status IN ('PENDING','SUCCEEDED','FAILED','TIMEOUT')),
  attempt_no INTEGER NOT NULL DEFAULT 1,
  retry_of BIGINT REFERENCES receipts(receipt_id),
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_at TIMESTAMPTZ
);

CREATE TABLE refunds (
  refund_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  method TEXT NOT NULL,
  reference_no TEXT NOT NULL DEFAULT '',
  refunded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE notifications (                       -- workflow: Reminder engine / Patient notification
  notification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  encounter_id TEXT REFERENCES encounters(encounter_id),
  invoice_id BIGINT REFERENCES invoices(invoice_id),
  appointment_id BIGINT REFERENCES appointments(appointment_id),
  kind TEXT NOT NULL CHECK (kind IN ('APPOINTMENT','REMINDER','SETTLED','CLAIM')),
  channel TEXT NOT NULL DEFAULT 'SMS (simulated)',
  message TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
  audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor TEXT NOT NULL DEFAULT 'system',
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_charges_encounter ON charges(encounter_id);
CREATE INDEX idx_invoices_issued ON invoices(issued_at);
CREATE INDEX idx_receipts_invoice ON receipts(invoice_id);
CREATE INDEX idx_claims_invoice ON claims(invoice_id);
CREATE INDEX idx_audit_entity ON audit_events(entity, entity_id);
CREATE INDEX idx_audit_created ON audit_events(created_at DESC);
CREATE INDEX idx_notifications_patient ON notifications(patient_id, created_at DESC);

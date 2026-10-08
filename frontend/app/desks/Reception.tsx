"use client";

import { useState } from "react";
import { Card, Ctx, Empty, Row, Tag, dateText, dateTime, money, payerText, statusTone, today } from "../lib";

export default function Reception({ ctx }: { ctx: Ctx }) {
  const { record, detail, catalog, busy, act, choose, selected } = ctx;
  const patient = record.patient || {};
  const enc = detail.encounter || {};
  const active = enc.encounter_id && enc.status !== "BILLED";
  const policies: Row[] = record.policies || [];
  const appts: Row[] = record.appointments || [];

  const [reg, setReg] = useState({ display_label: "", dob: "1990-01-01", sex: "Female", city: "Bengaluru", contact: "", abha_number: "", allergies: "" });
  const [pol, setPol] = useState({ payer_route: "PRIVATE", provider_name: "Alpha TPA", policy_no: "", valid_to: today(365), cover: 500000, copay_percent: 0 });
  const [appt, setAppt] = useState({ doctor_id: "D-01", slot_at: `${today()}T11:00`, reason: "" });
  const [visit, setVisit] = useState({ setting: "OPD", payment_mode: "SELF", policy_id: "" });
  const [deposit, setDeposit] = useState({ amount: 2000, method: "UPI" });

  async function register() {
    const created = await act("Patient registered with an MRN.", "/patients", { ...reg, abha_number: reg.abha_number.trim() });
    if (created) { await choose(created.patient_id); setReg({ ...reg, display_label: "", abha_number: "", contact: "" }); }
  }
  const visitBody = () => ({ ...visit, policy_id: visit.payment_mode === "SELF" ? "" : visit.policy_id || policies[0]?.policy_id || "" });
  const payerChoices = <>
    <div className="p-payer-choices">
      {[["SELF", "Self-pay", "Patient pays the bill"], ["CASHLESS", "Cashless", "Insurer / scheme pays after approval"], ["REIMBURSEMENT", "Reimbursement", "Patient pays, claims from insurer later"]].map(([id, name, hint]) =>
        <button key={id} className={visit.payment_mode === id ? "selected" : ""} disabled={id !== "SELF" && !policies.length} onClick={() => setVisit({ ...visit, payment_mode: id })}><b>{name}</b><span>{hint}</span></button>)}
    </div>
    {visit.payment_mode !== "SELF" && <label className="p-field">Insurance policy<select value={visit.policy_id || policies[0]?.policy_id} onChange={e => setVisit({ ...visit, policy_id: e.target.value })}>
      {policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.provider_name} · {p.policy_no} ({p.payer_route})</option>)}</select></label>}
    {!policies.length && <p className="p-fineprint">Add an insurance policy below to enable cashless or reimbursement.</p>}
  </>;

  return <>
    <div className="p-grid">
      <Card title="Register a new patient" sub="Registration & intake (ABHA)" icon="R">
        <label className="p-field">Full name<input value={reg.display_label} onChange={e => setReg({ ...reg, display_label: e.target.value })} placeholder="Synthetic name only" /></label>
        <div className="p-two-fields">
          <label className="p-field">Date of birth<input type="date" value={reg.dob} onChange={e => setReg({ ...reg, dob: e.target.value })} /></label>
          <label className="p-field">Sex<select value={reg.sex} onChange={e => setReg({ ...reg, sex: e.target.value })}><option>Female</option><option>Male</option><option>Other</option></select></label>
        </div>
        <div className="p-two-fields">
          <label className="p-field">City<input value={reg.city} onChange={e => setReg({ ...reg, city: e.target.value })} /></label>
          <label className="p-field">Mobile number<input type="tel" inputMode="numeric" maxLength={10} value={reg.contact} onChange={e => setReg({ ...reg, contact: e.target.value.replace(/\D/g, "").slice(0, 10) })} placeholder="10 digits" />{reg.contact && <small className="p-field-hint">{reg.contact.length === 10 ? `Saved masked as ${reg.contact[0]}XXXXX${reg.contact.slice(-4)}` : `${10 - reg.contact.length} more digit${reg.contact.length === 9 ? "" : "s"}`}</small>}</label>
        </div>
        <label className="p-field">ABHA number (optional)<input value={reg.abha_number} onChange={e => setReg({ ...reg, abha_number: e.target.value })} placeholder="XX-XXXX-XXXX-XXXX" /></label>
        <label className="p-field">Allergies<input value={reg.allergies} onChange={e => setReg({ ...reg, allergies: e.target.value })} placeholder="No known drug allergies" /></label>
        <button className="p-primary" disabled={busy || !reg.display_label.trim() || (reg.contact.length > 0 && reg.contact.length !== 10)} onClick={register}>Register patient</button>
        <p className="p-fineprint">The hospital MRN is generated automatically. ABHA links the record to the national health ID; it is optional.</p>
      </Card>

      <Card title="Insurance" sub={`${patient.display_label || "Patient"} · policies on file`} icon="I">
        {policies.length ? <div className="p-summary-list">{policies.map(p => <div key={p.policy_id}><span>{p.provider_name} · {p.policy_no}<small> · {p.payer_route} · valid to {dateText(p.valid_to)}{p.copay_bps ? ` · ${p.copay_bps / 100}% co-pay` : ""}</small></span><b>{money(p.coverage_amount_paise)}</b></div>)}</div> : <Empty>No policy on file. Self-pay only until one is added.</Empty>}
        <div className="p-mini-heading">Add a policy</div>
        <div className="p-two-fields">
          <label className="p-field">Payer<select value={pol.payer_route} onChange={e => setPol({ ...pol, payer_route: e.target.value, provider_name: { PRIVATE: "Alpha TPA", PMJAY: "PM-JAY", CGHS: "CGHS Bengaluru", CORPORATE: "Demo Employer Pvt Ltd" }[e.target.value] || "" })}>
            <option value="PRIVATE">Private insurer / TPA</option><option value="PMJAY">PM-JAY</option><option value="CGHS">CGHS</option><option value="CORPORATE">Corporate</option></select></label>
          <label className="p-field">Provider<input value={pol.provider_name} onChange={e => setPol({ ...pol, provider_name: e.target.value })} /></label>
        </div>
        <div className="p-two-fields">
          <label className="p-field">Policy number<input value={pol.policy_no} onChange={e => setPol({ ...pol, policy_no: e.target.value })} placeholder="SYN-POL-001" /></label>
          <label className="p-field">Cover (₹)<input type="number" value={pol.cover} onChange={e => setPol({ ...pol, cover: Number(e.target.value) })} /></label>
        </div>
        <div className="p-two-fields">
          <label className="p-field">Valid to<input type="date" value={pol.valid_to} onChange={e => setPol({ ...pol, valid_to: e.target.value })} /></label>
          <label className="p-field">Co-pay<select value={pol.copay_percent} onChange={e => setPol({ ...pol, copay_percent: Number(e.target.value) })}><option value={0}>None</option><option value={10}>10%</option><option value={20}>20%</option></select></label>
        </div>
        <button className="p-secondary" disabled={busy || !selected || pol.policy_no.trim().length < 3} onClick={() => act("Policy added.", `/patients/${selected}/policies`, { payer_route: pol.payer_route, provider_name: pol.provider_name, policy_no: pol.policy_no, valid_from: today(-30), valid_to: pol.valid_to, coverage_amount_paise: pol.cover * 100, copay_percent: pol.copay_percent, nominee: "Spouse" })}>Add policy</button>
      </Card>
    </div>

    <div className="p-grid">
      <Card title="Appointment" sub="Book, then check in on arrival" icon="A">
        {appts.length > 0 && <div className="p-summary-list">{appts.slice(0, 4).map(a => <div key={a.appointment_id}><span>{dateTime(a.slot_at)} · {a.doctor_name}<small> {a.reason}</small></span><Tag tone={statusTone(a.status === "CHECKED_IN" ? "COMPLETED" : a.status)}>{a.status.replace("_", " ")}</Tag></div>)}</div>}
        <div className="p-two-fields">
          <label className="p-field">Doctor<select value={appt.doctor_id} onChange={e => setAppt({ ...appt, doctor_id: e.target.value })}>{(catalog.doctors || []).map((d: Row) => <option key={d.doctor_id} value={d.doctor_id}>{d.name} · {d.department}</option>)}</select></label>
          <label className="p-field">Date and time<input type="datetime-local" value={appt.slot_at} onChange={e => setAppt({ ...appt, slot_at: e.target.value })} /></label>
        </div>
        <label className="p-field">Reason<input value={appt.reason} onChange={e => setAppt({ ...appt, reason: e.target.value })} placeholder="e.g. Fever, review" /></label>
        <button className="p-secondary" disabled={busy || !selected} onClick={() => act("Appointment booked. SMS confirmation logged (simulated).", "/appointments", { patient_id: selected, doctor_id: appt.doctor_id, slot_at: new Date(appt.slot_at).toISOString(), reason: appt.reason })}>Book appointment</button>
      </Card>

      <Card title={active ? "Current visit" : "Check in"} sub={active ? `${enc.encounter_id} · ${enc.setting}` : "Opens the Registration for this visit"} icon="✓">
        {active ? <>
          <div className="p-summary-list">
            <div><span>Payment route</span><b>{payerText(enc)}</b></div>
            <div><span>Status</span><Tag tone={statusTone(enc.status)}>{enc.status}</Tag></div>
            {enc.payment_mode === "CASHLESS" && <div><span>Insurance check</span><Tag tone={statusTone(detail.coverage?.eligibility_status)}>{detail.coverage?.eligibility_status}</Tag></div>}
            <div><span>Deposits taken</span><b>{money((detail.advances || []).reduce((s: number, a: Row) => s + a.amount_paise, 0))}</b></div>
          </div>
          {enc.payment_mode === "CASHLESS" && detail.coverage?.eligibility_status !== "VERIFIED" && <button className="p-primary" disabled={busy} onClick={() => act("Insurance verified against the policy (simulated insurer response).", `/coverage/${enc.encounter_id}/verify`)}>Verify insurance</button>}
          {enc.payer_route !== "PMJAY" && enc.status === "OPEN" && <>
            <div className="p-mini-heading">Deposit / co-pay at intake</div>
            <div className="p-two-fields">
              <label className="p-field">Amount (₹)<input type="number" min={1} value={deposit.amount} onChange={e => setDeposit({ ...deposit, amount: Number(e.target.value) })} /></label>
              <label className="p-field">Method<select value={deposit.method} onChange={e => setDeposit({ ...deposit, method: e.target.value })}><option>UPI</option><option>CASH</option><option>CARD</option></select></label>
            </div>
            <button className="p-secondary" disabled={busy || deposit.amount < 1} onClick={() => act("Deposit received.", "/advances", { encounter_id: enc.encounter_id, amount_paise: deposit.amount * 100, method: deposit.method })}>Take deposit</button>
          </>}
          <p className="p-fineprint">Next: the doctor sees the patient. Admission to a ward is decided by the doctor.</p>
        </> : <>
          {payerChoices}
          <label className="p-field">Visit type<select value={visit.setting} onChange={e => setVisit({ ...visit, setting: e.target.value })}><option value="OPD">Outpatient (OPD)</option><option value="EMERGENCY">Emergency</option><option value="DAY_CARE">Day care</option></select></label>
          <div className="p-action-row">
            {appts.filter(a => a.status === "BOOKED").slice(0, 1).map(a => <button key={a.appointment_id} className="p-primary" disabled={busy} onClick={() => act("Checked in from the appointment.", `/appointments/${a.appointment_id}/check-in`, visitBody())}>Check in ({dateTime(a.slot_at)})</button>)}
            <button className="p-secondary" disabled={busy || !selected} onClick={() => act("Walk-in visit opened.", "/encounters", { patient_id: selected, ...visitBody() })}>Walk-in visit</button>
          </div>
        </>}
      </Card>
    </div>
  </>;
}

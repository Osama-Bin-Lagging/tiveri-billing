"use client";

import { useState } from "react";
import { Card, Ctx } from "../lib";

// Reception: a separate screen for someone not yet in the system, so it never mixes with the selected patient.
export default function NewPatient({ ctx, onClose, onCreated }: { ctx: Ctx; onClose: () => void; onCreated: (patientId: string) => void }) {
  const { busy, act } = ctx;
  const [reg, setReg] = useState({ display_label: "", dob: "1990-01-01", sex: "Female", city: "Bengaluru", contact: "", abha_number: "", allergies: "" });
  const contactOk = reg.contact.length === 0 || reg.contact.length === 10;

  async function register() {
    const created = await act("", "/patients", { ...reg, abha_number: reg.abha_number.trim() });
    if (created) onCreated(created.patient_id);
  }

  return <Card title="Register a new patient" sub="Registration & intake (ABHA). The new patient opens on the Reception desk once saved." icon="+" wide>
    <div className="p-new-patient">
      <label className="p-field">Full name<input autoFocus value={reg.display_label} onChange={e => setReg({ ...reg, display_label: e.target.value })} placeholder="Synthetic name only" /></label>
      <div className="p-two-fields">
        <label className="p-field">Date of birth<input type="date" value={reg.dob} onChange={e => setReg({ ...reg, dob: e.target.value })} /></label>
        <label className="p-field">Sex<select value={reg.sex} onChange={e => setReg({ ...reg, sex: e.target.value })}><option>Female</option><option>Male</option><option>Other</option></select></label>
      </div>
      <div className="p-two-fields">
        <label className="p-field">City<input value={reg.city} onChange={e => setReg({ ...reg, city: e.target.value })} /></label>
        <label className="p-field">Mobile number<input type="tel" inputMode="numeric" maxLength={10} value={reg.contact} onChange={e => setReg({ ...reg, contact: e.target.value.replace(/\D/g, "").slice(0, 10) })} placeholder="10 digits" />
          {reg.contact && <small className="p-field-hint">{reg.contact.length === 10 ? `Saved masked as ${reg.contact[0]}XXXXX${reg.contact.slice(-4)}` : `${10 - reg.contact.length} more digit${reg.contact.length === 9 ? "" : "s"}`}</small>}</label>
      </div>
      <div className="p-two-fields">
        <label className="p-field">ABHA number (optional)<input value={reg.abha_number} onChange={e => setReg({ ...reg, abha_number: e.target.value })} placeholder="XX-XXXX-XXXX-XXXX" /></label>
        <label className="p-field">Allergies<input value={reg.allergies} onChange={e => setReg({ ...reg, allergies: e.target.value })} placeholder="No known drug allergies" /></label>
      </div>
      <div className="p-action-row">
        <button className="p-primary" disabled={busy || !reg.display_label.trim() || !contactOk} onClick={register}>Register patient</button>
        <button className="p-secondary" disabled={busy} onClick={onClose}>Cancel</button>
      </div>
      <p className="p-fineprint">The hospital MRN is generated automatically. ABHA links the record to the national health ID; it is optional.</p>
    </div>
  </Card>;
}

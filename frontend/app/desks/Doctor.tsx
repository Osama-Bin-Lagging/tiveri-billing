"use client";

import { useState } from "react";
import { Card, Ctx, Empty, Row, Tag, dateTime, money, statusTone } from "../lib";

type Med = { item_code: string; quantity: number; instruction: string };

export default function Doctor({ ctx }: { ctx: Ctx }) {
  const { detail, catalog, busy, act } = ctx;
  const enc = detail.encounter || {};
  const eid = enc.encounter_id;
  const open = eid && enc.status === "OPEN";
  const consults: Row[] = detail.consultations || [];
  const [notes, setNotes] = useState("");
  const [icd, setIcd] = useState("");
  const [rxNotes, setRxNotes] = useState("");
  const [labs, setLabs] = useState<string[]>([]);
  const [rads, setRads] = useState<string[]>([]);
  const [procs, setProcs] = useState<string[]>([]);
  const [meds, setMeds] = useState<Med[]>([]);
  const [admit, setAdmit] = useState(false);
  const [ward, setWard] = useState("W-GEN");
  const [outcome, setOutcome] = useState("Completed without complications.");

  const toggle = (list: string[], set: (v: string[]) => void, code: string) => set(list.includes(code) ? list.filter(c => c !== code) : [...list, code]);
  const orders: Row[] = [
    ...(detail.lab_orders || []).map((o: Row) => ({ ...o, kind: "LAB", id: o.lab_order_id, code: `LOINC ${o.loinc_code}` })),
    ...(detail.radiology_orders || []).map((o: Row) => ({ ...o, kind: "RADIOLOGY", id: o.rad_order_id, code: `SNOMED ${o.snomed_code}` })),
    ...(detail.procedure_orders || []).map((o: Row) => ({ ...o, kind: "PROCEDURE", id: o.proc_order_id, code: `SNOMED ${o.snomed_code}${o.outsourced ? " · outsourced" : ""}` })),
    ...(detail.pharmacy_orders || []).map((o: Row) => ({ ...o, kind: "PHARMACY", id: o.pharm_order_id, description: o.display_name, code: `${o.dispensed_quantity}/${o.quantity} given` })),
  ];
  const pending = orders.filter(o => ["ORDERED", "PARTIAL"].includes(o.status));
  const admitted = (detail.room_stays || []).find((s: Row) => !s.end_date);

  async function sendOrders() {
    const done = await act("Prescription saved. Orders sent to diagnostics and pharmacy.", "/clinical/prescriptions", {
      encounter_id: eid, icd_code: icd, notes: rxNotes, labs, procedures: procs,
      radiology: rads.map(code => ({ service_code: code, clinical_notes: rxNotes })),
      medicines: meds.filter(m => m.item_code), admit: admit && !admitted ? { ward_id: ward } : null,
    });
    if (done) { setLabs([]); setRads([]); setProcs([]); setMeds([]); setAdmit(false); setRxNotes(""); }
  }

  if (!eid || enc.status === "BILLED") return <Card title="No active visit" icon="+" wide><Empty>Reception checks the patient in first. The visit then appears here for consultation.</Empty></Card>;

  return <>
    <div className="p-grid">
      <Card title="Consultation" sub={`${enc.encounter_id} · ${enc.setting}`} icon="+">
        {consults.map(c => <div className="p-note" key={c.consult_id}><b>{dateTime(c.consult_at)} · {c.doctor_name}</b><p>{c.notes}</p></div>)}
        {open && <>
          <label className="p-field">Consultation notes<textarea rows={3} value={notes} onChange={e => setNotes(e.target.value)} placeholder="History, examination, impression" /></label>
          <button className={consults.length ? "p-secondary" : "p-primary"} disabled={busy || notes.trim().length < 10} onClick={async () => { if (await act("Consultation recorded; consultation fee posted to the running bill.", "/clinical/consultations", { encounter_id: eid, notes })) setNotes(""); }}>Record consultation</button>
        </>}
      </Card>

      <Card title="Prescription and orders" sub="Coded diagnosis, then any orders" icon="Rx">
        {!consults.length ? <Empty>Record the consultation first.</Empty> : !open ? <Empty>The visit is discharged.</Empty> : <>
          <label className="p-field">Diagnosis (ICD-10)<select value={icd} onChange={e => setIcd(e.target.value)}>
            <option value="">Choose a diagnosis…</option>
            {(catalog.diagnoses || []).map((d: Row) => <option key={d.icd_code} value={d.icd_code}>{d.icd_code} — {d.title} (SNOMED {d.snomed_code})</option>)}</select></label>
          <div className="p-check-groups">
            <div><div className="p-mini-heading">Laboratory</div>{(catalog.labs || []).map((t: Row) => <label key={t.service_code} className="p-check"><input type="checkbox" checked={labs.includes(t.service_code)} onChange={() => toggle(labs, setLabs, t.service_code)} /><span>{t.description}<small>LOINC {t.loinc_code} · {money(t.base_unit_paise)}</small></span></label>)}</div>
            <div><div className="p-mini-heading">Radiology</div>{(catalog.radiology || []).map((t: Row) => <label key={t.service_code} className="p-check"><input type="checkbox" checked={rads.includes(t.service_code)} onChange={() => toggle(rads, setRads, t.service_code)} /><span>{t.description}<small>SNOMED {t.snomed_code} · {money(t.base_unit_paise)}</small></span></label>)}</div>
            <div><div className="p-mini-heading">Procedures</div>{(catalog.procedures || []).map((t: Row) => <label key={t.service_code} className="p-check"><input type="checkbox" checked={procs.includes(t.service_code)} onChange={() => toggle(procs, setProcs, t.service_code)} /><span>{t.description}<small>SNOMED {t.snomed_code}{t.outsourced ? ` · ${t.partner}` : ""} · {money(t.base_unit_paise)}</small></span></label>)}</div>
          </div>
          <div className="p-mini-heading">Medicines</div>
          {meds.map((m, i) => <div className="p-med-row" key={i}>
            <select value={m.item_code} onChange={e => setMeds(meds.map((x, j) => j === i ? { ...x, item_code: e.target.value } : x))}>{(catalog.medicines || []).map((d: Row) => <option key={d.item_code} value={d.item_code}>{d.display_name}</option>)}</select>
            <input type="number" min={1} max={100} value={m.quantity} onChange={e => setMeds(meds.map((x, j) => j === i ? { ...x, quantity: Number(e.target.value) } : x))} />
            <input value={m.instruction} placeholder="Instruction" onChange={e => setMeds(meds.map((x, j) => j === i ? { ...x, instruction: e.target.value } : x))} />
            <button className="p-link" onClick={() => setMeds(meds.filter((_, j) => j !== i))}>Remove</button>
          </div>)}
          <button className="p-link" onClick={() => setMeds([...meds, { item_code: catalog.medicines?.[0]?.item_code || "", quantity: 10, instruction: "" }])}>+ Add medicine</button>
          {!admitted && <div className="p-admit"><label className="p-check"><input type="checkbox" checked={admit} onChange={e => setAdmit(e.target.checked)} /><span>Admit to a ward (IPD)</span></label>
            {admit && <select value={ward} onChange={e => setWard(e.target.value)}>{(catalog.wards || []).map((w: Row) => <option key={w.ward_id} value={w.ward_id}>{w.ward_name} · {money(w.base_unit_paise)}/day</option>)}</select>}</div>}
          <label className="p-field">Notes for the orders<input value={rxNotes} onChange={e => setRxNotes(e.target.value)} placeholder="e.g. Rule out consolidation" /></label>
          <button className="p-primary" disabled={busy || !icd || !(labs.length || rads.length || procs.length || meds.length || admit)} onClick={sendOrders}>Save prescription and send orders</button>
          <p className="p-fineprint">The diagnosis comes from the coded list, never free text. Charges post only when each service is completed.</p>
        </>}
      </Card>
    </div>

    <Card title="Orders and admission" sub={admitted ? `Admitted · ${admitted.ward_name} since ${admitted.start_date}` : (detail.prescriptions || []).map((p: Row) => `${p.icd_code} ${p.diagnosis}`).join(" · ") || "No prescription yet"} icon="≡" wide>
      {orders.length ? <div className="p-table"><table><thead><tr><th>Order</th><th>Code</th><th>Status</th><th></th></tr></thead><tbody>
        {orders.map(o => <tr key={`${o.kind}-${o.id}`}><td><b>{o.description}</b><small> {o.kind.toLowerCase()}</small></td><td>{o.code}</td><td><Tag tone={statusTone(o.status)}>{o.status}</Tag></td>
          <td className="p-row-actions">{open && o.kind === "PROCEDURE" && o.status === "ORDERED" && <button className="p-secondary" disabled={busy} onClick={() => act("Procedure recorded; charge posted.", `/procedures/${o.id}/perform`, { outcome_notes: outcome })}>Perform</button>}
            {open && ["ORDERED", "PARTIAL"].includes(o.status) && <button className="p-link" disabled={busy} onClick={() => act("Order cancelled. It will not be charged.", "/clinical/orders/cancel", { kind: o.kind, order_id: o.id, reason: "Cancelled by doctor" })}>Cancel</button>}</td></tr>)}
      </tbody></table></div> : <Empty>No orders yet.</Empty>}
      {open && (detail.procedure_orders || []).some((o: Row) => o.status === "ORDERED") && <label className="p-field">Procedure outcome note<input value={outcome} onChange={e => setOutcome(e.target.value)} /></label>}
      {open && <div className="p-discharge">
        <div><b>Discharge / end of visit</b><small>{pending.length ? `${pending.length} order(s) still pending — complete or cancel them first.` : admitted ? "Closes the ward stay and posts bed days, then billing can audit and bill." : "Ends the visit so billing can audit and bill."}</small></div>
        <button className="p-primary" disabled={busy || pending.length > 0 || !consults.length} onClick={() => act("Discharged. The visit is ready for the pre-bill audit.", `/encounters/${eid}/discharge`)}>{admitted ? "Discharge patient" : "End visit"}</button>
      </div>}
      {enc.status === "DISCHARGED" && <p className="p-fineprint">Discharged {dateTime(enc.discharged_at)}. Billing runs the pre-bill audit next.</p>}
    </Card>
  </>;
}

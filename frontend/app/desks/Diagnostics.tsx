"use client";

import { useEffect, useState } from "react";
import { Card, Ctx, Empty, Row, Tag, dateTime, statusTone } from "../lib";

export default function Diagnostics({ ctx }: { ctx: Ctx }) {
  const { detail, busy, act, load, choose, selected } = ctx;
  const [queue, setQueue] = useState<Row[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => { load("/diagnostics/queue").then(q => setQueue(q?.orders || [])); }, [load, detail]);

  const labs: Row[] = detail.lab_orders || [];
  const rads: Row[] = detail.radiology_orders || [];
  const pendingElsewhere = queue.filter(o => o.status === "ORDERED" && o.patient_id !== selected);
  const set = (key: string, v: string) => setValues({ ...values, [key]: v });

  return <>
    <div className="p-grid">
      <Card title="Laboratory" sub="Enter the result; the test charge posts once" icon="L">
        {labs.length ? labs.map(o => <div className="p-order" key={o.lab_order_id}>
          <div><b>{o.description}</b><small>LOINC {o.loinc_code} · ref {o.reference_range} {o.result_unit}</small></div>
          {o.status === "ORDERED" ? <div className="p-order-input">
            <input type="number" step="0.1" placeholder={o.result_unit} value={values[`L${o.lab_order_id}`] || ""} onChange={e => set(`L${o.lab_order_id}`, e.target.value)} />
            <button className="p-primary" disabled={busy || !Number(values[`L${o.lab_order_id}`])} onClick={() => act(`${o.description} result recorded; charge posted.`, `/lab/orders/${o.lab_order_id}/complete`, { result_value: Number(values[`L${o.lab_order_id}`]) })}>Complete test</button>
          </div> : <div><Tag tone={statusTone(o.status)}>{o.status}</Tag>{o.result_value != null && <small> {o.result_value} {o.result_unit} · {dateTime(o.report_date)}</small>}</div>}
        </div>) : <Empty>No lab orders on this visit.</Empty>}
      </Card>
      <Card title="Radiology" sub="Report the study; the charge posts with the report" icon="X">
        {rads.length ? rads.map(o => <div className="p-order" key={o.rad_order_id}>
          <div><b>{o.description}</b><small>{o.modality} · SNOMED {o.snomed_code}{o.clinical_notes ? ` · ${o.clinical_notes}` : ""}</small></div>
          {o.status === "ORDERED" ? <div className="p-order-input">
            <input placeholder="Findings" value={values[`R${o.rad_order_id}`] || ""} onChange={e => set(`R${o.rad_order_id}`, e.target.value)} />
            <button className="p-primary" disabled={busy || (values[`R${o.rad_order_id}`] || "").trim().length < 5} onClick={() => act(`${o.description} reported; charge posted.`, `/radiology/orders/${o.rad_order_id}/report`, { findings: values[`R${o.rad_order_id}`] })}>Submit report</button>
          </div> : <div><Tag tone={statusTone(o.status)}>{o.status}</Tag>{o.findings && <small> {o.findings}</small>}</div>}
        </div>) : <Empty>No radiology orders on this visit.</Empty>}
      </Card>
    </div>
    <Card title="Worklist" sub="Pending orders for other patients" icon="≡" wide>
      {pendingElsewhere.length ? <div className="p-summary-list">{pendingElsewhere.map(o => <div key={`${o.kind}-${o.order_id}`}>
        <span>{o.patient_label} · {o.description}<small> {o.kind.toLowerCase()} · ordered {dateTime(o.ordered_at)}</small></span>
        <button className="p-link" onClick={() => choose(o.patient_id)}>Open</button></div>)}</div> : <Empty>No other pending tests.</Empty>}
    </Card>
  </>;
}

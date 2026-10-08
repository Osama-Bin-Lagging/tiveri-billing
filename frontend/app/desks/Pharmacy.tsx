"use client";

import { useEffect, useState } from "react";
import { Card, Ctx, Empty, Row, Tag, money, statusTone } from "../lib";

export default function Pharmacy({ ctx }: { ctx: Ctx }) {
  const { detail, busy, act, load, choose, selected } = ctx;
  const [stock, setStock] = useState<Row[]>([]);
  const [queue, setQueue] = useState<Row[]>([]);
  const [qty, setQty] = useState<Record<number, number>>({});
  useEffect(() => {
    load("/pharmacy/stock").then(s => setStock(s?.items || []));
    load("/pharmacy/queue").then(q => setQueue(q?.orders || []));
  }, [load, detail]);

  const enc = detail.encounter || {};
  const orders: Row[] = detail.pharmacy_orders || [];
  const ipd = enc.setting === "IPD";

  return <>
    <Card title="Prescribed medicines" sub={ipd ? "Inpatient supply: part of exempt hospital care" : "Outpatient sale: item GST applies"} icon="Rx" wide>
      {orders.length ? orders.map(o => {
        const left = o.quantity - Number(o.dispensed_quantity);
        const item = stock.find(s => s.item_code === o.item_code);
        const n = Math.min(qty[o.pharm_order_id] ?? left, left);
        return <div className="p-order" key={o.pharm_order_id}>
          <div><b>{o.display_name}</b><small>{o.dispensed_quantity}/{o.quantity} given · {o.instruction || "as directed"} · {item ? `${item.available_units} in stock · ${money(item.unit_price_paise)} each · ${ipd ? "exempt (IPD)" : item.tax_category === "NIL" ? "nil GST" : `${item.tax_rate_bps / 100}% GST`}` : ""}</small></div>
          {["ORDERED", "PARTIAL"].includes(o.status) && enc.status === "OPEN" ? <div className="p-order-input">
            <input type="number" min={1} max={left} value={n} onChange={e => setQty({ ...qty, [o.pharm_order_id]: Number(e.target.value) })} />
            <button className="p-primary" disabled={busy || n < 1 || n > left} onClick={async () => { if (await act("Dispensed from the earliest-expiring batch; stock and bill updated.", "/pharmacy/dispense", { pharm_order_id: o.pharm_order_id, quantity: n, source_event_id: `DISP-${crypto.randomUUID()}` })) { const { [o.pharm_order_id]: _, ...rest } = qty; setQty(rest); } }}>Dispense</button>
          </div> : <Tag tone={statusTone(o.status)}>{o.status}</Tag>}
        </div>;
      }) : <Empty>No medicines prescribed on this visit.</Empty>}
    </Card>
    <div className="p-grid">
      <Card title="Worklist" sub="Other patients waiting" icon="≡">
        {queue.filter(o => o.patient_id !== selected).length ? <div className="p-summary-list">{queue.filter(o => o.patient_id !== selected).map(o =>
          <div key={o.pharm_order_id}><span>{o.patient_label} · {o.display_name}<small> {o.dispensed_quantity}/{o.quantity}</small></span><button className="p-link" onClick={() => choose(o.patient_id)}>Open</button></div>)}</div> : <Empty>Nobody else is waiting.</Empty>}
      </Card>
      <Card title="Stock" sub="Unexpired batches, earliest expiry used first" icon="M">
        <div className="p-summary-list">{stock.map(s => <div key={s.item_code}><span>{s.description}<small> {s.item_code} · HSN {s.hsn_code} · {s.tax_category === "REVIEW" ? "needs GST review" : s.tax_category === "NIL" ? "nil GST" : `${s.tax_rate_bps / 100}% GST`}</small></span><b>{s.available_units}</b></div>)}</div>
      </Card>
    </div>
  </>;
}

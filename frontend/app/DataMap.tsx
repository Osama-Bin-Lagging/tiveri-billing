"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ctx, Row, Tag, dateTime, money, statusTone } from "./lib";

const COLORS: Record<string, [string, string]> = {
  HIS: ["#e3edf7", "#3f6e99"], RIS: ["#dcf0ee", "#2c8c86"], LIS: ["#ece5f6", "#7457a5"], PHARMACY: ["#e5f2df", "#4d8a3c"],
  BILLING: ["#f8edd0", "#a07a1c"], INSURANCE: ["#f7e3d9", "#a8583a"],
};
const GROUP_NAME: Record<string, string> = { HIS: "HIS core", RIS: "Radiology", LIS: "Laboratory", PHARMACY: "Pharmacy", BILLING: "Billing", INSURANCE: "Payer" };
const BW = 140, BH = 48, BUS_Y = 660, BUS_X = 690;
// A few fields that identify a record at a glance, per table.
const SUMMARY: Record<string, string[]> = {
  patients: ["display_label", "mrn", "abha_number"], encounters: ["setting", "payment_mode", "status"], doctors: ["name", "specialization"],
  consultations: ["notes"], prescriptions: ["icd_code", "snomed_code"], room_stays: ["ward_id", "start_date", "end_date"], wards: ["ward_name", "ward_type"],
  radiology_orders: ["service_code", "status"], lab_orders: ["service_code", "status"], pharmacy_orders: ["item_code", "quantity", "status"],
  procedure_orders: ["service_code", "status"], radiology_results: ["findings"], lab_results: ["loinc_code", "result_value", "result_unit"],
  dispenses: ["item_code", "quantity"], procedures_performed: ["outcome_notes"], charges: ["description", "charge_type", "subtotal_paise"],
  invoice_lines: ["line_no", "description", "total_paise"], invoices: ["invoice_no", "total_paise"], receipts: ["method", "amount_paise", "status"],
  services: ["description", "base_unit_paise"], payer_rates: ["payer_route", "payer_label", "unit_paise"], tax_rules: ["rule_code", "tax_category", "rate_bps"],
  claims: ["attempt_no", "status", "approved_paise"], insurance_policies: ["provider_name", "policy_no"], appointments: ["slot_at", "status"],
  coverages: ["payer_label", "eligibility_status"], preauths: ["status", "approved_paise"], advances: ["amount_paise", "method"],
  balance_adjustments: ["kind", "amount_paise"], refunds: ["amount_paise"], notifications: ["kind", "message"],
};

const center = (e: Row) => e.kind === "relationship" ? { cx: e.x + 40, cy: e.y + 24, w: 80, h: 48 } : { cx: e.x + BW / 2, cy: e.y + BH / 2, w: BW, h: BH };
function show(col: string, v: any) {
  if (v === null || v === undefined || v === "") return "—";
  if (col.endsWith("_paise")) return money(Number(v));
  if (col.endsWith("_bps")) return `${Number(v) / 100}%`;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return dateTime(v);
  return String(v);
}
const TOP_Y = 124, MID_Y = 224;  // free corridors between rows
function edgePath(a: Row, b: Row, bus: boolean) {
  const A = center(a), B = center(b);
  if (bus) { // results -> shared "charges" bus -> trunk -> Charge (as in the team's ER diagram)
    const x1 = A.cx, y1 = A.cy + A.h / 2, y2 = B.cy + 10;
    return { d: `M${x1},${y1} V${BUS_Y} H${BUS_X} V${y2} H${B.cx - B.w / 2}`, mx: x1, my: (y1 + BUS_Y) / 2 };
  }
  if (b.key === "charge" && (a.key === "consultation" || a.key === "admits")) { // join the same trunk from above
    const y1 = A.cy - A.h / 2 + (a.key === "admits" ? A.h : 0), y2 = B.cy - 8;
    return { d: `M${A.cx},${y1} V${MID_Y} H${BUS_X} V${y2} H${B.cx - B.w / 2}`, mx: (A.cx + BUS_X) / 2, my: MID_Y };
  }
  if (a.key === "registration" && b.key === "charge") { // down into the shared trunk, entering Charge from the left
    const x1 = A.cx + 40, y1 = A.cy + A.h / 2;
    return { d: `M${x1},${y1} V${MID_Y} H${BUS_X} V${B.cy - 8} H${B.cx - B.w / 2}`, mx: BUS_X - 110, my: MID_Y };
  }
  if (a.key === "registration" && b.key === "bill") { // over the top of Ward
    const x2 = B.cx - 20;
    return { d: `M${A.cx + 30},${A.cy - A.h / 2} V${TOP_Y} H${x2} V${B.cy - B.h / 2}`, mx: (A.cx + x2) / 2, my: TOP_Y };
  }
  if (a.key === "claim" && b.key === "payment") { // down from the claim's corner, across, into Payment
    const x1 = A.cx + A.w / 2 - 6, y1 = A.cy + A.h / 2;
    return { d: `M${x1},${y1} V${TOP_Y + 6} H${B.cx} V${B.cy - B.h / 2}`, mx: (x1 + B.cx) / 2, my: TOP_Y + 6 };
  }
  const dx = B.cx - A.cx, dy = B.cy - A.cy;
  if (Math.abs(dx) > Math.abs(dy)) {
    const x1 = A.cx + Math.sign(dx) * A.w / 2, x2 = B.cx - Math.sign(dx) * B.w / 2, mid = (x1 + x2) / 2;
    return { d: `M${x1},${A.cy} C${mid},${A.cy} ${mid},${B.cy} ${x2},${B.cy}`, mx: mid, my: (A.cy + B.cy) / 2 };
  }
  const y1 = A.cy + Math.sign(dy) * A.h / 2, y2 = B.cy - Math.sign(dy) * B.h / 2, mid = (y1 + y2) / 2;
  return { d: `M${A.cx},${y1} C${A.cx},${mid} ${B.cx},${mid} ${B.cx},${y2}`, mx: (A.cx + B.cx) / 2, my: mid };
}

export default function DataMap({ ctx }: { ctx: Ctx }) {
  const { selected, record, detail, load } = ctx;
  const [schema, setSchema] = useState<Row | null>(null);
  const [data, setData] = useState<Row | null>(null);
  const [visit, setVisit] = useState("");
  const [active, setActive] = useState("registration");
  const [tab, setTab] = useState<"records" | "schema" | "timeline">("records");
  const [open, setOpen] = useState<string | null>(null);           // "entityKey:pk" of the expanded record
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const [query, setQuery] = useState("");
  const [miss, setMiss] = useState("");
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => { load("/datamap/schema").then(setSchema); }, [load]);
  useEffect(() => { setVisit(""); setOpen(null); }, [selected]);
  useEffect(() => { if (selected) load(`/datamap/${selected}${visit ? `?encounter_id=${visit}` : ""}`).then(setData); }, [selected, visit, detail, load]);

  const ents: Row[] = schema?.entities || [];
  const byKey = useMemo(() => Object.fromEntries(ents.map(e => [e.key, e])), [ents]);
  const keyOfTable = useMemo(() => Object.fromEntries(ents.map(e => [e.table, e.key]).reverse()), [ents]);
  const timeline: Row[] = data?.timeline || [];

  const rowsOf = useCallback((key: string): Row[] => data?.entities?.[key]?.rows || [], [data]);
  const count = (k: string) => rowsOf(k).length;

  const entity = byKey[active];
  const recs = rowsOf(active);
  const pkOf = (k: string) => byKey[k]?.pk;

  // Linked records: outgoing foreign keys and incoming references, one hop.
  const links = useCallback((key: string, r: Row) => {
    const out: { key: string; row: Row; via: string }[] = [], inc: { key: string; row: Row; via: string }[] = [];
    for (const a of byKey[key]?.attributes || []) {
      if (!a.fk || r[a.name] == null || !byKey[a.fk.entity]) continue;
      rowsOf(a.fk.entity).filter(x => String(x[a.fk.column]) === String(r[a.name])).forEach(row => out.push({ key: a.fk.entity, row, via: a.name }));
    }
    for (const e of ents) for (const a of e.attributes) {
      if (a.fk?.entity !== key) continue;
      rowsOf(e.key).filter(x => x[a.name] != null && String(x[a.name]) === String(r[a.fk.column])).forEach(row => inc.push({ key: e.key, row, via: a.name }));
    }
    return { out, inc };
  }, [byKey, ents, rowsOf]);

  const openRow = open ? (() => { const [k, id] = [open.slice(0, open.indexOf(":")), open.slice(open.indexOf(":") + 1)]; return { k, row: rowsOf(k).find(r => String(r[pkOf(k)]) === id) }; })() : null;
  const lineage = openRow?.row ? links(openRow.k, openRow.row) : null;
  // Trace: follow foreign keys outwards from the record (and from whatever points directly at it) to the root.
  const lit = useMemo(() => {
    const seen = new Set<string>(); if (!openRow?.row) return seen;
    const visit = (k: string, r: Row, depth: number) => {
      const id = `${k}:${r[pkOf(k)]}`; if (seen.has(id) || depth > 8) return; seen.add(id);
      links(k, r).out.forEach(o => visit(o.key, o.row, depth + 1));
    };
    visit(openRow.k, openRow.row, 0);
    lineage?.inc.forEach(i => visit(i.key, i.row, 1));
    return new Set([...seen].map(x => x.slice(0, x.indexOf(":"))));
  }, [openRow?.k, openRow?.row, lineage, links]);

  function goTo(key: string, row?: Row) {
    setActive(key); setTab("records");
    if (row) { setOpen(`${key}:${row[pkOf(key)]}`); setTimeout(() => document.querySelector(".p-dmx-rec.open")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 60); }
  }
  function search() {
    const q = query.trim().toLowerCase(); if (!q) return;
    for (const e of ents) for (const r of rowsOf(e.key)) {
      if (Object.entries(r).some(([c, v]) => !c.startsWith("_") && v != null && String(v).toLowerCase() === q)) { setMiss(""); goTo(e.key, r); return; }
    }
    setMiss(`Nothing matches “${query}”`);
  }
  // Zoom and pan (in SVG units)
  const W = schema?.canvas.width || 1200, H = schema?.canvas.height || 690;
  const zoom = (f: number) => setView(v => { const k = Math.min(3, Math.max(0.6, v.k * f)); const cx = v.x + W / v.k / 2, cy = v.y + H / v.k / 2; return { k, x: cx - W / k / 2, y: cy - H / k / 2 }; });
  const scale = () => (svgRef.current ? (W / view.k) / svgRef.current.clientWidth : 1);

  if (!schema) return <div className="p-card p-wide">Loading the data map…</div>;
  const total = ents.filter(e => e.kind !== "reference").reduce((s, e) => s + count(e.key), 0);

  return <div className="p-dmx">
    <div className="p-dmx-bar">
      <div className="p-dmx-title"><div className="p-kicker">DATA MAP · LIVE ER VIEW</div>
        <h2>{record.patient?.display_label}</h2><p>{total} records across {ents.filter(e => e.kind !== "reference" && count(e.key)).length} tables. Click a box, then a record, to follow its links.</p></div>
      <div className="p-dmx-tools">
        <select value={visit} onChange={e => { setVisit(e.target.value); setOpen(null); }} aria-label="Visit"><option value="">All visits</option>{(record.encounters || []).map((e: Row) => <option key={e.encounter_id} value={e.encounter_id}>{e.encounter_id} · {e.setting} · {e.status}</option>)}</select>
        <div className="p-dmx-search"><input value={query} placeholder="Find an ID, e.g. SYN-2026-00001" onChange={e => { setQuery(e.target.value); setMiss(""); }} onKeyDown={e => { if (e.key === "Enter") search(); }} /><button onClick={search}>Find</button></div>
      </div>
    </div>
    {miss && <div className="p-alert error">{miss}</div>}

    <div className="p-dmx-body">
      <div className="p-dmx-canvas">
        <div className="p-dmx-zoom"><button onClick={() => zoom(1.25)} aria-label="Zoom in">+</button><button onClick={() => zoom(0.8)} aria-label="Zoom out">−</button><button onClick={() => setView({ k: 1, x: 0, y: 0 })}>Fit</button></div>
        <svg ref={svgRef} viewBox={`${view.x} ${view.y} ${W / view.k} ${H / view.k}`} role="img" aria-label="ER diagram of this patient's records"
          onMouseDown={e => { drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; }}
          onMouseMove={e => { if (!drag.current) return; const s = scale(); setView(v => ({ ...v, x: drag.current!.vx - (e.clientX - drag.current!.x) * s, y: drag.current!.vy - (e.clientY - drag.current!.y) * s })); }}
          onMouseUp={() => { drag.current = null; }} onMouseLeave={() => { drag.current = null; }}>
          {(schema.lanes || []).map((l: Row) => <g key={l.label}><rect x={l.x} y={l.y} width={l.w} height={l.h} rx={14} className="p-dmx-lane" /><text x={l.x + 14} y={l.y + 18} className="p-dmx-lane-label">{l.label}</text></g>)}
          <line x1={100} y1={BUS_Y} x2={BUS_X} y2={BUS_Y} className="p-dmx-bus" />
          <text x={BUS_X - 6} y={BUS_Y - 6} textAnchor="end" className="p-dmx-rel-label">charges</text>
          {(schema.relations || []).map((r: Row, i: number) => {
            const a = byKey[r.from], b = byKey[r.to]; if (!a || !b) return null;
            const bus = r.to === "charge" && a.y >= 560;
            const { d, mx, my } = edgePath(a, b, bus);
            const on = count(r.from) > 0 && count(r.to) > 0;
            const hot = lit.size ? lit.has(r.from) && lit.has(r.to) : r.from === active || r.to === active;
            return <g key={i} className={`p-dmx-edge ${on ? "on" : ""} ${hot ? "hot" : ""}`}>
              <path d={d} />
              {!bus && r.label && !hot && <g transform={`translate(${mx},${my})`}><polygon points="0,-5 9,0 0,5 -9,0" className="p-dmx-diamond" /></g>}
            </g>;
          })}
          {ents.map(e => {
            const [fill, stroke] = COLORS[e.group] || COLORS.HIS; const n = count(e.key); const b = center(e);
            const cls = ["p-dmx-node", n ? "" : "empty", e.key === active ? "sel" : "", lit.size && !lit.has(e.key) ? "dim" : "", lit.has(e.key) ? "lit" : ""].join(" ");
            return <g key={e.key} className={cls} onClick={() => { setActive(e.key); setTab("records"); }}>
              {e.kind === "relationship"
                ? <polygon points={`${b.cx},${b.cy - 24} ${b.cx + 40},${b.cy} ${b.cx},${b.cy + 24} ${b.cx - 40},${b.cy}`} fill={fill} stroke={stroke} strokeWidth={2} />
                : <rect x={b.cx - BW / 2} y={b.cy - BH / 2} width={BW} height={BH} rx={e.kind === "workflow" ? 12 : 6} fill={fill} stroke={stroke} strokeWidth={2} strokeDasharray={e.kind === "reference" ? "5 4" : undefined} />}
              {e.kind === "weak" && <rect x={b.cx - BW / 2 + 4} y={b.cy - BH / 2 + 4} width={BW - 8} height={BH - 8} rx={3} fill="none" stroke={stroke} strokeWidth={1.4} />}
              {e.kind !== "relationship" && <rect x={b.cx - BW / 2} y={b.cy - BH / 2} width={5} height={BH} rx={2} fill={stroke} />}
              <text x={b.cx} y={b.cy + (e.kind === "relationship" ? 4 : 0)} textAnchor="middle" className="p-dmx-name">{e.er_name}</text>
              {e.kind !== "relationship" && <text x={b.cx} y={b.cy + 15} textAnchor="middle" className="p-dmx-table">{e.table}</text>}
              <g transform={`translate(${b.cx + b.w / 2 - 6},${b.cy - b.h / 2 + 2})`}><rect x={-16} y={-10} width={32} height={20} rx={10} fill={n ? stroke : "#c7d1d6"} /><text y={5} textAnchor="middle" className="p-dmx-count">{n}</text></g>
            </g>;
          })}
          {/* Highlighted relationship diamonds and names sit above the boxes so tight gaps stay readable. */}
          {(schema.relations || []).map((r: Row, i: number) => {
            const a = byKey[r.from], b = byKey[r.to]; if (!a || !b || !r.label) return null;
            const bus = r.to === "charge" && a.y >= 560;
            const hot = lit.size ? lit.has(r.from) && lit.has(r.to) : r.from === active || r.to === active;
            if (bus || !hot) return null;
            const { mx, my } = edgePath(a, b, bus); const A = center(a), B = center(b);
            const across = Math.abs(B.cy - A.cy) < 10;  // side by side in one row
            const tight = across && Math.abs(B.cx - A.cx) - (A.w + B.w) / 2 < 60;
            return <g key={`l${i}`} transform={`translate(${mx},${my})`} className="p-dmx-rel-top">
              <polygon points="0,-11 22,0 0,11 -22,0" className="p-dmx-diamond" />
              {r.from === "registration" && r.to === "bill" ? <text y={-16} textAnchor="middle" className="p-dmx-rel-label">{r.label}</text>
                : tight ? <text y={-Math.max(A.h, B.h) / 2 - 13} textAnchor="middle" className="p-dmx-rel-label">{r.label}</text>
                : across ? <text y={24} textAnchor="middle" className="p-dmx-rel-label">{r.label}</text>
                : <text x={27} y={4} className="p-dmx-rel-label">{r.label}</text>}
            </g>;
          })}
        </svg>
        <div className="p-dmx-legend">{Object.entries(COLORS).map(([g, [f, s]]) => <span key={g}><i style={{ background: f, borderColor: s }} />{GROUP_NAME[g]}</span>)}<span><i className="weak" />Weak entity</span><span><i className="ref" />Reference data</span><span><i className="diamond" />Relationship</span></div>
      </div>

      <aside className="p-dmx-inspector">
        <div className="p-dmx-head"><div className="p-kicker">{({ relationship: "RELATIONSHIP WITH DATA", reference: "REFERENCE DATA", weak: "WEAK ENTITY" } as Row)[entity?.kind] || "ER ENTITY"} · {GROUP_NAME[entity?.group]}</div>
          <h3>{entity?.er_name}</h3><small>table <code>{entity?.table}</code> · {recs.length} record{recs.length === 1 ? "" : "s"}</small></div>
        <div className="p-tabs">{(["records", "schema", "timeline"] as const).map(t => <button key={t} className={tab === t ? "selected" : ""} onClick={() => setTab(t)}>{t === "records" ? "Records" : t === "schema" ? "Keys & links" : "Timeline"}</button>)}</div>

        {tab === "records" && (recs.length ? <div className="p-dmx-recs">{recs.map(r => {
          const id = `${active}:${r[entity.pk]}`; const isOpen = open === id;
          const sum = (SUMMARY[entity.table] || []).map(c => show(c, r[c])).filter(x => x !== "—");
          const l = isOpen ? links(active, r) : null;
          return <div key={id} className={`p-dmx-rec ${isOpen ? "open" : ""}`}>
            <button className="p-dmx-rec-head" onClick={() => setOpen(isOpen ? null : id)}>
              <code>{show(entity.pk, r[entity.pk])}</code><span>{sum.join(" · ") || "—"}</span>{r.status && <Tag tone={statusTone(r.status)}>{r.status}</Tag>}<i>{isOpen ? "−" : "+"}</i></button>
            {isOpen && <>
              <div className="p-dmx-attrs">{entity.attributes.map((a: Row) => <div key={a.name} className={a.pk ? "pk" : a.fk ? "fk" : ""}>
                <small>{a.name}{a.pk ? " · PK" : a.fk ? ` → ${byKey[a.fk.entity]?.er_name || a.fk.entity}` : ""}</small>
                {a.fk && r[a.name] != null && byKey[a.fk.entity]
                  ? <button className="p-link" onClick={() => { const t = rowsOf(a.fk.entity).find(x => String(x[a.fk.column]) === String(r[a.name])); goTo(a.fk.entity, t); }}>{show(a.name, r[a.name])}</button>
                  : <b>{show(a.name, r[a.name])}</b>}</div>)}</div>
              {l && (l.out.length + l.inc.length > 0) && <div className="p-dmx-links">
                {l.out.length > 0 && <div><div className="p-mini-heading">Points to</div>{l.out.map((x, i) => <button key={`o${i}`} onClick={() => goTo(x.key, x.row)}>→ {byKey[x.key].er_name} <code>{show(pkOf(x.key), x.row[pkOf(x.key)])}</code></button>)}</div>}
                {l.inc.length > 0 && <div><div className="p-mini-heading">Referenced by</div>{l.inc.map((x, i) => <button key={`i${i}`} onClick={() => goTo(x.key, x.row)}>← {byKey[x.key].er_name} <code>{show(pkOf(x.key), x.row[pkOf(x.key)])}</code></button>)}</div>}
              </div>}
              {r._seq != null && <p className="p-fineprint">{(() => { const ev = timeline.find(t => Number(t.audit_id) === Number(r._seq)); return ev ? `Created by ${ev.actor} · ${dateTime(ev.created_at)} · ${ev.action.replaceAll("_", " ").toLowerCase()}` : ""; })()}</p>}
            </>}
          </div>;
        })}</div> : <p className="p-history">No {entity?.er_name} records for this patient yet. They appear as the workflow reaches this step.</p>)}

        {tab === "schema" && <div>
          <div className="p-table"><table><thead><tr><th>Attribute</th><th>Type</th><th>Key</th></tr></thead><tbody>
            {(entity?.attributes || []).map((a: Row) => <tr key={a.name}><td><code>{a.name}</code></td><td>{a.type}</td><td>{a.pk ? <Tag tone="green">PK</Tag> : a.fk ? <button className="p-link" onClick={() => setActive(a.fk.entity)}>FK → {byKey[a.fk.entity]?.er_name}</button> : ""}</td></tr>)}
          </tbody></table></div>
          <div className="p-mini-heading">Relationships</div>
          <div className="p-dmx-rels">{(schema.relations || []).filter((r: Row) => r.from === active || r.to === active).map((r: Row, i: number) => {
            const other = r.from === active ? r.to : r.from;
            return <button key={i} onClick={() => setActive(other)}><b>{byKey[r.from]?.er_name}</b> <span>{r.label || "—"}</span> <b>{byKey[r.to]?.er_name}</b> <code>{r.card_from || "·"} : {r.card_to || "·"}</code></button>;
          })}</div>
        </div>}

        {tab === "timeline" && <div className="p-dmx-timeline">{timeline.map(t => <button key={t.audit_id}
          onClick={() => { const k = keyOfTable[t.entity]; if (k) { const row = (data?.entities?.[k]?.rows || []).find((x: Row) => String(x[pkOf(k)]) === String(t.entity_id)); goTo(k, row); } }}>
          <small>{dateTime(t.created_at)}</small><b>{t.action.replaceAll("_", " ").toLowerCase()}</b><span>{t.actor} · {byKey[keyOfTable[t.entity]]?.er_name || t.entity.replaceAll("_", " ")} #{t.entity_id}</span></button>)}</div>}
      </aside>
    </div>
  </div>;
}

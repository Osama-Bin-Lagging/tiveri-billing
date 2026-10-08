"use client";

import { useEffect, useMemo, useState } from "react";
import { Ctx, Row, Tag, dateTime, money } from "./lib";

const COLORS: Record<string, [string, string]> = {
  HIS: ["#dbe7f3", "#3f6e99"], RIS: ["#d4ecea", "#2c8c86"], LIS: ["#e6def2", "#7457a5"], PHARMACY: ["#dfeed8", "#4d8a3c"],
  BILLING: ["#f6e8c6", "#a07a1c"], INSURANCE: ["#f4dcd0", "#a8583a"], WORKFLOW: ["#eceff1", "#7b8a94"],
};
const W = 150, H = 46, WW = 132, WH = 40;

function box(e: Row) {
  if (e.kind === "relationship") return { cx: e.x + 30, cy: e.y + 20, w: 60, h: 40 };
  if (e.kind === "workflow") return { cx: e.x + WW / 2, cy: e.y + WH / 2, w: WW, h: WH };
  return { cx: e.x + W / 2, cy: e.y + H / 2, w: W, h: H };
}
function edgePoint(b: { cx: number; cy: number; w: number; h: number }, tx: number, ty: number) {
  const dx = tx - b.cx, dy = ty - b.cy;
  if (!dx && !dy) return [b.cx, b.cy];
  const s = Math.min(Math.abs((b.w / 2) / (dx || 1e-9)), Math.abs((b.h / 2) / (dy || 1e-9)));
  return [b.cx + dx * s, b.cy + dy * s];
}
function show(col: string, v: any) {
  if (v === null || v === undefined || v === "") return "—";
  if (col.endsWith("_paise")) return money(Number(v));
  if (col.endsWith("_bps")) return `${Number(v) / 100}%`;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return dateTime(v);
  return String(v);
}

export default function DataMap({ ctx }: { ctx: Ctx }) {
  const { selected, record, detail, load } = ctx;
  const [schema, setSchema] = useState<Row | null>(null);
  const [data, setData] = useState<Row | null>(null);
  const [visit, setVisit] = useState("");
  const [active, setActive] = useState("registration");
  const [tab, setTab] = useState<"records" | "schema" | "timeline">("records");
  const [focus, setFocus] = useState<{ column: string; value: string } | null>(null);

  useEffect(() => { load("/datamap/schema").then(setSchema); }, [load]);
  useEffect(() => { setVisit(""); }, [selected]);
  useEffect(() => {
    if (selected) load(`/datamap/${selected}${visit ? `?encounter_id=${visit}` : ""}`).then(setData);
  }, [selected, visit, detail, load]);

  const ents: Row[] = schema?.entities || [];
  const byKey = useMemo(() => Object.fromEntries(ents.map(e => [e.key, e])), [ents]);
  const entity = byKey[active];
  const recs: Row[] = data?.entities?.[active]?.rows || [];
  const count = (k: string) => data?.entities?.[k]?.count || 0;

  function jump(target: string, column: string, value: any) {
    setActive(target); setTab("records"); setFocus({ column, value: String(value) });
    setTimeout(() => document.querySelector(".p-dm-row.focus")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 60);
  }

  if (!schema) return <div className="p-card p-wide">Loading the data map…</div>;
  return <div className="p-datamap">
    <div className="p-dm-toolbar">
      <div><div className="p-kicker">DATA MAP · LIVE ER VIEW</div><h2>{record.patient?.display_label} — every record the workflow has created</h2>
        <p>Boxes light up as records appear. Click a box to see its rows; click a linked ID to follow the relationship.</p></div>
      <label className="p-field">Visit<select value={visit} onChange={e => setVisit(e.target.value)}><option value="">All visits</option>{(record.encounters || []).map((e: Row) => <option key={e.encounter_id} value={e.encounter_id}>{e.encounter_id} · {e.setting} · {e.status}</option>)}</select></label>
    </div>
    <div className="p-dm-canvas">
      <svg viewBox={`0 0 ${schema.canvas.width} ${schema.canvas.height}`} role="img" aria-label="ER diagram of this patient's records">
        <defs><marker id="dot" markerWidth="6" markerHeight="6" refX="3" refY="3"><circle cx="3" cy="3" r="2" fill="#8aa0ad" /></marker></defs>
        <rect x="20" y="615" width="1160" height="85" rx="10" fill="#f6f8f9" stroke="#d8e0e4" strokeDasharray="4 4" />
        <text x="32" y="632" className="p-dm-band">WORKFLOW TABLES (not in the minimal ER diagram)</text>
        {(schema.relations || []).map((r: Row, i: number) => {
          const a = byKey[r.from], b = byKey[r.to]; if (!a || !b) return null;
          const A = box(a), B = box(b);
          const [x1, y1] = edgePoint(A, B.cx, B.cy), [x2, y2] = edgePoint(B, A.cx, A.cy);
          const lit = count(r.from) > 0 && count(r.to) > 0;
          const hot = r.from === active || r.to === active;
          return <g key={i} className={`p-dm-edge ${lit ? "lit" : ""} ${hot ? "hot" : ""}`}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} />
            {r.label && hot && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} textAnchor="middle" className="p-dm-rel">{r.label}</text>}
            {r.card_from && <text x={x1 + (x2 - x1) * 0.12} y={y1 + (y2 - y1) * 0.12 - 3} className="p-dm-card">{r.card_from}</text>}
            {r.card_to && <text x={x2 - (x2 - x1) * 0.12} y={y2 - (y2 - y1) * 0.12 - 3} className="p-dm-card">{r.card_to}</text>}
          </g>;
        })}
        {ents.map(e => {
          const [fill, stroke] = COLORS[e.group] || COLORS.HIS; const n = count(e.key); const sel = e.key === active;
          const b = box(e);
          return <g key={e.key} className={`p-dm-node ${n ? "" : "empty"} ${sel ? "sel" : ""}`} onClick={() => { setActive(e.key); setFocus(null); setTab("records"); }}>
            {e.kind === "relationship"
              ? <polygon points={`${b.cx},${b.cy - 20} ${b.cx + 30},${b.cy} ${b.cx},${b.cy + 20} ${b.cx - 30},${b.cy}`} fill={fill} stroke={stroke} strokeWidth={sel ? 3 : 1.5} />
              : <rect x={b.cx - b.w / 2} y={b.cy - b.h / 2} width={b.w} height={b.h} rx={e.kind === "workflow" ? 10 : 4} fill={fill} stroke={stroke} strokeWidth={sel ? 3 : 1.5} />}
            {e.kind === "weak" && <rect x={b.cx - b.w / 2 + 4} y={b.cy - b.h / 2 + 4} width={b.w - 8} height={b.h - 8} rx={2} fill="none" stroke={stroke} strokeWidth={1.2} />}
            <text x={b.cx} y={b.cy + (e.kind === "relationship" ? 4 : 2)} textAnchor="middle" className="p-dm-name">{e.er_name}</text>
            {e.kind !== "relationship" && <text x={b.cx} y={b.cy + 15} textAnchor="middle" className="p-dm-table">{e.table}</text>}
            <circle cx={b.cx + b.w / 2 - 4} cy={b.cy - b.h / 2 + 4} r={11} fill={n ? stroke : "#c9d2d7"} />
            <text x={b.cx + b.w / 2 - 4} y={b.cy - b.h / 2 + 8} textAnchor="middle" className="p-dm-count">{n}</text>
          </g>;
        })}
      </svg>
      <div className="p-dm-legend">{Object.entries(COLORS).map(([g, [f, s]]) => <span key={g}><i style={{ background: f, borderColor: s }} />{g === "HIS" ? "HIS core" : g === "RIS" ? "Radiology" : g === "LIS" ? "Laboratory" : g.charAt(0) + g.slice(1).toLowerCase()}</span>)}<span><i className="weak" />Weak entity</span><span><i className="diamond" />Relationship with data</span></div>
    </div>

    <section className="p-card p-wide p-dm-panel">
      <div className="p-dm-panel-head">
        <div><div className="p-kicker">{entity?.kind === "workflow" ? "WORKFLOW TABLE" : entity?.kind === "relationship" ? "RELATIONSHIP" : "ER ENTITY"}</div>
          <h3>{entity?.er_name} <small>· table <code>{entity?.table}</code> · {count(active)} record(s)</small></h3></div>
        <div className="p-tabs">{(["records", "schema", "timeline"] as const).map(t => <button key={t} className={tab === t ? "selected" : ""} onClick={() => setTab(t)}>{t === "records" ? "Records" : t === "schema" ? "Attributes & keys" : "Timeline"}</button>)}</div>
      </div>
      {tab === "records" && (recs.length ? <div className="p-dm-rows">{recs.map((r, i) => {
        const isFocus = focus && String(r[focus.column]) === focus.value;
        return <div key={i} className={`p-dm-row ${isFocus ? "focus" : ""}`}>
          {(entity?.attributes || []).map((a: Row) => <div key={a.name} className={a.pk ? "pk" : ""}>
            <small>{a.name}{a.pk ? " · PK" : a.fk ? ` → ${byKey[a.fk.entity]?.er_name || a.fk.entity}` : ""}</small>
            {a.fk && r[a.name] !== null && r[a.name] !== undefined && byKey[a.fk.entity]
              ? <button className="p-link" onClick={() => jump(a.fk.entity, a.fk.column, r[a.name])}>{show(a.name, r[a.name])}</button>
              : <b>{show(a.name, r[a.name])}</b>}
          </div>)}
        </div>;
      })}</div> : <p className="p-history">No {entity?.er_name} records for this patient yet. They appear as the workflow reaches this step.</p>)}
      {tab === "schema" && <div className="p-table"><table><thead><tr><th>Attribute</th><th>Type</th><th>Key</th></tr></thead><tbody>
        {(entity?.attributes || []).map((a: Row) => <tr key={a.name}><td><code>{a.name}</code></td><td>{a.type}</td><td>{a.pk ? <Tag tone="green">PK</Tag> : a.fk ? <button className="p-link" onClick={() => { setActive(a.fk.entity); setFocus(null); }}>FK → {byKey[a.fk.entity]?.er_name}</button> : ""}</td></tr>)}
      </tbody></table>
        <p className="p-fineprint">Relationships: {(schema.relations || []).filter((r: Row) => r.from === active || r.to === active).map((r: Row) => `${byKey[r.from]?.er_name} ${r.label || "—"} ${byKey[r.to]?.er_name} (${r.card_from || "·"}:${r.card_to || "·"})`).join(" · ") || "none"}</p></div>}
      {tab === "timeline" && <div className="p-timeline">{(data?.timeline || []).map((t: Row) => <div key={t.audit_id}>
        <small>{dateTime(t.created_at)}</small><b>{t.action.replaceAll("_", " ").toLowerCase()}</b><span>{t.actor} · {t.entity} #{t.entity_id}</span>
        {byKey[Object.keys(byKey).find(k => byKey[k].table === t.entity) || ""] && <button className="p-link" onClick={() => jump(Object.keys(byKey).find(k => byKey[k].table === t.entity)!, byKey[Object.keys(byKey).find(k => byKey[k].table === t.entity)!].pk, t.entity_id)}>open</button>}
      </div>)}</div>}
    </section>
  </div>;
}

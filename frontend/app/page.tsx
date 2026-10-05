"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type Obj = Record<string, any>;
type View = "Overview" | "Encounters" | "Pharmacy" | "Claims" | "Tax review" | "Receivables" | "Reports" | "Catalog" | "Audit";
const views: View[] = ["Overview", "Encounters", "Pharmacy", "Claims", "Tax review", "Receivables", "Reports", "Catalog", "Audit"];
const rupees = (n: number | undefined) => `₹${((n || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const paise = (v: string) => Math.round(Number(v || 0) * 100);
const today = () => new Date().toISOString().slice(0, 10);
const monthNow = () => new Date().toISOString().slice(0, 7);
const shortDate = (v?: string) => v ? new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`/api${path}`, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}
const post = (path: string, body: Obj = {}) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) { return <span className={`pill ${tone}`}>{children}</span>; }
function Panel({ title, action, children, className = "" }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-head"><h2>{title}</h2>{action}</div>{children}</section>;
}
function MoneyField({ value, onChange, label = "Amount (₹)" }: { value: string; onChange: (v: string) => void; label?: string }) {
  return <label>{label}<input type="number" min="0" step="0.01" value={value} onChange={e => onChange(e.target.value)} /></label>;
}

export default function Home() {
  const [view, setView] = useState<View>("Overview");
  const [boot, setBoot] = useState<Obj>({});
  const [dash, setDash] = useState<Obj>({});
  const [detail, setDetail] = useState<Obj>({});
  const [selected, setSelected] = useState("E-OPD-01");
  const [stock, setStock] = useState<Obj>({ items: [] });
  const [gstr, setGstr] = useState<Obj>({});
  const [ar, setAr] = useState<Obj>({});
  const [reports, setReports] = useState<Obj>({});
  const [audit, setAudit] = useState<Obj>({});
  const [period, setPeriod] = useState(monthNow());
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("Demo Patient H");
  const [newSetting, setNewSetting] = useState("OPD");
  const [newRoute, setNewRoute] = useState("SELF");
  const [newPayer, setNewPayer] = useState("");
  const [service, setService] = useState("CONSULT");
  const [quantity, setQuantity] = useState("1");
  const [roomCode, setRoomCode] = useState("WARD");
  const [roomStart, setRoomStart] = useState(today());
  const [roomEnd, setRoomEnd] = useState(new Date(Date.now() + 86400000).toISOString().slice(0, 10));
  const [packageCode, setPackageCode] = useState("HBP-DEMO-01");
  const [itemCode, setItemCode] = useState("MED-A");
  const [dispenseQty, setDispenseQty] = useState("1");
  const [prescription, setPrescription] = useState("RX-DEMO-01");
  const [amount, setAmount] = useState("1000");
  const [payerKind, setPayerKind] = useState("PATIENT");
  const [method, setMethod] = useState("UPI");
  const [diagnosis, setDiagnosis] = useState("Z00");
  const [summary, setSummary] = useState("Synthetic discharge summary for classroom demonstration.");
  const [rateService, setRateService] = useState("CONSULT");
  const [rateRoute, setRateRoute] = useState("PRIVATE");
  const [rateLabel, setRateLabel] = useState("");
  const [rateAmount, setRateAmount] = useState("450");

  const refresh = useCallback(async (encounterId = selected, periodValue = period) => {
    const [b, d, s, g, a, r, u] = await Promise.all([
      api("/bootstrap"), api("/dashboard"), api("/pharmacy/stock"),
      api(`/gstr1?month=${periodValue}`), api("/ar"), api(`/analytics?month=${periodValue}`), api("/audit?limit=80")
    ]);
    setBoot(b); setDash(d); setStock(s); setGstr(g); setAr(a); setReports(r); setAudit(u);
    if (encounterId) setDetail(await api(`/encounters/${encounterId}`));
  }, [selected, period]);

  useEffect(() => { refresh().catch(e => setError(e.message)); }, [refresh]);

  async function act(label: string, path: string, payload: Obj, follow?: (result: Obj) => void) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await post(path, payload);
      const next = follow ? (follow(result), result.encounter_id || selected) : selected;
      await refresh(next);
      setNotice(`${label} completed.`);
      return result;
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function selectEncounter(id: string) { setSelected(id); setView("Encounters"); setError(""); }
  const enc = detail.encounter || {};
  const inv = detail.invoice || null;
  const claim = detail.claim || null;
  const worklist = dash.worklist || [];
  const services = boot.services || [];
  const packages = boot.package_catalog || [];
  const activeClaim = (boot.claims || []).find((c: Obj) => c.invoice_id === inv?.invoice_id);
  const preauths = detail.preauths || [];
  const latestPreauth = preauths[preauths.length - 1];
  const canEdit = enc.status === "OPEN";
  const advanceTotal = (detail.advances || []).reduce((n: number, a: Obj) => n + a.amount_paise, 0);
  const refundTotal = (detail.refunds || []).reduce((n: number, a: Obj) => n + a.amount_paise, 0);
  const unusedAdvance = Math.max(0, advanceTotal - (inv?.advance_allocated_paise || 0) - refundTotal);
  function downloadReview() {
    const blob = new Blob([JSON.stringify(gstr, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `tiveri-gstr1-review-${period}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  const statement = useMemo(() => {
    const sum = (detail.charges || []).reduce((n: number, c: Obj) => n + (c.subtotal_paise || 0), 0);
    const tax = (detail.charges || []).reduce((n: number, c: Obj) => n + Math.round((c.subtotal_paise || 0) * (c.tax_rate_bps || 0) / 10000), 0);
    return { sum, tax, total: sum + tax };
  }, [detail]);

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-icon">T</span><span><strong>Tiveri</strong><small>HOSPITAL BILLING</small></span></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav>{views.map((v, i) => <button key={v} className={view === v ? "nav-item active" : "nav-item"} onClick={() => { if (v === "Claims" && (detail.encounter?.payer_route === "SELF" || !detail.encounter)) setSelected("E-IPD-02"); if (v === "Pharmacy" && detail.encounter?.status !== "OPEN") setSelected((boot.encounters || []).find((e: Obj) => e.status === "OPEN")?.encounter_id || "E-OPD-01"); setView(v); }}><span className="nav-symbol">{["▦", "▤", "▧", "▣", "≡", "▥", "▨", "☷", "▫"][i]}</span>{v}</button>)}</nav>
      <div className="side-foot"><div className="demo-dot" />Local teaching demo<br /><small>Synthetic data · No live portals</small></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><div className="eyebrow">DH 308 · FINAL PROJECT</div><h1>{view}</h1></div><div className="top-actions"><Pill tone="mint">● PostgreSQL connected</Pill><button className="ghost" onClick={() => refresh().catch(e => setError(e.message))}>Refresh data</button></div></header>
      <div className="notice-strip"><strong>Demo boundary</strong><span>All patients are invented. HIS events, insurer decisions, PM-JAY checks and GST filing are simulated.</span></div>
      {error && <div className="alert error"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
      {notice && <div className="alert success"><span>{notice}</span><button onClick={() => setNotice("")}>×</button></div>}
      {view === "Overview" && <div className="content">
        <div className="intro-card"><div><div className="eyebrow">SMALL HOSPITAL · 20–50 BEDS</div><h2>One patient journey, one running bill.</h2><p>Capture care activity from HIS, dispense from a batch, settle by patient or payer, then review revenue and tax.</p><button className="primary" onClick={() => selectEncounter("E-OPD-01")}>Open live patient workspace <span>↗</span></button></div><div className="intro-graphic"><div className="graphic-row"><span>HIS event</span><b>01</b></div><div className="graphic-row"><span>Running bill</span><b>02</b></div><div className="graphic-row"><span>Settlement</span><b>03</b></div></div></div>
        <div className="metric-grid"><div className="metric"><span>Open encounters</span><strong>{dash.open_encounters ?? "—"}</strong><small>OPD + IPD worklist</small></div><div className="metric"><span>Final invoices</span><strong>{dash.final_invoices ?? "—"}</strong><small>Itemised and immutable</small></div><div className="metric"><span>Outstanding</span><strong>{rupees(dash.unpaid_paise)}</strong><small>After advances and receipts</small></div><div className="metric"><span>Cash collected</span><strong>{rupees(dash.collections_paise)}</strong><small>Advance + receipt less refund</small></div></div>
        <Panel title="Patient worklist" action={<span className="muted">Choose a case to continue</span>}><div className="table-wrap"><table><thead><tr><th>Encounter</th><th>Patient</th><th>Setting</th><th>Payer</th><th>Running bill</th><th>Status</th><th></th></tr></thead><tbody>{worklist.map((w: Obj) => <tr key={w.encounter_id}><td><code>{w.encounter_id}</code></td><td>{w.patient_label}</td><td>{w.setting}</td><td>{w.payer_route}</td><td>{rupees(w.running_total_paise)}</td><td><Pill tone={w.status === "OPEN" ? "amber" : "mint"}>{w.status}</Pill></td><td><button className="text-button" onClick={() => selectEncounter(w.encounter_id)}>Open →</button></td></tr>)}</tbody></table></div></Panel>
        <div className="two-col"><Panel title="Coverage in this build"><div className="feature-list"><span>OPD and IPD billing</span><span>Three demo TPAs and pre-authorisation</span><span>Pharmacy stock and item-level GST</span><span>PM-JAY package and zero copay rule</span><span>GSTR-1 review and AR aging</span><span>Rate cards, advances and receipts</span></div></Panel><Panel title="Sample scenarios"><div className="scenario-list">{[["E-OPD-01", "OPD self pay + pharmacy"], ["E-IPD-02", "IPD and TPA claim"], ["E-IPD-03", "PM-JAY package"], ["E-OPD-04", "CGHS rate"], ["E-OPD-05", "Corporate credit"]].map(([id, label]) => <button key={id} onClick={() => selectEncounter(id)}><span>{label}</span><code>{id}</code></button>)}</div></Panel></div>
      </div>}

      {view === "Encounters" && <div className="content">
        <div className="two-col top-align"><Panel title="Start a synthetic encounter"><div className="form-grid"><label>Patient label<input value={newName} onChange={e => setNewName(e.target.value)} /></label><label>Setting<select value={newSetting} onChange={e => setNewSetting(e.target.value)}>{["OPD", "IPD", "EMERGENCY", "DAY_CARE"].map(x => <option key={x}>{x}</option>)}</select></label><label>Payer route<select value={newRoute} onChange={e => setNewRoute(e.target.value)}>{["SELF", "PRIVATE", "PMJAY", "CGHS", "CORPORATE"].map(x => <option key={x}>{x}</option>)}</select></label><label>Payer name<input value={newPayer} onChange={e => setNewPayer(e.target.value)} placeholder="e.g. Alpha TPA" /></label></div><button disabled={busy} className="primary" onClick={() => act("Encounter created", "/encounters", { display_label: newName, setting: newSetting, payer_route: newRoute, payer_label: newPayer }, r => setSelected(r.encounter_id))}>Create encounter</button></Panel>
          <Panel title="Current case" action={<select className="compact-select" value={selected} onChange={e => setSelected(e.target.value)}>{(boot.encounters || []).map((e: Obj) => <option key={e.encounter_id} value={e.encounter_id}>{e.encounter_id}</option>)}</select>}><div className="case-hero"><div><span className="eyebrow">{selected}</span><h3>{detail.patient?.display_label || "Loading..."}</h3><p>{enc.setting} · {enc.payer_route}{enc.payer_label ? ` · ${enc.payer_label}` : ""}</p></div><Pill tone={canEdit ? "amber" : "mint"}>{enc.status || "..."}</Pill></div><div className="case-numbers"><div><small>Running total</small><strong>{rupees(detail.running_total_paise)}</strong></div><div><small>Paid</small><strong>{rupees(detail.paid_paise)}</strong></div><div><small>Balance</small><strong>{rupees(detail.remaining_paise)}</strong></div></div></Panel></div>
        <div className="three-col">
          <Panel title="Capture HIS charge"><p className="helper">Each event ID is unique. Retrying the same event does not double bill.</p><label>Service<select value={service} onChange={e => setService(e.target.value)}>{services.filter((s: Obj) => !["PHARMACY", "PACKAGE", "ROOM"].includes(s.kind)).map((s: Obj) => <option key={s.service_code} value={s.service_code}>{s.description}</option>)}</select></label><label>Quantity<input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)} /></label><button disabled={busy || !canEdit} className="secondary" onClick={() => act("HIS service captured", "/his/events", { encounter_id: selected, service_code: service, quantity: Number(quantity), source_event_id: `HIS-${Date.now()}` })}>Capture service</button></Panel>
          <Panel title="Room or package"><label>Room<select value={roomCode} onChange={e => setRoomCode(e.target.value)}>{services.filter((s: Obj) => s.kind === "ROOM").map((s: Obj) => <option key={s.service_code} value={s.service_code}>{s.description}</option>)}</select></label><div className="form-grid"><label>From<input type="date" value={roomStart} onChange={e => setRoomStart(e.target.value)} /></label><label>To, exclusive<input type="date" value={roomEnd} onChange={e => setRoomEnd(e.target.value)} /></label></div><button disabled={busy || !canEdit || enc.setting !== "IPD"} className="secondary" onClick={() => act("Room stay posted", `/encounters/${selected}/room-stays`, { room_code: roomCode, start_date: roomStart, end_date: roomEnd })}>Add room stay</button><div className="divider" /><label>Package<select value={packageCode} onChange={e => setPackageCode(e.target.value)}>{packages.map((p: Obj) => <option key={p.package_code} value={p.package_code}>{p.package_code} · {p.note}</option>)}</select></label><button disabled={busy || !canEdit} className="secondary" onClick={() => act("Package applied", "/packages/apply", { encounter_id: selected, package_code: packageCode })}>Apply package</button></Panel>
          <Panel title="Bill and payment"><MoneyField value={amount} onChange={setAmount} /><label>Method<select value={method} onChange={e => setMethod(e.target.value)}>{["UPI", "CASH", "CARD", "TRANSFER"].map(x => <option key={x}>{x}</option>)}</select></label><div className="button-stack"><button disabled={busy || !canEdit || enc.payer_route === "PMJAY"} className="secondary" onClick={() => act("Advance received", "/advances", { encounter_id: selected, amount_paise: paise(amount), method })}>Record advance</button><button disabled={busy || !canEdit} className="primary" onClick={() => act("Invoice finalised", "/invoices", { encounter_id: selected })}>Finalise invoice</button></div>{inv && <div className="invoice-mini"><strong>{inv.invoice_no}</strong><span>{rupees(inv.total_paise)} total</span></div>}{inv && <><label>Receipt from<select value={payerKind} onChange={e => setPayerKind(e.target.value)}>{["PATIENT", "INSURER", "SCHEME", "CORPORATE"].map(x => <option key={x}>{x}</option>)}</select></label><button disabled={busy} className="secondary" onClick={() => act("Receipt posted", "/receipts", { invoice_id: inv.invoice_id, payer_kind: payerKind, amount_paise: paise(amount), method })}>Post receipt</button></>}</Panel>
        </div>
        {unusedAdvance > 0 && <div className="refund-box"><span>Unused patient advance: <strong>{rupees(unusedAdvance)}</strong></span><button disabled={busy || paise(amount) > unusedAdvance} className="secondary" onClick={() => act("Advance refunded", "/refunds", { encounter_id: selected, amount_paise: paise(amount), method })}>Refund entered amount</button></div>}
        <div className="two-col top-align"><Panel title={inv ? `Invoice ${inv.invoice_no}` : "Running bill"}><div className="table-wrap"><table><thead><tr><th>Service</th><th>Qty</th><th>Tax</th><th>Amount</th></tr></thead><tbody>{(detail.charges || []).map((c: Obj) => <tr key={c.charge_id}><td>{c.description}{c.included_in_package && <small className="line-note">Included in package</small>}</td><td>{c.quantity}</td><td>{c.tax_category === "TAXABLE" ? `${c.tax_rate_bps / 100}%` : c.tax_category}</td><td>{rupees(c.subtotal_paise + Math.round(c.subtotal_paise * c.tax_rate_bps / 10000))}</td></tr>)}</tbody></table></div><div className="totals"><div><span>Services</span><strong>{rupees(statement.sum)}</strong></div><div><span>GST in demo</span><strong>{rupees(statement.tax)}</strong></div><div className="grand"><span>Total</span><strong>{rupees(statement.total)}</strong></div></div></Panel><Panel title="Workflow record"><div className="record-grid"><span>Coverage</span><strong>{detail.coverage?.eligibility_status || "—"}</strong><span>Pre-authorisations</span><strong>{preauths.length}</strong><span>Pharmacy dispenses</span><strong>{detail.dispenses?.length || 0}</strong><span>Advances</span><strong>{rupees((detail.advances || []).reduce((n: number, a: Obj) => n + a.amount_paise, 0))}</strong><span>Claim</span><strong>{claim?.status || "Not submitted"}</strong><span>Receipts</span><strong>{detail.receipts?.length || 0}</strong></div></Panel></div>
      </div>}

      {view === "Pharmacy" && <div className="content"><div className="section-lead"><h2>Dispense, bill, and reduce stock together</h2><p>Batch tracking uses the earliest unexpired batch with enough stock. Tax values in this demo are training settings.</p></div><div className="two-col top-align"><Panel title="Dispense to patient"><label>Encounter<select value={selected} onChange={e => setSelected(e.target.value)}>{(boot.encounters || []).filter((e: Obj) => e.status === "OPEN").map((e: Obj) => <option key={e.encounter_id} value={e.encounter_id}>{e.encounter_id} · {e.payer_route}</option>)}</select></label><label>Item<select value={itemCode} onChange={e => setItemCode(e.target.value)}>{(stock.items || []).map((i: Obj) => <option key={i.item_code} value={i.item_code}>{i.description}</option>)}</select></label><div className="form-grid"><label>Units<input type="number" min="1" value={dispenseQty} onChange={e => setDispenseQty(e.target.value)} /></label><label>Prescription reference<input value={prescription} onChange={e => setPrescription(e.target.value)} /></label></div><button disabled={busy} className="primary" onClick={() => act("Medicine dispensed and billed", "/pharmacy/dispense", { encounter_id: selected, item_code: itemCode, quantity: Number(dispenseQty), prescription_ref: prescription, source_event_id: `RX-${Date.now()}` })}>Dispense and post charge</button></Panel><Panel title="Stock by batch"><div className="stock-list">{(stock.items || []).map((item: Obj) => <div className="stock-item" key={item.item_code}><div><strong>{item.description}</strong><small>{item.item_code} · HSN {item.hsn_code} · {item.tax_rule_code}</small></div><Pill tone="mint">{item.available_units} in stock</Pill><div className="batch-lines">{item.batches.map((b: Obj) => <span key={b.batch_id}>{b.batch_no} · {b.quantity_available} units · expires {shortDate(b.expiry_date)}</span>)}</div></div>)}</div></Panel></div></div>}

      {view === "Claims" && <div className="content"><div className="section-lead"><h2>Payer desk</h2><p>Pre-authorisation, eligibility checks, claim documents and payer settlement are simulated locally.</p></div><div className="two-col top-align"><Panel title="Selected payer case" action={<select className="compact-select" value={selected} onChange={e => setSelected(e.target.value)}>{(boot.encounters || []).filter((e: Obj) => e.payer_route !== "SELF").map((e: Obj) => <option key={e.encounter_id} value={e.encounter_id}>{e.encounter_id} · {e.payer_route}</option>)}</select>}><div className="case-hero"><div><span className="eyebrow">{selected}</span><h3>{detail.patient?.display_label || "—"}</h3><p>{enc.payer_route} · {enc.payer_label}</p></div><Pill tone="blue">{enc.status}</Pill></div><div className="record-grid"><span>Coverage</span><strong>{detail.coverage?.eligibility_status}</strong><span>Authorisation</span><strong>{latestPreauth?.status || "Not requested"}</strong><span>Claim</span><strong>{activeClaim?.status || "Not submitted"}</strong><span>Outstanding</span><strong>{rupees(detail.remaining_paise)}</strong></div>{enc.payer_route === "PMJAY" && <button disabled={busy} className="secondary" onClick={() => act("Synthetic beneficiary check", `/coverage/${selected}/verify`, { member_ref: `SYN-${selected}` })}>Run demo beneficiary check</button>}</Panel><Panel title="Pre-authorisation"><p className="helper">For private TPA and PM-JAY inpatient cases. This does not contact a payer.</p><MoneyField value={amount} onChange={setAmount} label="Request / approve amount (₹)" /><div className="button-stack"><button disabled={busy || !canEdit || !["PRIVATE", "PMJAY"].includes(enc.payer_route)} className="secondary" onClick={() => act("Demo pre-authorisation submitted", "/preauth", { encounter_id: selected, requested_paise: paise(amount) })}>Submit request</button><button disabled={busy || !latestPreauth || latestPreauth.status !== "SUBMITTED_DEMO"} className="primary" onClick={() => act("Demo pre-authorisation approved", `/preauth/${latestPreauth?.preauth_id}/decision`, { approved_paise: paise(amount), reference_no: `SYN-PRE-${Date.now()}` })}>Record approval</button></div></Panel></div><div className="two-col top-align"><Panel title="Prepare claim"><p className="helper">Finalise the invoice first. Attach an itemised bill and a discharge summary.</p><label>ICD-style diagnosis code<input value={diagnosis} onChange={e => setDiagnosis(e.target.value)} /></label><label>Discharge summary<textarea value={summary} onChange={e => setSummary(e.target.value)} rows={3} /></label><div className="checklist"><span>✓ Itemised invoice</span><span>✓ Discharge summary</span><span>✓ Payer and coverage route</span></div><button disabled={busy || !inv || !!claim || enc.payer_route === "SELF"} className="primary" onClick={() => act("Simulated claim submitted", "/claims", { invoice_id: inv.invoice_id, diagnosis_code: diagnosis, discharge_summary: summary, documents: { itemised_bill: true, discharge_summary: true } })}>Submit demo claim</button></Panel><Panel title="Decision and settlement"><p className="helper">An approval records a receivable. Post a separate receipt after money arrives.</p><MoneyField value={amount} onChange={setAmount} label="Approved / settled amount (₹)" /><button disabled={busy || !claim || claim.status !== "SUBMITTED_DEMO"} className="secondary" onClick={() => act("Demo claim approved", `/claims/${claim?.claim_id}/decision`, { approved_paise: paise(amount), reference_no: `SYN-CLAIM-${Date.now()}` })}>Record claim approval</button><button disabled={busy || !inv || !claim || claim.status !== "APPROVED_DEMO"} className="primary" onClick={() => act("Payer settlement posted", "/receipts", { invoice_id: inv?.invoice_id, payer_kind: enc.payer_route === "PMJAY" ? "SCHEME" : enc.payer_route === "CORPORATE" ? "CORPORATE" : "INSURER", amount_paise: paise(amount), method: "TRANSFER", reference_no: `SYN-SET-${Date.now()}` })}>Post payer receipt</button></Panel></div><Panel title="Claim register"><div className="table-wrap"><table><thead><tr><th>Claim</th><th>Invoice</th><th>Status</th><th>Submitted</th><th>Approved</th></tr></thead><tbody>{(boot.claims || []).map((c: Obj) => <tr key={c.claim_id}><td>CLM-{c.claim_id}</td><td>{c.invoice_id}</td><td><Pill tone={c.status === "APPROVED_DEMO" ? "mint" : "amber"}>{c.status}</Pill></td><td>{rupees(c.submitted_paise)}</td><td>{rupees(c.approved_paise)}</td></tr>)}</tbody></table></div></Panel></div>}

      {view === "Tax review" && <div className="content"><div className="section-lead"><h2>GSTR-1 review packet</h2><p>Taxable B2B, taxable B2C, exempt supplies, HSN summary and invoice count. This is for classroom review, not portal upload.</p></div><div className="tax-actions"><label className="period-filter">Month<input type="month" value={period} onChange={e => setPeriod(e.target.value)} /></label><button className="secondary" onClick={downloadReview}>Download review JSON</button></div><div className="metric-grid">{[["Table 4", "B2B taxable lines", gstr.tables?.table4?.length], ["Table 7", "B2C rate groups", gstr.tables?.table7?.length], ["Table 8", "Exempt / nil groups", gstr.tables?.table8?.length], ["Table 12", "HSN summaries", gstr.tables?.table12?.length]].map(([title, caption, n]) => <div className="metric" key={String(title)}><span>{title}</span><strong>{n ?? 0}</strong><small>{caption}</small></div>)}</div><div className="two-col top-align"><Panel title="Taxable supplies"><div className="table-wrap"><table><thead><tr><th>Section</th><th>Rate</th><th>Taxable value</th><th>Tax</th></tr></thead><tbody>{[...(gstr.tables?.table4 || []).map((r: Obj) => ({ ...r, section: "B2B" })), ...(gstr.tables?.table7 || []).map((r: Obj) => ({ ...r, section: "B2C" }))].map((r: Obj, i: number) => <tr key={i}><td>{r.section}</td><td>{r.rate_percent}%</td><td>{rupees(r.taxable_paise)}</td><td>{rupees(r.tax_paise)}</td></tr>)}</tbody></table></div></Panel><Panel title="Exempt and HSN"><div className="sub-title">Table 8</div>{(gstr.tables?.table8 || []).map((r: Obj, i: number) => <div className="list-row" key={i}><span>{r.category} · State {r.state_code}</span><strong>{rupees(r.value_paise)}</strong></div>)}<div className="sub-title">Table 12</div>{(gstr.tables?.table12 || []).map((r: Obj, i: number) => <div className="list-row" key={i}><span>HSN {r.hsn_sac} · {r.rate_percent}% · {r.quantity} units</span><strong>{rupees(r.taxable_paise)}</strong></div>)}</Panel></div><Panel title="Review warnings"><div className="warning-list">{(gstr.warnings || []).map((w: string, i: number) => <p key={i}>{w}</p>)}</div></Panel></div>}

      {view === "Receivables" && <div className="content"><div className="section-lead"><h2>Accounts receivable</h2><p>Outstanding invoices are aged from issue date after advance allocation and actual receipts.</p></div><div className="metric-grid">{[["Current", "current"], ["31–60 days", "days_31_60"], ["61–90 days", "days_61_90"], ["Over 90 days", "over_90"]].map(([label, key]) => <div className="metric" key={key}><span>{label}</span><strong>{rupees(ar.totals?.[key])}</strong><small>Unsettled balance</small></div>)}</div><Panel title="Open balances" action={<Pill tone="amber">Total {rupees(ar.totals?.total)}</Pill>}><div className="table-wrap"><table><thead><tr><th>Invoice</th><th>Patient</th><th>Payer</th><th>Issued</th><th>Age</th><th>Outstanding</th></tr></thead><tbody>{(ar.rows || []).map((r: Obj) => <tr key={r.invoice_id}><td>{r.invoice_no}</td><td>{r.patient_label}</td><td>{r.payer_route} · {r.payer_label}</td><td>{shortDate(r.issued_at)}</td><td>{r.age_days} days</td><td>{rupees(r.outstanding_paise)}</td></tr>)}</tbody></table></div></Panel></div>}

      {view === "Reports" && <div className="content"><div className="section-lead"><h2>Revenue and collection summary</h2><p>Numbers come from final invoices, receipts and advances in the local database.</p></div><label className="period-filter">Month<input type="month" value={period} onChange={e => setPeriod(e.target.value)} /></label><div className="metric-grid two-metrics"><div className="metric"><span>Invoiced revenue</span><strong>{rupees(reports.revenue_paise)}</strong><small>Final invoices in {period}</small></div><div className="metric"><span>Cash collected</span><strong>{rupees(reports.collections_paise)}</strong><small>Receipts plus advances</small></div></div><div className="two-col top-align"><Panel title="Payer mix">{(reports.payer_mix || []).map((r: Obj) => <div className="bar-row" key={r.payer_route}><div><strong>{r.payer_route}</strong><span>{rupees(r.revenue_paise)}</span></div><div className="bar-track"><i style={{ width: `${reports.revenue_paise ? Math.round(r.revenue_paise / reports.revenue_paise * 100) : 0}%` }} /></div></div>)}</Panel><Panel title="Department revenue">{(reports.department_revenue || []).map((r: Obj) => <div className="list-row" key={r.department}><span>{r.department}</span><strong>{rupees(r.revenue_paise)}</strong></div>)}</Panel></div></div>}

      {view === "Catalog" && <div className="content"><div className="section-lead"><h2>Charge master and payer rates</h2><p>Prices are snapped at charge capture. A rate change affects future charges only.</p></div><div className="two-col top-align"><Panel title="Set demo rate"><label>Service<select value={rateService} onChange={e => setRateService(e.target.value)}>{services.map((s: Obj) => <option key={s.service_code} value={s.service_code}>{s.description}</option>)}</select></label><label>Payer<select value={rateRoute} onChange={e => setRateRoute(e.target.value)}>{["SELF", "PRIVATE", "PMJAY", "CGHS", "CORPORATE"].map(x => <option key={x}>{x}</option>)}</select></label><label>Payer label, optional<input value={rateLabel} onChange={e => setRateLabel(e.target.value)} placeholder="e.g. Alpha TPA" /></label><MoneyField value={rateAmount} onChange={setRateAmount} label="Unit price (₹)" /><button disabled={busy} className="primary" onClick={() => act("Rate card updated", "/rates", { service_code: rateService, payer_route: rateRoute, payer_label: rateLabel, unit_paise: paise(rateAmount) })}>Save rate</button></Panel><Panel title="Package catalog">{packages.map((p: Obj) => <div className="package-card" key={p.package_code}><strong>{p.package_code}</strong><Pill tone="blue">{p.payer_route}</Pill><p>{p.note}</p><small>Includes {p.included_departments.join(", ")}</small></div>)}</Panel></div><Panel title="Services"><div className="table-wrap"><table><thead><tr><th>Code</th><th>Service</th><th>Department</th><th>Base unit</th><th>Tax rule</th></tr></thead><tbody>{services.map((s: Obj) => <tr key={s.service_code}><td><code>{s.service_code}</code></td><td>{s.description}</td><td>{s.department}</td><td>{rupees(s.base_unit_paise)}</td><td>{s.tax_rule_code}</td></tr>)}</tbody></table></div></Panel></div>}

      {view === "Audit" && <div className="content"><div className="section-lead"><h2>Action history</h2><p>Every important write records an event for the demo review trail.</p></div><Panel title="Recent events"><div className="table-wrap"><table><thead><tr><th>Time</th><th>Action</th><th>Entity</th><th>ID</th></tr></thead><tbody>{(audit.events || []).map((a: Obj) => <tr key={a.audit_id}><td>{new Date(a.created_at).toLocaleString("en-IN")}</td><td>{a.action.replaceAll("_", " ")}</td><td>{a.entity}</td><td><code>{a.entity_id}</code></td></tr>)}</tbody></table></div></Panel><div className="reset-box"><div><strong>Reset synthetic cases</strong><p>Restore the seeded patients and reports for another classroom walkthrough.</p></div><button disabled={busy} className="danger" onClick={() => { if (window.confirm("Reset synthetic demo cases?")) act("Demo reset", "/demo/reset", {}, () => setSelected("E-OPD-01")); }}>Reset demo data</button></div></div>}
    </main>
  </div>;
}

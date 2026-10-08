"use client";

import { useCallback, useEffect, useState } from "react";
import DataMap from "./DataMap";
import Billing from "./desks/Billing";
import Diagnostics from "./desks/Diagnostics";
import Doctor from "./desks/Doctor";
import Pharmacy from "./desks/Pharmacy";
import Reception from "./desks/Reception";
import { Ctx, Row, Staff, Tag, api, deskTitle, initials, payerText, post, roles, statusTone } from "./lib";

const FIRST_PATIENT = "P-DEMO-09";

function steps(detail: Row) {
  const enc = detail.encounter || {};
  const orders = [...(detail.lab_orders || []), ...(detail.radiology_orders || [])];
  const pharm = detail.pharmacy_orders || [];
  const rx = (detail.prescriptions || []).length > 0;
  const done = (s: string) => ["COMPLETED", "PERFORMED", "DISPENSED", "CANCELLED"].includes(s);
  return [
    { name: "Registration", note: enc.encounter_id ? enc.setting : "Check in", ok: !!enc.encounter_id },
    { name: "Doctor", note: (detail.prescriptions || []).length ? "Orders sent" : (detail.consultations || []).length ? "Consulted" : "Waiting", ok: (detail.prescriptions || []).length > 0 },
    { name: "Diagnostics", note: orders.length ? `${orders.filter(o => done(o.status)).length}/${orders.length} done` : rx ? "Not needed" : "—", ok: rx && orders.every(o => done(o.status)) },
    { name: "Pharmacy", note: pharm.length ? `${pharm.filter((o: Row) => done(o.status)).length}/${pharm.length} done` : rx ? "Not needed" : "—", ok: rx && pharm.every((o: Row) => done(o.status)) },
    { name: "Discharge", note: enc.status === "OPEN" ? "Visit open" : enc.status ? "Done" : "—", ok: ["DISCHARGED", "BILLED"].includes(enc.status) },
    { name: "Bill", note: detail.invoice?.invoice_no || (enc.status === "DISCHARGED" ? "Audit next" : "—"), ok: !!detail.invoice },
    { name: "Payer", note: enc.payment_mode === "CASHLESS" ? (detail.claims || []).slice(-1)[0]?.status || (detail.invoice ? "Claim next" : "—") : "Self-pay", ok: enc.payment_mode !== "CASHLESS" ? !!detail.invoice : ["APPROVED", "PARTIAL"].includes((detail.claims || []).slice(-1)[0]?.status) },
    { name: "Settled", note: detail.payment_status === "PAID" ? "Paid" : detail.invoice ? "Outstanding" : "—", ok: detail.payment_status === "PAID" },
  ];
}

export default function Home() {
  const [user, setUser] = useState<Staff | null>(null);
  const [loginRole, setLoginRole] = useState("reception");
  const [password, setPassword] = useState("Demo@1234");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(FIRST_PATIENT);
  const [patients, setPatients] = useState<Row[]>([]);
  const [record, setRecord] = useState<Row>({});
  const [detail, setDetail] = useState<Row>({});
  const [catalog, setCatalog] = useState<Row>({});
  const [visit, setVisit] = useState("");
  const [view, setView] = useState<"desk" | "map">("desk");

  const refresh = useCallback(async (patientId: string, encounterId = "") => {
    const [directory, patient] = await Promise.all([api("/patients"), api(`/patients/${patientId}`)]);
    setPatients(directory.patients || []); setRecord(patient);
    const eid = encounterId && patient.encounters?.some((e: Row) => e.encounter_id === encounterId) ? encounterId : patient.encounters?.[0]?.encounter_id || "";
    setVisit(eid);
    setDetail(eid ? await api(`/encounters/${eid}`) : {});
  }, []);

  useEffect(() => {
    const saved = sessionStorage.getItem("tiveri_patient_id") || FIRST_PATIENT;
    setSelected(saved);
    if (!sessionStorage.getItem("tiveri_token")) { setLoading(false); return; }
    api("/auth/me").then(async (staff: Staff) => { setCatalog(await api("/catalog")); await refresh(saved).catch(() => refresh(FIRST_PATIENT)); setUser(staff); })
      .catch(() => { sessionStorage.removeItem("tiveri_token"); setUser(null); }).finally(() => setLoading(false));
  }, [refresh]);

  async function login() {
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await post("/auth/login", { username: loginRole, password });
      sessionStorage.setItem("tiveri_token", response.token);
      setCatalog(await api("/catalog"));
      await refresh(selected).catch(() => refresh(FIRST_PATIENT));
      setUser(response.user);
    } catch (cause) { sessionStorage.removeItem("tiveri_token"); setError((cause as Error).message); } finally { setBusy(false); }
  }
  async function logout() { await api("/auth/logout", { method: "POST" }).catch(() => {}); sessionStorage.removeItem("tiveri_token"); setUser(null); setNotice(""); setError(""); }
  const choose = useCallback(async (patientId: string) => {
    setSelected(patientId); sessionStorage.setItem("tiveri_patient_id", patientId); setError(""); setNotice("");
    try { await refresh(patientId); } catch (cause) { setError((cause as Error).message); }
  }, [refresh]);
  const act = useCallback(async (label: string, path: string, payload: Row = {}) => {
    setBusy(true); setError(""); setNotice("");
    try { const result = await post(path, payload); await refresh(selected, visit); setNotice(label); return result; }
    catch (cause) { setError((cause as Error).message); return null; } finally { setBusy(false); }
  }, [refresh, selected, visit]);
  const load = useCallback(async (path: string) => { try { return await api(path); } catch (cause) { setError((cause as Error).message); return null; } }, []);
  async function resetDemo() {
    setBusy(true); setError("");
    try { await post("/demo/reset", {}); sessionStorage.removeItem("tiveri_token"); sessionStorage.setItem("tiveri_patient_id", FIRST_PATIENT); setSelected(FIRST_PATIENT); setUser(null); setNotice("Demo data restored. Sign in to begin again."); }
    catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  }

  if (loading) return <div className="p-loading">Opening the hospital demo…</div>;
  if (!user) return <main className="p-login">
    <section className="p-login-story"><div className="p-logo"><span>+</span><b>Syndicate 1</b><small>HOSPITAL OPERATIONS</small></div>
      <div className="p-login-copy"><div className="p-kicker">DH 308 · LIVE PROJECT</div><h1>One patient.<br />Five connected desks.</h1>
        <p>Follow a visit from registration through consultation, diagnostics, pharmacy and discharge to an audited bill, the insurer and the final payment.</p>
        <div className="p-steps"><span>Reception</span><i /><span>Doctor</span><i /><span>Diagnostics</span><i /><span>Pharmacy</span><i /><span>Billing</span></div></div>
      <div className="p-login-foot">Synthetic patients and results · Insurer, PM-JAY, SMS and GST portals are simulated</div></section>
    <section className="p-login-panel"><div className="p-login-inner"><div className="p-kicker">STAFF ACCESS</div><h2>Sign in for the demo</h2>
      <p>Finish a handoff, sign out, and open the next desk. The selected patient stays in view. Every desk can open the Data map.</p>
      <div className="p-role-grid">{roles.map(role => <button key={role.id} className={`p-role ${loginRole === role.id ? "selected" : ""}`} onClick={() => setLoginRole(role.id)}><span className="p-role-icon">{role.icon}</span><span><b>{role.name}</b><small>{role.task}</small></span><span>{loginRole === role.id ? "✓" : ""}</span></button>)}</div>
      <label className="p-field">Demo password<input type="password" value={password} onChange={e => setPassword(e.target.value)} onKeyDown={e => { if (e.key === "Enter") login(); }} /></label>
      <div className="p-hint">Password for all desks: <code>Demo@1234</code></div>
      {error && <div className="p-alert error">{error}</div>}{notice && <div className="p-alert success">{notice}</div>}
      <button className="p-primary p-signin" disabled={busy} onClick={login}>Continue as {roles.find(r => r.id === loginRole)?.name}<span>↗</span></button></div></section>
  </main>;

  const patient = record.patient || {};
  const enc = detail.encounter || {};
  const ctx: Ctx = { user, busy, selected, record, detail, catalog, act, load, choose };
  const Desk = { RECEPTION: Reception, DOCTOR: Doctor, LAB: Diagnostics, PHARMACY: Pharmacy, ADMIN: Billing }[user.role];
  const role = roles.find(r => r.role === user.role);

  return <div className={`p-shell ${view === "map" ? "map" : ""}`}>
    <aside className="p-sidebar"><div className="p-logo dark"><span>+</span><b>Syndicate 1</b></div>
      <div className="p-side-label">SIGNED IN</div><div className="p-side-person"><span>{role?.icon}</span><div><b>{deskTitle[user.role]}</b><small>{user.display_name}</small></div></div>
      <div className="p-side-tabs"><button className={view === "desk" ? "active" : ""} onClick={() => setView("desk")}>Desk</button><button className={view === "map" ? "active" : ""} onClick={() => setView("map")}>Data map</button></div>
      <div className="p-side-label">PATIENTS</div>
      <div className="p-side-list">{patients.map(row => <button key={row.patient_id} title={row.display_label} className={selected === row.patient_id ? "active" : ""} onClick={() => choose(row.patient_id)}>
        <span className="p-avatar">{initials(row.display_label)}</span><span><b>{row.display_label}</b><small>{row.mrn} · {row.latest_status ? `${row.latest_setting} ${row.latest_status.toLowerCase()}` : "no visit"}</small></span></button>)}</div>
      <div className="p-sidebar-foot"><span className="p-dot" /> PostgreSQL connected <button onClick={logout}>Sign out ↗</button></div>
    </aside>
    <main className="p-main">
      <header className="p-topbar"><div><div className="p-kicker">DH 308 · HIS AND BILLING</div><h1>{view === "map" ? "Data map" : deskTitle[user.role]}</h1></div>
        <div className="p-topright"><Tag tone="green">Live demo</Tag><span>{user.display_name}<small>{user.role.toLowerCase()}</small></span>
          {user.role === "ADMIN" && <button onClick={resetDemo} disabled={busy}>Reset demo</button>}<button className="p-top-signout" onClick={logout}>Sign out</button></div></header>
      <div className="p-content">
        {error && <div className="p-alert error">{error}<button onClick={() => setError("")}>×</button></div>}
        {notice && <div className="p-alert success">{notice}<button onClick={() => setNotice("")}>×</button></div>}
        {view === "desk" && <section className="p-patient"><div className="p-patient-top"><div><div className="p-kicker">PATIENT · {patient.mrn}{patient.abha_number ? ` · ABHA ${patient.abha_number}` : ""}</div>
          <h2>{patient.display_label || "Choose a patient"}</h2><p>{patient.age_years} years · {patient.sex} · {patient.city} · {patient.blood_group} · {patient.allergies}</p></div>
          <div className="p-patient-tags">{enc.encounter_id ? <><Tag>{enc.setting}</Tag><Tag tone={statusTone(enc.status)}>{enc.status}</Tag><Tag tone="blue">{payerText(enc)}</Tag></> : <Tag tone="amber">No visit yet</Tag>}
            {(record.encounters || []).length > 1 && <select className="p-visit-pick" value={visit} onChange={e => refresh(selected, e.target.value)}>{record.encounters.map((e: Row) => <option key={e.encounter_id} value={e.encounter_id}>{e.encounter_id} · {e.status}</option>)}</select>}</div></div>
          {patient.history_summary && <p className="p-history">{patient.history_summary}</p>}</section>}
        {view === "desk" && enc.encounter_id && <div className="p-flow">{steps(detail).map((s, i) => <div key={s.name} className={s.ok ? "done" : ""}><span>{s.ok ? "✓" : i + 1}</span><b>{s.name}</b><small>{s.note}</small></div>)}</div>}
        {view === "map" ? <DataMap ctx={ctx} /> : <Desk ctx={ctx} />}
      </div>
    </main>
  </div>;
}

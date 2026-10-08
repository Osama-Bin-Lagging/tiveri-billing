"use client";

import { useEffect, useState } from "react";
import { Card, Ctx, Empty, Row, Tag, dateText, dateTime, money, payerText, statusTone, today } from "../lib";

const lineTax = (c: Row) => { const s = c.subtotal_paise; const t = Math.round(Math.abs(s) * c.tax_rate_bps / 10000); return s < 0 ? -t : t; };
const typeLabel: Record<string, string> = { CHARGE: "", REVERSAL: "Reversal", PACKAGE_ADJ: "In package" };

export default function Billing({ ctx }: { ctx: Ctx }) {
  const { detail, catalog, busy, act, load } = ctx;
  const enc = detail.encounter || {};
  const eid = enc.encounter_id;
  const inv = detail.invoice;
  const cov = detail.coverage || {};
  const claims: Row[] = detail.claims || [];
  const claim = claims[claims.length - 1];
  const receipts: Row[] = detail.receipts || [];
  const preauth = (detail.preauths || [])[(detail.preauths || []).length - 1];
  const cashless = enc.payment_mode === "CASHLESS";

  const [audit, setAudit] = useState<Row | null>(null);
  const [reverseId, setReverseId] = useState<number | null>(null);
  const [reason, setReason] = useState("Posted in error (duplicate)");
  const [method, setMethod] = useState("UPI");
  const [preauthAmt, setPreauthAmt] = useState(15000);
  const [partial, setPartial] = useState({ amount: 0, reason: "Room rent above policy limit" });
  const [reject, setReject] = useState("Discharge summary incomplete");
  const [correction, setCorrection] = useState("Attached the missing documents.");
  const [finance, setFinance] = useState<Row | null>(null);

  useEffect(() => {
    setAudit(null);
    if (eid && enc.status === "DISCHARGED") load(`/encounters/${eid}/audit`).then(setAudit);
  }, [eid, enc.status, detail, load]);

  if (!eid) return <Card title="No visit yet" icon="₹" wide><Empty>Reception opens a visit first. Charges appear here as each service is completed.</Empty></Card>;

  const charges: Row[] = detail.charges || [];
  const runAudit = async () => setAudit(await load(`/encounters/${eid}/audit`));
  const reverse = async (id: number) => { if (await act("Charge reversed with a credit line. Nothing was deleted.", `/charges/${id}/reverse`, { reason })) { setReverseId(null); } };
  const shortfall = claim && ["PARTIAL", "REJECTED"].includes(claim.status) && detail.payer_share_paise > (claim.status === "PARTIAL" ? claim.approved_paise : detail.payer_received_paise);
  const insurerOpen = claim && ["APPROVED", "PARTIAL"].includes(claim.status) ? claim.approved_paise - (detail.payer_received_paise || 0) - receipts.filter(r => r.status === "PENDING" && r.payer_kind !== "PATIENT").reduce((s, r) => s + r.amount_paise, 0) : 0;
  const patientPending = receipts.filter(r => r.status === "PENDING" && r.payer_kind === "PATIENT").reduce((s, r) => s + r.amount_paise, 0);
  const patientCollect = Math.max(0, (detail.patient_due_paise || 0) - patientPending);
  const packages: Row[] = (catalog.packages || []).filter((p: Row) => p.payer_route === enc.payer_route && (enc.payer_route === "PMJAY" || enc.setting === "DAY_CARE"));
  const hasPackage = charges.some(c => c.kind === "PACKAGE" && c.charge_type === "CHARGE" && !c.offset_applied);
  const unusedDeposit = inv ? (detail.advances || []).reduce((s: number, a: Row) => s + a.amount_paise, 0) - (detail.refunds || []).reduce((s: number, a: Row) => s + a.amount_paise, 0) - (detail.deposit_used_paise || 0) : 0;
  const payerKind = enc.payer_route === "PRIVATE" ? "INSURER" : enc.payer_route === "CORPORATE" ? "CORPORATE" : "SCHEME";

  return <>
    <div className="p-grid">
      <Card title="Visit and payer" sub={`${eid} · ${enc.setting} · ${payerText(enc)}`} icon="P">
        <div className="p-summary-list">
          <div><span>Visit status</span><Tag tone={statusTone(enc.status)}>{enc.status}</Tag></div>
          {cashless && <div><span>Insurance check</span><Tag tone={statusTone(cov.eligibility_status)}>{cov.eligibility_status}</Tag></div>}
          {cashless && cov.copay_bps > 0 && <div><span>Patient co-pay</span><b>{cov.copay_bps / 100}%</b></div>}
          {cov.preauth_required && <div><span>Pre-authorisation</span>{preauth ? <span><Tag tone={statusTone(preauth.status)}>{preauth.status}</Tag> {preauth.status === "APPROVED" ? money(preauth.approved_paise) : ""}</span> : <Tag tone="amber">REQUIRED</Tag>}</div>}
          <div><span>Diagnosis</span><b>{[...new Set((detail.prescriptions || []).map((p: Row) => p.icd_code))].join(", ") || "—"}</b></div>
        </div>
        <div className="p-action-row">
          {cashless && cov.eligibility_status !== "VERIFIED" && enc.status !== "BILLED" && <button className="p-secondary" disabled={busy} onClick={() => act("Insurance verified (simulated).", `/coverage/${eid}/verify`)}>Verify insurance</button>}
          {packages.length > 0 && !hasPackage && enc.status !== "BILLED" && packages.map(p => <button key={p.package_code} className="p-secondary" disabled={busy} onClick={() => act(`Package ${p.package_code} applied; included services kept at their price and offset.`, "/packages/apply", { encounter_id: eid, package_code: p.package_code })}>Apply {p.package_code}</button>)}
        </div>
        {cov.preauth_required && enc.status !== "BILLED" && (!preauth || preauth.status === "REJECTED") && <div className="p-inline-form">
          <label className="p-field">Pre-auth amount (₹)<input type="number" value={preauthAmt} onChange={e => setPreauthAmt(Number(e.target.value))} /></label>
          <button className="p-primary" disabled={busy || cov.eligibility_status !== "VERIFIED" || preauthAmt < 1} onClick={() => act("Pre-authorisation requested from the insurer (simulated).", "/preauth", { encounter_id: eid, requested_paise: preauthAmt * 100 })}>Request pre-authorisation</button>
        </div>}
        {preauth?.status === "SUBMITTED" && <div className="p-sim"><span>Simulate insurer reply:</span>
          <button className="p-secondary" disabled={busy} onClick={() => act("Pre-authorisation approved.", `/preauth/${preauth.preauth_id}/decision`, { outcome: "APPROVED" })}>Approve</button>
          <button className="p-link" disabled={busy} onClick={() => act("Pre-authorisation rejected.", `/preauth/${preauth.preauth_id}/decision`, { outcome: "REJECTED" })}>Reject</button></div>}
      </Card>

      <Card title="Pre-bill audit" sub="Checks before the bill is made" icon="✓" tone={audit ? audit.passed ? "p-ok" : "p-bad" : ""}>
        {enc.status === "OPEN" ? <Empty>The doctor discharges / ends the visit first. Then the audit can run.</Empty> : enc.status === "BILLED" ? <Empty>Audit passed. Bill {inv?.invoice_no} issued.</Empty> : <>
          {audit && <>
            <div className={`p-audit-head ${audit.passed ? "ok" : "bad"}`}>{audit.passed ? "Audit passed — ready to bill" : "Audit failed — correct and re-audit"}</div>
            {audit.findings.map((f: Row, i: number) => <div className={`p-finding ${f.severity === "BLOCK" ? "block" : "warn"}`} key={i}>
              <b>{f.rule.replaceAll("_", " ")}</b><span>{f.message}</span>
              {f.charge_id && reverseId !== f.charge_id && <button className="p-link" onClick={() => setReverseId(f.charge_id)}>Reverse this charge</button>}
              {f.charge_id && reverseId === f.charge_id && <div className="p-inline-form"><input value={reason} onChange={e => setReason(e.target.value)} /><button className="p-primary" disabled={busy || !reason.trim()} onClick={() => reverse(f.charge_id)}>Confirm reversal</button></div>}
            </div>)}
          </>}
          <div className="p-action-row">
            <button className="p-secondary" disabled={busy} onClick={runAudit}>{audit ? "Re-audit" : "Run audit"}</button>
            <button className="p-primary" disabled={busy || !audit?.passed} onClick={() => act("Bill generated from the audited charges.", "/invoices", { encounter_id: eid })}>Generate bill</button>
          </div>
        </>}
      </Card>
    </div>

    <Card title={inv ? `Bill ${inv.invoice_no}` : "Running bill"} sub={inv ? `Issued ${dateText(inv.issued_at)} · due ${dateText(inv.due_date)}` : "Charges post as each service is completed"} icon="₹" wide>
      {charges.length ? <div className="p-table"><table><thead><tr><th>Service</th><th>Qty × rate</th><th>GST</th><th>Amount</th><th></th></tr></thead><tbody>
        {charges.map(c => <tr key={c.charge_id} className={c.charge_type !== "CHARGE" ? "p-offset" : c.offset_applied ? "p-struck" : ""}>
          <td><b>{c.description}</b>{typeLabel[c.charge_type] && <Tag tone={c.charge_type === "REVERSAL" ? "red" : "blue"}>{typeLabel[c.charge_type]}</Tag>}{c.source_type === "REPOST" && <Tag tone="green">Restored</Tag>}<small> {c.source_type.replaceAll("_", " ").toLowerCase()}{c.reason ? ` · ${c.reason}` : ""}</small></td>
          <td>{c.quantity} × {money(c.unit_price_paise)}</td>
          <td>{c.tax_category === "TAXABLE" ? `${c.tax_rate_bps / 100}%` : c.tax_category.toLowerCase()}</td>
          <td>{money(c.subtotal_paise + lineTax(c))}</td>
          <td className="p-row-actions">{c.charge_type === "CHARGE" && !c.offset_applied && enc.status !== "BILLED" && (reverseId === c.charge_id
            ? <span className="p-inline-form"><input value={reason} onChange={e => setReason(e.target.value)} /><button className="p-primary" disabled={busy || !reason.trim()} onClick={() => reverse(c.charge_id)}>Reverse</button></span>
            : <button className="p-link" onClick={() => setReverseId(c.charge_id)}>Reverse</button>)}</td>
        </tr>)}
      </tbody></table></div> : <Empty>No completed service has been charged yet.</Empty>}
      <div className="p-totals">
        <div><span>Subtotal</span><b>{money(inv?.subtotal_paise ?? detail.running_subtotal_paise)}</b></div>
        <div><span>GST</span><b>{money(inv?.tax_paise ?? detail.running_tax_paise)}</b></div>
        <div className="grand"><span>{inv ? "Bill total" : "Running total"}</span><b>{money(inv?.total_paise ?? detail.running_total_paise)}</b></div>
        {cashless && <><div><span>Patient share</span><b>{money(detail.patient_share_paise)}</b></div><div><span>Payer share</span><b>{money(detail.payer_share_paise)}</b></div></>}
        {(detail.deposit_used_paise || 0) > 0 && <div><span>Deposit applied</span><b>−{money(detail.deposit_used_paise)}</b></div>}
        {(detail.moved_to_patient_paise || 0) > 0 && <div><span>Claim shortfall moved to patient</span><b>{money(detail.moved_to_patient_paise)}</b></div>}
        {(detail.written_off_paise || 0) > 0 && <div><span>Written off</span><b>{money(detail.written_off_paise)}</b></div>}
        {inv && <div className="grand"><span>Still owed</span><b>{money(detail.remaining_paise)}</b></div>}
      </div>
      {inv && <button className="p-secondary" onClick={() => window.print()}>Print or save PDF</button>}
    </Card>

    {inv && <div className="p-grid">
      {cashless && <Card title="Insurance claim" sub={`${enc.payer_label} · approval is not payment`} icon="C">
        {claims.map(c => <div className="p-note" key={c.claim_id}><b>Attempt {c.attempt_no} · {dateTime(c.submitted_at)} · <Tag tone={statusTone(c.status)}>{c.status}</Tag></b>
          <p>Claimed {money(c.submitted_paise)}{["APPROVED", "PARTIAL"].includes(c.status) ? ` · approved ${money(c.approved_paise)}` : ""} · ICD {c.diagnosis_code}</p>
          {c.rejection_reason && <small>Reason: {c.rejection_reason}</small>}</div>)}
        {!claim && <button className="p-primary" disabled={busy} onClick={() => act("Claim submitted with the itemised bill and discharge summary.", "/claims", { invoice_id: inv.invoice_id, discharge_summary: `Treated for ${(detail.prescriptions || []).map((p: Row) => p.diagnosis).join(", ")}; discharged stable (synthetic).` })}>Submit claim</button>}
        {claim?.status === "SUBMITTED" && <div className="p-sim-box"><div className="p-mini-heading">Simulate the insurer's decision</div>
          <button className="p-secondary" disabled={busy} onClick={() => act("Claim approved in full. Payment still to come.", `/claims/${claim.claim_id}/decision`, { outcome: "APPROVED" })}>Approve in full</button>
          <div className="p-inline-form"><input type="number" placeholder="Approved ₹" value={partial.amount || ""} onChange={e => setPartial({ ...partial, amount: Number(e.target.value) })} /><input value={partial.reason} onChange={e => setPartial({ ...partial, reason: e.target.value })} />
            <button className="p-secondary" disabled={busy || !partial.amount} onClick={() => act("Claim partly approved.", `/claims/${claim.claim_id}/decision`, { outcome: "PARTIAL", approved_paise: partial.amount * 100, reason: partial.reason })}>Approve part</button></div>
          <div className="p-inline-form"><input value={reject} onChange={e => setReject(e.target.value)} />
            <button className="p-link" disabled={busy || !reject.trim()} onClick={() => act("Claim rejected. A notice was logged for the patient.", `/claims/${claim.claim_id}/decision`, { outcome: "REJECTED", reason: reject })}>Reject</button></div>
        </div>}
        {claim?.status === "REJECTED" && <div className="p-inline-form"><input value={correction} onChange={e => setCorrection(e.target.value)} />
          <button className="p-primary" disabled={busy || !correction.trim()} onClick={() => act("Claim corrected and resubmitted.", `/claims/${claim.claim_id}/resubmit`, { correction_note: correction })}>Resubmit claim</button></div>}
        {shortfall && <div className="p-sim-box"><div className="p-mini-heading">Insurer will not pay {money(detail.payer_share_paise - (claim.status === "PARTIAL" ? claim.approved_paise : detail.payer_received_paise))}</div>
          {enc.payer_route !== "PMJAY" && <button className="p-primary" disabled={busy} onClick={() => act("Shortfall moved to the patient (self-pay path).", `/invoices/${inv.invoice_id}/shortfall`, { action: "TO_PATIENT" })}>Bill the patient</button>}
          <button className="p-link" disabled={busy} onClick={() => act("Shortfall written off.", `/invoices/${inv.invoice_id}/shortfall`, { action: "WRITE_OFF" })}>Write off</button></div>}
        {insurerOpen > 0 && <button className="p-primary" disabled={busy} onClick={() => act("Insurer payment received.", "/receipts", { invoice_id: inv.invoice_id, payer_kind: payerKind, amount_paise: insurerOpen, method: "TRANSFER", reference_no: `NEFT-SYN-${inv.invoice_id}` })}>Record insurer payment {money(insurerOpen)}</button>}
      </Card>}

      <Card title="Patient payment" sub={`Status: ${detail.payment_status}`} icon="₹">
        <div className="p-summary-list">
          <div><span>Patient owes</span><b>{money(detail.patient_due_paise)}</b></div>
          {cashless && <div><span>Payer owes</span><b>{money(detail.payer_due_paise)}</b></div>}
        </div>
        {receipts.map(r => <div className="p-note" key={r.receipt_id}><b>{r.payer_kind.toLowerCase()} · {r.method} · {money(r.amount_paise)} · <Tag tone={statusTone(r.status)}>{r.status}</Tag>{r.attempt_no > 1 ? <small> retry #{r.attempt_no}</small> : null}</b>
          {r.status === "PENDING" && <div className="p-sim"><span>Simulate:</span>
            <button className="p-secondary" disabled={busy} onClick={() => act("Payment succeeded.", `/receipts/${r.receipt_id}/outcome`, { outcome: "SUCCEEDED" })}>Success</button>
            <button className="p-link" disabled={busy} onClick={() => act("Payment failed. Retry with another mode.", `/receipts/${r.receipt_id}/outcome`, { outcome: "FAILED" })}>Fail</button>
            <button className="p-link" disabled={busy} onClick={() => act("Payment timed out. Retry.", `/receipts/${r.receipt_id}/outcome`, { outcome: "TIMEOUT" })}>Timeout</button></div>}
          {["FAILED", "TIMEOUT"].includes(r.status) && !receipts.some(x => x.retry_of === r.receipt_id) && <div className="p-sim"><span>Retry with:</span>
            {["UPI", "CARD", "CASH"].map(m => <button key={m} className="p-secondary" disabled={busy} onClick={() => act(`Retry started with ${m}.`, `/receipts/${r.receipt_id}/retry`, { method: m })}>{m}</button>)}</div>}
        </div>)}
        {patientCollect > 0 && enc.payer_route !== "PMJAY" && <>
          <div className="p-payment-method-options">{["UPI", "CARD", "CASH", "GATEWAY"].map(m => <button key={m} className={method === m ? "selected" : ""} onClick={() => setMethod(m)}>{m === "GATEWAY" ? "Gateway" : m}</button>)}</div>
          <button className="p-primary" disabled={busy} onClick={() => act(method === "CASH" ? "Cash received." : `${method} payment started — waiting for confirmation.`, "/receipts", { invoice_id: inv.invoice_id, payer_kind: "PATIENT", amount_paise: patientCollect, method })}>Collect {money(patientCollect)}</button>
        </>}
        {enc.payment_mode === "REIMBURSEMENT" && <p className="p-fineprint">Reimbursement: the patient pays the hospital, then claims from their insurer with this itemised bill.</p>}
        {unusedDeposit > 0 && <button className="p-link" disabled={busy} onClick={() => act("Unused deposit refunded.", "/refunds", { encounter_id: eid, amount_paise: unusedDeposit, method: "UPI" })}>Refund unused deposit {money(unusedDeposit)}</button>}
      </Card>
    </div>}

    {inv && <Card title="Ledger and patient messages" sub="Reminders and notifications are simulated (no real SMS)" icon="✉" wide>
      <div className="p-ledger"><div><small>Outstanding</small><b>{money(detail.remaining_paise)}</b></div><div><small>Status</small><Tag tone={statusTone(detail.payment_status)}>{detail.payment_status === "PAID" ? "BILL SETTLED" : detail.payment_status}</Tag></div>
        {detail.remaining_paise > 0 && <button className="p-secondary" disabled={busy} onClick={() => act("Reminder sent (simulated SMS).", `/invoices/${inv.invoice_id}/remind`)}>Send reminder</button>}</div>
      {(detail.notifications || []).length ? (detail.notifications || []).map((n: Row) => <div className="p-note" key={n.notification_id}><b>{dateTime(n.created_at)} · {n.kind} · {n.channel}</b><p>{n.message}</p></div>) : <Empty>No messages yet.</Empty>}
    </Card>}

    <section className="p-card p-tax-review"><div><h3>Finance</h3><p>Unpaid bills by age, and this month's GST review packet (not a filing).</p></div>
      <button className="p-secondary" disabled={busy} onClick={async () => setFinance({ ar: await load("/ar"), gst: await load(`/gstr1?month=${today().slice(0, 7)}`) })}>Load reports</button>
      {finance && <div className="p-tax-results"><span>Outstanding: {money(finance.ar?.totals?.total)}</span><span>Over 30 days: {money((finance.ar?.totals?.days_31_60 || 0) + (finance.ar?.totals?.days_61_90 || 0) + (finance.ar?.totals?.over_90 || 0))}</span><span>B2B lines: {finance.gst?.tables?.table4?.length || 0}</span><span>Exempt / nil groups: {finance.gst?.tables?.table8?.length || 0}</span><span>HSN rows: {finance.gst?.tables?.table12?.length || 0}</span></div>}
    </section>
  </>;
}

let db = null;
let view = 'overview';
let selected = 'E-IPD-02';
let tab = 'charges';
let modalAction = null;
let toastTimer = null;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const money = paise => '₹' + ((paise || 0) / 100).toLocaleString('en-IN', {minimumFractionDigits:0,maximumFractionDigits:2});
const find = (table, field, value) => db[table].find(item => item[field] === value);
const sum = (rows, field) => rows.reduce((total, row) => total + row[field], 0);
const date = iso => new Date(iso).toLocaleString('en-IN', {dateStyle:'medium',timeStyle:'short'});
const routeLabel = route => ({SELF:'Self pay',PRIVATE:'Private insurance',PMJAY:'PM-JAY',CGHS:'CGHS',CORPORATE:'Corporate credit'})[route] || route;
const payerReceipt = route => ({PRIVATE:'INSURER',PMJAY:'SCHEME',CGHS:'SCHEME',CORPORATE:'CORPORATE'})[route];
const status = value => ({SUBMITTED_DEMO:'Submitted in demo',APPROVED_DEMO:'Approved in demo',REJECTED_DEMO:'Rejected in demo'})[value] || 'Not started';
const badge = (label, tone='gray') => `<span class="tag tag-${tone}">${esc(label)}</span>`;

async function api(path, method='GET', body=null) {
  const response = await fetch(path, {method, headers:{'Content-Type':'application/json'}, body:body === null ? null : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function toast(message, error=false) {
  const node=$('toast'); node.textContent=message; node.classList.toggle('error',error); node.classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>node.classList.remove('show'),4000);
}
async function refresh() { db=await api('/api/state'); if (!db.encounter.some(row=>row.encounter_id===selected)) selected=db.encounter[0]?.encounter_id; render(); }
async function perform(action, message) { try { const result=await action(); await refresh(); if(message) toast(message); return result; } catch(error) { toast(error.message,true); return null; } }

function record(id) {
  const encounter=find('encounter','encounter_id',id);
  if (!encounter) return null;
  const patient=find('patient','patient_id',encounter.patient_id);
  const coverage=db.coverage.find(row=>row.patient_id===patient.patient_id && row.payer_kind===encounter.payer_route);
  const charges=db.charge.filter(row=>row.encounter_id===id);
  const preauth=db.preauth.find(row=>row.encounter_id===id);
  const invoice=db.invoice.find(row=>row.encounter_id===id);
  const lines=invoice?db.invoice_line.filter(row=>row.invoice_id===invoice.invoice_id):[];
  const claim=invoice?db.claim.find(row=>row.invoice_id===invoice.invoice_id):null;
  const payments=invoice?db.payment.filter(row=>row.invoice_id===invoice.invoice_id):[];
  const running=sum(charges,'amount_paise');
  const paid=sum(payments,'amount_paise');
  return {encounter,patient,coverage,charges,preauth,invoice,lines,claim,payments,running,paid,balance:invoice?invoice.total_paise-paid:0};
}
function routeTone(route){return {SELF:'teal',PRIVATE:'blue',PMJAY:'orange',CGHS:'green',CORPORATE:'gray'}[route]||'gray';}
function stage(c){if(!c.invoice)return 'Running bill';if(c.balance===0)return 'Settled';return c.claim?'Claim in progress':'Final invoice';}
function pageHeading(kicker,title,description,button='') { return `<section class="page-heading"><div><div class="eyebrow">${esc(kicker)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${button}</section>`; }

function overview() {
  const cases=db.encounter.map(row=>record(row.encounter_id));
  const outstanding=db.invoice.reduce((total,invoice)=>total+invoice.total_paise-sum(db.payment.filter(p=>p.invoice_id===invoice.invoice_id),'amount_paise'),0);
  const metrics=[['Open encounters',db.encounter.length,'OPD and IPD examples'],['HIS charge events',db.charge.length,'Unique source event IDs'],['Final invoices',db.invoice.length,'One per encounter'],['Outstanding',money(outstanding),'Only receipts reduce this']];
  return pageHeading('OPERATIONS / 01','Billing overview','A small to mid-sized hospital billing workspace using invented cases.',`<button class="button button-primary" data-action="new-encounter">+ New encounter</button>`)+
    `<section class="metric-grid">${metrics.map(m=>`<div class="metric"><span class="metric-label">${m[0]}</span><strong>${m[1]}</strong><small>${m[2]}</small></div>`).join('')}</section>`+
    `<section class="overview-grid"><div class="panel panel-pad"><div class="panel-head"><h2>Encounter worklist</h2><small>${cases.length} training cases</small></div><div class="table-wrap"><table class="table"><thead><tr><th>Patient and encounter</th><th>Setting</th><th>Payer route</th><th>Stage</th><th class="right">Running total</th></tr></thead><tbody>${cases.map(c=>`<tr class="case-row" data-case="${esc(c.encounter.encounter_id)}"><td><span class="td-title">${esc(c.patient.display_label)}</span><small>${esc(c.encounter.encounter_id)}</small></td><td>${esc(c.encounter.setting)}</td><td>${badge(routeLabel(c.encounter.payer_route),routeTone(c.encounter.payer_route))}</td><td>${esc(stage(c))}</td><td class="right amount">${money(c.invoice?.total_paise??c.running)}</td></tr>`).join('')}</tbody></table></div></div><div class="panel"><div class="panel-pad"><div class="panel-head"><h2>From HIS event to receipt</h2></div><div class="flow"><div class="flow-step"><span class="flow-num">1</span><div><strong>Capture delivered care</strong><p>A unique HIS service event becomes one priced charge.</p></div></div><div class="flow-step"><span class="flow-num">2</span><div><strong>Finalise an itemised bill</strong><p>Charge prices are copied into locked invoice lines.</p></div></div><div class="flow-step"><span class="flow-num">3</span><div><strong>Record the payer outcome</strong><p>Preauthorisation and claim approval stay separate from cash received.</p></div></div><div class="flow-step"><span class="flow-num">4</span><div><strong>Reconcile receipts</strong><p>Patient or payer payments reduce the balance.</p></div></div></div></div><div class="panel-foot">All names, tariffs and payer decisions on this site are invented.</div></div></section>`+
    `<section class="panel panel-pad" style="margin-top:18px"><div class="panel-head"><h2>Recent activity</h2><button class="button button-outline button-small" data-view="audit">View full log</button></div>${activityRows(5)}</section>`;
}
function activityRows(limit=null) {
  const labels={ENCOUNTER_OPENED:'Encounter opened',HIS_CHARGE_RECEIVED:'HIS service event captured',DEMO_PREAUTH_SUBMITTED:'Preauthorisation requested',DEMO_PREAUTH_DECISION:'Preauthorisation decision recorded',INVOICE_FINALISED:'Final invoice created',DEMO_CLAIM_SUBMITTED:'Claim submitted',DEMO_CLAIM_DECISION:'Claim decision recorded',PAYMENT_RECORDED:'Receipt recorded',DEMO_RESET:'Synthetic cases reset'};
  const rows=[...db.audit_event].reverse();
  const chosen=limit?rows.slice(0,limit):rows;
  return chosen.length?`<div class="recent-list">${chosen.map(row=>`<div class="recent-row"><span>${esc(labels[row.action]||row.action)}</span><time>${date(row.occurred_at)}</time></div>`).join('')}</div>`:'<div class="empty">No activity yet.</div>';
}
function encounters() {
  const cases=db.encounter.map(row=>record(row.encounter_id));
  const c=record(selected)||cases[0];
  return pageHeading('OPERATIONS / 02','Encounters','Choose a case to follow its charges, bill, payer decision and receipts.',`<button class="button button-primary" data-action="new-encounter">+ New encounter</button>`)+
    `<section class="workspace-grid"><div class="panel worklist"><h2>Worklist</h2><p>${cases.length} encounters in the local database</p><div class="case-list">${cases.map(item=>`<button type="button" class="case-card ${item.encounter.encounter_id===selected?'active':''}" data-case="${esc(item.encounter.encounter_id)}"><span class="case-card-top"><strong>${esc(item.patient.display_label)}</strong>${badge(item.encounter.setting,'blue')}</span><span class="case-card-middle">${esc(item.encounter.encounter_id)}</span><span class="case-card-bottom"><span>${routeLabel(item.encounter.payer_route)}</span><span>${stage(item)}</span></span></button>`).join('')}</div></div>${casePanel(c)}</section>`;
}
function casePanel(c) {
  const total=c.invoice?.total_paise??c.running;
  const tabButtons=[['charges','Service events'],['invoice','Final invoice'],['payer','Payer workflow'],['receipts','Receipts']];
  const content={charges:chargesTab,invoice:invoiceTab,payer:payerTab,receipts:receiptsTab}[tab](c);
  return `<div class="panel case-detail"><div class="case-heading"><div><div class="eyebrow">SELECTED ENCOUNTER</div><h2>${esc(c.patient.display_label)}</h2><p>${esc(c.encounter.encounter_id)} · ${esc(c.encounter.setting)} · Opened ${date(c.encounter.opened_at)}</p></div><div>${badge(routeLabel(c.encounter.payer_route),routeTone(c.encounter.payer_route))}${badge(stage(c),c.balance===0&&c.invoice?'green':'gray')}</div></div><div class="case-metrics"><div><span>Charge events</span><strong>${c.charges.length}</strong></div><div><span>Bill amount</span><strong>${money(total)}</strong></div><div><span>Received</span><strong>${money(c.paid)}</strong></div><div><span>Balance due</span><strong>${money(c.balance)}</strong></div></div><div class="tabs" role="tablist">${tabButtons.map(([key,label])=>`<button type="button" class="tab ${tab===key?'active':''}" data-tab="${key}" role="tab" aria-selected="${tab===key}">${label}</button>`).join('')}</div><div class="tab-content">${content}</div></div>`;
}
function chargesTab(c) {
  const lines=c.charges.map(row=>{const s=find('service_catalog','service_code',row.service_code);return `<tr><td><span class="td-title">${esc(s?.description||row.service_code)}</span><small>${esc(row.source_event_id)}</small></td><td>${esc(s?.department||'')}</td><td>${row.quantity}</td><td class="right">${money(row.unit_price_paise)}</td><td class="right amount">${money(row.amount_paise)}</td></tr>`;}).join('');
  return `<div class="content-head"><div><h3>Delivered services</h3><p>Each event is priced once using the encounter's illustrative rate card.</p></div><div class="content-actions"><button class="button button-outline button-small" data-action="add-charge" ${c.invoice?'disabled':''}>+ Add HIS event</button><button class="button button-primary button-small" data-action="finalise" ${c.invoice||!c.charges.length?'disabled':''}>Finalise bill</button></div></div><div class="table-wrap"><table class="table"><thead><tr><th>Service / source event</th><th>Department</th><th>Qty</th><th class="right">Unit rate</th><th class="right">Amount</th></tr></thead><tbody>${lines||'<tr><td colspan="5">No service events yet. Add one to start the running bill.</td></tr>'}</tbody></table></div><div class="summary-band"><span>${c.invoice?'Final bill locked':'Running subtotal · tax on these demo services ₹0'}</span><strong>${money(c.running)}</strong></div>${c.invoice?'<div class="notice blue">The invoice preserves these charge prices. New events cannot change a final bill.</div>':''}`;
}
function invoiceTab(c) {
  if (!c.invoice) return `<div class="empty"><strong>No final invoice yet</strong>Open Service events and finalise the running bill after checking the delivered services.</div>`;
  return `<div class="content-head"><div><h3>Invoice #${c.invoice.invoice_id}</h3><p>Created ${date(c.invoice.created_at)}. This is a sample document for a teaching case.</p></div><button class="button button-outline button-small" data-action="print">Print this view</button></div><div class="invoice-paper"><div class="invoice-paper-head"><div><strong>Tiveri Hospital Demo</strong><small>Itemised final bill · invented information</small></div><div><strong>#${c.invoice.invoice_id}</strong><small>${esc(c.encounter.encounter_id)}</small></div></div><p style="font-size:12px;color:#627f8d;margin:16px 0">Patient: ${esc(c.patient.display_label)} &nbsp; | &nbsp; Payer: ${routeLabel(c.encounter.payer_route)}</p><table class="table"><thead><tr><th>Service</th><th>Qty</th><th class="right">Unit rate</th><th class="right">Amount</th></tr></thead><tbody>${c.lines.map(row=>`<tr><td>${esc(row.description)}<small>${esc(row.department)}</small></td><td>${row.quantity}</td><td class="right">${money(row.unit_price_paise)}</td><td class="right amount">${money(row.amount_paise)}</td></tr>`).join('')}</tbody></table><div class="invoice-total"><span>Total</span><span>${money(c.invoice.total_paise)}</span></div></div><p class="section-note">All shown services are marked exempt in this teaching catalogue. Pharmacy and other supplies need case-specific tax review before production use.</p>`;
}
function payerTab(c) {
  if (!c.coverage) return `<div class="empty"><strong>Self-pay encounter</strong>No claim is needed. Finalise the bill and record the patient's receipt.</div>`;
  const needs=Boolean(c.coverage.preauth_required);
  const canClaim=c.invoice&&!c.claim&&(!needs||c.preauth?.status==='APPROVED_DEMO');
  let authButtons='';
  if(needs&&!c.preauth)authButtons='<button class="button button-outline button-small" data-action="request-preauth">Request preauthorisation</button>';
  else if(needs&&c.preauth?.status==='SUBMITTED_DEMO')authButtons='<button class="button button-outline button-small" data-action="decide-preauth">Record demo decision</button>';
  let claimButtons='';
  if(canClaim)claimButtons='<button class="button button-primary button-small" data-action="submit-claim">Submit demo claim</button>';
  else if(c.claim?.status==='SUBMITTED_DEMO')claimButtons='<button class="button button-primary button-small" data-action="decide-claim">Record claim decision</button>';
  return `<div class="content-head"><div><h3>${routeLabel(c.encounter.payer_route)} workflow</h3><p>${esc(c.coverage.payer_label)} · ${esc(c.coverage.reference_code)}</p></div>${badge('Eligibility unverified','orange')}</div><div class="notice blue">The payer interactions here are local simulations. No insurer, CGHS or PM-JAY portal is contacted.</div><div class="payer-grid"><div class="payer-card"><h4>1 · Preauthorisation</h4><p>${needs?'This training route requires a recorded estimate and decision before the claim.':'Not required for this example route. Actual agreement or package rules must be checked.'}</p><span class="status">Status: <b>${needs?status(c.preauth?.status):'Not required in demo'}</b>${c.preauth?` · Requested ${money(c.preauth.requested_paise)}`:''}</span>${authButtons}</div><div class="payer-card"><h4>2 · Final claim</h4><p>Submit after the itemised bill. The decision records an approved amount, not cash received.</p><span class="status">Status: <b>${status(c.claim?.status)}</b>${c.claim?.approved_paise!=null?` · Approved ${money(c.claim.approved_paise)}`:''}</span>${claimButtons}</div></div><div class="notice green">Payer approval leaves the outstanding balance at ${money(c.balance)}. Record a receipt after money arrives.</div>`;
}
function receiptsTab(c) {
  if(!c.invoice)return `<div class="empty"><strong>No receipts yet</strong>Finalise the bill before recording money received.</div>`;
  return `<div class="content-head"><div><h3>Payment ledger</h3><p>Payments are recorded separately from authorisations and claim decisions.</p></div><button class="button button-orange button-small" data-action="record-payment" ${c.balance===0?'disabled':''}>+ Record receipt</button></div><div class="receipt-summary"><div><small>Invoice</small><strong>${money(c.invoice.total_paise)}</strong></div><div><small>Received</small><strong>${money(c.paid)}</strong></div><div><small>Outstanding</small><strong>${money(c.balance)}</strong></div></div><div class="table-wrap"><table class="table"><thead><tr><th>Receipt</th><th>From</th><th>Method / reference</th><th>Date</th><th class="right">Amount</th></tr></thead><tbody>${c.payments.length?c.payments.map(row=>`<tr><td>#${row.payment_id}</td><td>${esc(row.payer_kind)}</td><td>${esc(row.method)}</td><td>${date(row.recorded_at)}</td><td class="right amount">${money(row.amount_paise)}</td></tr>`).join(''):'<tr><td colspan="5">No money has been received. Approval does not change the balance.</td></tr>'}</tbody></table></div>`;
}
function payerDesk() {
  const cases=db.encounter.filter(row=>row.payer_route!=='SELF').map(row=>record(row.encounter_id));
  return pageHeading('OPERATIONS / 03','Payer desk','Track example preauthorisations, final claims and cash received by payer route.')+
    `<section class="panel panel-pad"><div class="panel-head"><h2>Covered encounters</h2><small>Decisions are simulated</small></div><div class="table-wrap"><table class="table"><thead><tr><th>Case</th><th>Route</th><th>Preauth</th><th>Claim</th><th class="right">Approved</th><th class="right">Balance</th></tr></thead><tbody>${cases.map(c=>`<tr class="case-row" data-case="${esc(c.encounter.encounter_id)}" data-open-tab="payer"><td><span class="td-title">${esc(c.patient.display_label)}</span><small>${esc(c.encounter.encounter_id)}</small></td><td>${badge(routeLabel(c.encounter.payer_route),routeTone(c.encounter.payer_route))}</td><td>${c.coverage.preauth_required?status(c.preauth?.status):'Not required in demo'}</td><td>${status(c.claim?.status)}</td><td class="right amount">${money(c.claim?.approved_paise??0)}</td><td class="right amount">${money(c.balance)}</td></tr>`).join('')}</tbody></table></div></section><div class="callout" style="margin-top:18px"><span class="flow-num">i</span><div><b>India-specific routes in the design:</b> private insurance, PM-JAY, CGHS and corporate credit use different rate or document rules. This prototype demonstrates their status flow with invented data, and it does not submit to any external payer.</div></div>`;
}
function tariff() {
  const routes=['PRIVATE','PMJAY','CGHS','CORPORATE'];
  const price=(code,route,fallback)=>db.payer_rate.find(r=>r.service_code===code&&r.payer_kind===route)?.unit_price_paise??fallback;
  return pageHeading('CONFIGURATION / 04','Tariff master','The demonstration catalogue stores a base price and optional payer rates. Rates shown here are invented.')+
    `<section class="panel panel-pad"><div class="panel-head"><h2>Service catalogue and payer rates</h2><small>${db.service_catalog.length} items</small></div><div class="table-wrap"><table class="table matrix"><thead><tr><th>Code / service</th><th>Department</th><th>Self pay</th><th>Private</th><th>PM-JAY</th><th>CGHS</th><th>Corporate</th></tr></thead><tbody>${db.service_catalog.map(row=>`<tr><td><span class="td-title">${esc(row.service_code)}</span><small>${esc(row.description)}${row.active?'':' · disabled pending tax review'}</small></td><td>${esc(row.department)}</td><td>${money(row.list_price_paise)}</td>${routes.map(route=>`<td>${money(price(row.service_code,route,row.list_price_paise))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="section-note">A selected price is copied into the charge and invoice line. The PM-JAY placeholder is an invented example, not an official HBP tariff. Real scheme, CGHS and insurer rates must be configured from current contracts.</p></section>`;
}
function auditView() {
  return pageHeading('TRACEABILITY / 05','Activity log','A local audit trail shows when a service event, bill, payer decision or receipt was recorded.')+
    `<section class="panel panel-pad"><div class="panel-head"><h2>Recent database actions</h2><small>${db.audit_event.length} entries</small></div>${activityRows()}</section>`;
}
function render() {
  if(!db)return;
  document.querySelectorAll('.nav-item').forEach(node=>node.classList.toggle('active',node.dataset.view===view));
  $('app').innerHTML={overview,encounters,payer:payerDesk,tariff,audit:auditView}[view]();
}

function openModal({eyebrow,title,description,fields=[],submit='Save',action}) {
  modalAction=action;
  $('modal-eyebrow').textContent=eyebrow;
  $('modal-title').textContent=title;
  $('modal-description').textContent=description;
  $('modal-submit').textContent=submit;
  $('modal-fields').innerHTML=fields.map(field=>`<div class="modal-field"><label for="field-${esc(field.name)}">${esc(field.label)}</label>${field.options?`<select id="field-${esc(field.name)}" name="${esc(field.name)}">${field.options.map(option=>`<option value="${esc(option.value)}" ${option.value===field.value?'selected':''}>${esc(option.label)}</option>`).join('')}</select>`:`<input id="field-${esc(field.name)}" name="${esc(field.name)}" type="${field.type||'text'}" value="${esc(field.value??'')}" ${field.type==='number'?'min="0" step="0.01"':''} ${field.required===false?'':'required'}>`}${field.help?`<small>${esc(field.help)}</small>`:''}</div>`).join('');
  $('action-dialog').showModal();
}
function rupees(value) {
  const number=Number(value);
  if(!Number.isFinite(number)||number<0||Math.abs(number*100-Math.round(number*100))>0.0001)throw new Error('Enter a non-negative amount with up to two decimal places');
  return Math.round(number*100);
}
function newEncounter() {
  openModal({eyebrow:'NEW TRAINING CASE',title:'Open an encounter',description:'Use an invented patient label. The payer route is fixed for this encounter.',fields:[
    {name:'display_label',label:'Demo patient label',value:'Demo Patient F'},
    {name:'setting',label:'Care setting',options:[['OPD','OPD'],['IPD','IPD'],['EMERGENCY','Emergency'],['DAY_CARE','Day care']].map(([value,label])=>({value,label}))},
    {name:'payer_route',label:'Payer route',options:[['SELF','Self pay'],['PRIVATE','Private insurance'],['PMJAY','PM-JAY'],['CGHS','CGHS'],['CORPORATE','Corporate credit']].map(([value,label])=>({value,label}))},
    {name:'payer_label',label:'Payer name (for covered case)',value:'Demo payer',required:false,help:'Not used for a self-pay case.'}
  ],submit:'Create encounter',action:async values=>{const result=await api('/api/encounters','POST',values);selected=result.encounter_id;view='encounters';tab='charges';return result;}});
}
function addCharge() {
  const c=record(selected);
  const options=db.service_catalog.filter(s=>s.active&&(s.service_code!=='PMJAY-PKG'||c.encounter.payer_route==='PMJAY')).map(s=>({value:s.service_code,label:`${s.description} (${money(db.payer_rate.find(r=>r.service_code===s.service_code&&r.payer_kind===c.encounter.payer_route)?.unit_price_paise??s.list_price_paise)})`}));
  openModal({eyebrow:'HIS EVENT',title:'Add a delivered service',description:'The source event ID prevents a retry from creating a second charge.',fields:[{name:'service_code',label:'Service',options},{name:'quantity',label:'Quantity',type:'number',value:1}],submit:'Add service event',action:values=>{const quantity=Number(values.quantity);if(!Number.isInteger(quantity)||quantity<1||quantity>100)throw new Error('Quantity must be 1 to 100');return api('/api/his/events','POST',{source_event_id:'UI-'+Date.now()+'-'+Math.random().toString(36).slice(2,8),encounter_id:selected,service_code:values.service_code,quantity});}});
}
function preauthRequest() {
  const c=record(selected);
  openModal({eyebrow:'SIMULATED PAYER STEP',title:'Request preauthorisation',description:'Use an invented estimate. This is not an eligibility check or a real payer request.',fields:[{name:'amount',label:'Requested amount (₹)',type:'number',value:Math.max(1000,Math.ceil(c.running/100))}],submit:'Record request',action:values=>api('/api/preauth','POST',{encounter_id:selected,coverage_id:c.coverage.coverage_id,requested_paise:rupees(values.amount)})});
}
function preauthDecision() {
  const c=record(selected);
  openModal({eyebrow:'SIMULATED PAYER STEP',title:'Record preauth decision',description:'Authorisation is an approval limit, not a payment.',fields:[{name:'amount',label:'Approved amount (₹)',type:'number',value:c.preauth.requested_paise/100}],submit:'Record decision',action:values=>api(`/api/preauth/${c.preauth.preauth_id}/decision`,'POST',{approved_paise:rupees(values.amount)})});
}
function claimDecision() {
  const c=record(selected);
  openModal({eyebrow:'SIMULATED PAYER STEP',title:'Record claim decision',description:'The balance changes only when a receipt is entered.',fields:[{name:'amount',label:'Approved amount (₹)',type:'number',value:Math.min(c.claim.requested_paise,c.preauth?.approved_paise??c.claim.requested_paise)/100}],submit:'Record decision',action:values=>api(`/api/claims/${c.claim.claim_id}/decision`,'POST',{approved_paise:rupees(values.amount)})});
}
function receipt() {
  const c=record(selected);
  const options=c.encounter.payer_route==='PMJAY'?[]:[{value:'PATIENT',label:'Patient'}];
  if(c.coverage)options.push({value:payerReceipt(c.encounter.payer_route),label:routeLabel(c.encounter.payer_route)+' payer'});
  openModal({eyebrow:'RECONCILIATION',title:'Record money received',description:'The server checks the outstanding balance and any payer approval limit.',fields:[{name:'payer_kind',label:'Received from',options,value:c.encounter.payer_route==='PMJAY'?payerReceipt(c.encounter.payer_route):'PATIENT'},{name:'amount',label:'Amount (₹)',type:'number',value:c.balance/100},{name:'method',label:'Method or settlement reference',value:'Demo UPI / settlement'}],submit:'Record receipt',action:values=>api('/api/payments','POST',{invoice_id:c.invoice.invoice_id,payer_kind:values.payer_kind,amount_paise:rupees(values.amount),method:values.method})});
}

document.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-view]');
  if(nav){view=nav.dataset.view;render();window.scrollTo(0,0);return;}
  const caseNode=event.target.closest('[data-case]');
  if(caseNode){selected=caseNode.dataset.case;view='encounters';tab=caseNode.dataset.openTab||'charges';render();window.scrollTo(0,0);return;}
  const tabNode=event.target.closest('[data-tab]');
  if(tabNode){tab=tabNode.dataset.tab;render();return;}
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(!action)return;
  if(action==='new-encounter')newEncounter();
  if(action==='add-charge')addCharge();
  if(action==='finalise')openModal({eyebrow:'FINAL BILL',title:'Finalise this invoice',description:'The charge list will be locked for this encounter. Check it before continuing.',submit:'Finalise invoice',action:()=>api('/api/invoices','POST',{encounter_id:selected})});
  if(action==='request-preauth')preauthRequest();
  if(action==='decide-preauth')preauthDecision();
  if(action==='submit-claim'){const c=record(selected);await perform(()=>api('/api/claims','POST',{invoice_id:c.invoice.invoice_id,coverage_id:c.coverage.coverage_id}),'Demo claim submitted.');}
  if(action==='decide-claim')claimDecision();
  if(action==='record-payment')receipt();
  if(action==='reset')openModal({eyebrow:'LOCAL WORKSPACE',title:'Reset synthetic cases',description:'This clears the local demo changes and reloads the five invented cases.',submit:'Reset demo',action:async()=>{const result=await api('/api/demo/reset','POST',{});selected='E-IPD-02';view='overview';tab='charges';return result;}});
  if(action==='print')window.print();
});
$('modal-form').addEventListener('submit',async event=>{
  event.preventDefault();
  if(!modalAction)return;
  try{const values=Object.fromEntries(new FormData(event.currentTarget));await modalAction(values);$('action-dialog').close();modalAction=null;await refresh();toast('Saved in the local billing database.');}
  catch(error){toast(error.message,true);}
});
$('modal-close').addEventListener('click',()=>{$('action-dialog').close();modalAction=null;});
$('modal-cancel').addEventListener('click',()=>{$('action-dialog').close();modalAction=null;});
refresh().catch(error=>toast(error.message,true));

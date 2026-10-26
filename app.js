const $ = s => document.querySelector(s);
const money = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
const pretty = s => (s||'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
let activeTask = null;
async function api(path, body) {
  const r = await fetch(path, {method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const d = await r.json(); if(!r.ok) throw new Error(d.error||`Request failed (${r.status})`); return d;
}
function toast(msg){const t=$('#toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}
function renderState(s){
  const open=s.invoices.filter(i=>i.status!=='paid'), overdue=open.filter(i=>i.overdue_days>0);
  $('#statOpen').textContent=open.length; $('#statOverdue').textContent=overdue.length;
  $('#statAmount').textContent=money(open.reduce((a,i)=>a+i.amount,0));
  $('#statPending').textContent=s.drafts.filter(d=>d.status==='pending').length;
  $('#invoiceNavCount').textContent=s.invoices.length;
  $('#invoiceRows').innerHTML=s.invoices.map(i=>`<tr><td>${esc(i.id)}</td><td class="vendor">${esc(i.vendor)}</td><td>${i.overdue_days?`${i.overdue_days} days ago`:i.due_date}</td><td class="amount">${money(i.amount)}</td><td><span class="status ${i.status==='paid'?'paid':i.overdue_days?'overdue':'upcoming'}">${i.status==='paid'?'Paid':i.overdue_days?'Overdue':'Upcoming'}</span></td></tr>`).join('');
  $('#taskCount').textContent=s.tasks.length;
  $('#taskList').innerHTML=s.tasks.length?s.tasks.map(t=>`<div class="task-item" data-id="${t.id}"><p>${esc(t.request)}</p><div class="task-meta"><span>${new Date(t.created_at).toLocaleString()}</span><span class="task-status ${t.status}">${pretty(t.status)}</span></div></div>`).join(''):'<div class="empty">No agent runs yet.<br>Start with an invoice follow-up task.</div>';
  document.querySelectorAll('.task-item').forEach(el=>el.onclick=()=>loadTask(el.dataset.id));
}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function renderTask(t){activeTask=t;const box=$('#result');box.classList.remove('hidden');const plans=t.plan.map((p,i)=>`<div class="plan-step"><b>${i+1}. ${esc(pretty(p.step))}</b> — ${esc(p.description)}</div>`).join('');const events=t.events.slice().reverse().map(e=>`<div class="timeline-event"><b>${new Date(e.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</b> · ${esc(e.message)}${e.data.tool?` <span style="color:#9a85dc">[${esc(e.data.tool)}]</span>`:''}</div>`).join('');const drafts=t.drafts.map(d=>`<div class="draft"><div class="draft-head"><strong>${esc(d.invoice_id)} · ${esc(d.vendor)}</strong><span class="task-status ${d.status==='approved'?'completed':d.status==='rejected'?'failed':''}">${pretty(d.status)}</span></div><div class="draft-meta">${d.overdue_days} days overdue · ${money(d.amount)} · To ${esc(d.recipient)} · Priority ${esc(d.priority)}</div><div class="draft-body"><b>${esc(d.subject)}</b><br>${esc(d.body)}</div>${d.status==='pending'?`<div class="draft-actions"><button class="approve" data-draft="${d.id}" data-decision="approve">Approve simulated send</button><button class="reject" data-draft="${d.id}" data-decision="reject">Reject</button></div>`:''}</div>`).join('')||'<div class="empty">No drafts saved.</div>';const out=t.outbox.map(o=>`<div class="outbox">✓ Simulated outbox · ${esc(o.invoice_id)} · ${esc(o.recipient)} · ${new Date(o.created_at).toLocaleString()}</div>`).join('');box.innerHTML=`<div class="section-heading"><div><div class="eyebrow">AGENT RUN · ${esc(t.mode.toUpperCase())}</div><h2>${esc(pretty(t.status))}</h2></div><span class="task-status ${t.status==='completed'?'completed':t.status==='failed'?'failed':''}">${pretty(t.status)}</span></div><div class="result-meta">${esc(t.request)} · Run ${t.id.slice(0,8)}</div><div class="result-grid"><div class="subpanel"><h3>Execution plan</h3>${plans}<div class="verified"><b>Independent verification</b><br>Re-read SQLite: ${t.verification.draft_count} drafts · ${t.verification.pending} pending · ${t.verification.approved} approved · ${t.verification.rejected} rejected · ${t.verification.outbox_count} in simulated outbox<br>Checked ${new Date(t.verification.checked_at).toLocaleTimeString()}</div>${out}</div><div class="subpanel"><h3>Reminder drafts and approvals</h3>${drafts}</div><div class="subpanel" style="grid-column:1/-1"><h3>Execution timeline and tool evidence</h3>${events}</div></div>`;
  const verifyBox=box.querySelector('.verified');
  if(verifyBox) verifyBox.innerHTML += `<br>Eligible invoice set ${t.verification.eligible_match?'matches':'MISMATCH'} (${t.verification.draft_count}/${t.verification.expected_eligible_count}) · Approved drafts/outbox ${t.verification.approved_outbox_match?'match':'MISMATCH'}`;
  box.querySelectorAll('[data-decision]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const res=await api(`/api/drafts/${b.dataset.draft}/decision`,{decision:b.dataset.decision});renderTask(res);renderState(await api('/api/state'));toast(b.dataset.decision==='approve'?'Approved and queued in simulated outbox':'Rejected; protected action was not run')}catch(e){toast(e.message);b.disabled=false}});
  box.scrollIntoView({behavior:'smooth',block:'start'});
}
async function loadTask(id){try{renderTask(await api(`/api/tasks/${id}`))}catch(e){toast(e.message)}}
async function refresh(){renderState(await api('/api/state'))}
$('#taskForm').addEventListener('submit',async e=>{e.preventDefault();const request=$('#request').value.trim()||$('#request').placeholder;const btn=$('#runBtn');btn.disabled=true;btn.querySelector('span').textContent='Working…';try{const task=await api('/api/tasks',{request});renderTask(task);await refresh();toast('Draft preparation complete; approval is pending')}catch(err){toast(err.message)}finally{btn.disabled=false;btn.querySelector('span').textContent='Run task'}});
$('#refreshBtn').onclick=()=>refresh().catch(e=>toast(e.message));
refresh().catch(e=>toast('Cannot connect to local agent: '+e.message));

$('#retryBtn').onclick=async()=>{try{await api('/api/failure-injection',{});toast('Armed: next draft write fails once, then retries')}catch(e){toast(e.message)}};

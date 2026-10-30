let token = null; // Session memory only; refresh requires sign-in.
let role = null;
let pendingSale = null;
const byId = id => document.getElementById(id);
function message(text, error=false) {
  byId('message').textContent = text;
  byId('message').className = error ? 'error' : 'success';
}
async function api(path, method='GET', body) {
  const response = await fetch('/api/' + path, {
    method, headers: {'Content-Type':'application/json', ...(token ? {Authorization:'Bearer ' + token} : {})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function render(data, target) {
  target.replaceChildren();
  if (!Array.isArray(data)) {
    for (const [name, value] of Object.entries(data)) {
      const h = document.createElement('h4'); h.textContent = name.replaceAll('_',' '); target.append(h);
      const section = document.createElement('div'); target.append(section);
      if (Array.isArray(value)) render(value, section);
      else {const p=document.createElement('pre');p.textContent=JSON.stringify(value,null,2);section.append(p);}
    }
    return;
  }
  if (!data.length) { target.textContent = 'No records yet.'; return; }
  const table=document.createElement('table'), head=document.createElement('thead'), tr=document.createElement('tr');
  const columns=[...new Set(data.flatMap(row=>Object.keys(row)))];
  for(const key of columns){const th=document.createElement('th');th.textContent=key.replaceAll('_',' ');tr.append(th);}
  head.append(tr);table.append(head);
  const body=document.createElement('tbody');
  for(const row of data){const tr=document.createElement('tr');for(const key of columns){const td=document.createElement('td');td.textContent=typeof row[key]==='object'?JSON.stringify(row[key]):String(row[key]??'');tr.append(td);}body.append(tr);}
  table.append(body);target.append(table);
}
async function loadView(path) {
  try { render(await api(path), byId('results'));byId('view-title').textContent=path.replace('analytics/','').replaceAll('_',' ');
    document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===path));
  } catch(error){message(error.message,true);}
}
byId('login').addEventListener('submit', async event=>{
  event.preventDefault();
  try {const result=await api('auth/login','POST',Object.fromEntries(new FormData(event.target)));
    token=result.access_token;role=result.role;byId('workspace').hidden=false;byId('login-card').hidden=true;
    byId('welcome').textContent=role[0].toUpperCase()+role.slice(1)+' workspace';
    document.querySelectorAll('[data-manager]').forEach(x=>x.hidden=role!=='manager');
    document.querySelectorAll('[data-staff]').forEach(x=>x.hidden=role==='customer');
    byId('staff-forms').hidden=role==='customer';byId('restock-card').hidden=role!=='manager';byId('review-card').hidden=role!=='customer';
    message('Signed in.');await loadView('menu');
  } catch(error){message(error.message,true);}
});
byId('logout').onclick=()=>location.reload();
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>loadView(b.dataset.view));
byId('checkout').addEventListener('submit',async event=>{
  event.preventDefault();const form=Object.fromEntries(new FormData(event.target));
  const cart={branch_id:Number(form.branch_id),customer_id:Number(form.customer_id),redeem_points:Number(form.redeem_points),lines:[{menu_item_id:Number(form.menu_item_id),quantity:Number(form.quantity)}]};
  // Keep the same request key when retrying an unchanged sale after a network error.
  const signature=JSON.stringify(cart);
  if(!pendingSale || pendingSale.signature!==signature) pendingSale={signature,key:crypto.randomUUID()};
  const button=event.target.querySelector('button');button.disabled=true;
  try {const result=await api('orders','POST',{...cart,request_key:pendingSale.key});pendingSale=null;message('Sale completed: '+JSON.stringify(result));await loadView('orders');}
  catch(error){message(error.message,true);}finally{button.disabled=false;}
});
byId('restock').addEventListener('submit',async event=>{
  event.preventDefault();const f=Object.fromEntries(new FormData(event.target));
  try {const result=await api('stock/receipts','POST',{branch_id:Number(f.branch_id),ingredient_id:Number(f.ingredient_id),quantity:f.quantity,note:'Received through starter UI'});message('Receipt recorded: '+JSON.stringify(result));await loadView('stock');}
  catch(error){message(error.message,true);}
});
byId('review').addEventListener('submit',async event=>{
  event.preventDefault();const f=Object.fromEntries(new FormData(event.target));
  try{await api('reviews','POST',{order_id:Number(f.order_id),rating:Number(f.rating),text:f.text,tags:f.tags.split(',').map(t=>t.trim()).filter(Boolean)});message('Review submitted.');await loadView('reviews');}
  catch(error){message(error.message,true);}
});
api('health').then(s=>{byId('health').textContent=`SQL: ${s.sql} (${s.sql_dialect}) · MongoDB: ${s.mongo}`;}).catch(()=>{byId('health').textContent='Service unavailable';});

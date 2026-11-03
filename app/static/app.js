let token = null; // Session memory only; refresh requires sign-in.
let role = null;
let loggedInCustomerId = null;
let pendingSale = null;

// ordering
const ordering = {branches: [], dishes: [], customers: []};
const orderCart = new Map();

// menu, ingredients
let menuRecords = [];
let ingredientRecords = [];
let recipeRecords = [];
let selectedMenuId = null;
let selectedIngredientId = null;

const byId = id => document.getElementById(id);
const money = amount => '$' + Number(amount).toFixed(2);
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
function setOptions(select, records, label, placeholder) {
  select.replaceChildren();
  const prompt = document.createElement('option');
  prompt.value = '';
  prompt.textContent = placeholder;
  prompt.disabled = true;
  prompt.selected = true;
  select.append(prompt);
  for (const record of records) {
    const option = document.createElement('option');
    option.value = record.id;
    option.textContent = label(record);
    select.append(option);
  }
}
function setSelectedOption(select, value) {
  if (value !== null && [...select.options].some(option => option.value === String(value))) {
    select.value = String(value);
  }
}
function selectedCustomer() {
  return ordering.customers.find(customer => customer.id === Number(byId('order-customer').value));
}
function cartSubtotal() {
  const cents = [...orderCart].reduce((sum, [id, quantity]) => {
    const dish = ordering.dishes.find(item => item.id === id);
    return sum + (dish ? Math.round(Number(dish.price) * 100) * quantity : 0);
  }, 0);
  return cents / 100;
}
function redemptionCap(subtotal, customer) {
  if (!customer) return 0;
  return Math.min(Math.floor(customer.points / 100) * 100,
    Math.floor(Math.round(subtotal * 100) / 100) * 100);
}
function updateOrderSummary() {
  const customer = selectedCustomer();
  const subtotal = cartSubtotal();
  const cap = redemptionCap(subtotal, customer);
  byId('available-points').textContent = customer ? String(customer.points) : 'Select a customer';
  byId('redeem-points').max = String(cap);
  const requested = Number(byId('redeem-points').value) || 0;
  const discount = Math.min(requested, cap) / 100;
  byId('redemption-limit').textContent = customer
    ? `You can redeem up to ${cap} points for this order.`
    : 'Select a customer to see available points.';
  byId('order-subtotal').textContent = money(subtotal);
  byId('order-discount').textContent = '−' + money(discount);
  byId('order-total').textContent = money(Math.max(0, subtotal - discount));
}
function renderOrderCart() {
  const target = byId('order-cart');
  target.replaceChildren();
  if (!orderCart.size) {
    target.textContent = 'Add a dish to start your cart.';
    target.classList.add('muted');
    updateOrderSummary();
    return;
  }
  target.classList.remove('muted');
  for (const [id, quantity] of orderCart) {
    const dish = ordering.dishes.find(item => item.id === id);
    if (!dish) continue;
    const row = document.createElement('div');
    row.className = 'cart-row';
    const description = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = dish.name;
    const price = document.createElement('span');
    price.className = 'muted';
    price.textContent = ` ${money(dish.price)} each · ${money(Number(dish.price) * quantity)}`;
    description.append(name, price);
    const controls = document.createElement('div');
    controls.className = 'quantity-controls';
    const decrement = document.createElement('button');
    decrement.type = 'button';
    decrement.className = 'secondary';
    decrement.dataset.cartAction = 'decrease';
    decrement.dataset.dishId = String(id);
    decrement.setAttribute('aria-label', `Decrease ${dish.name} quantity`);
    decrement.textContent = '−';
    const count = document.createElement('span');
    count.textContent = String(quantity);
    const increment = document.createElement('button');
    increment.type = 'button';
    increment.className = 'secondary';
    increment.dataset.cartAction = 'increase';
    increment.dataset.dishId = String(id);
    increment.setAttribute('aria-label', `Increase ${dish.name} quantity`);
    increment.textContent = '+';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove-item';
    remove.dataset.cartAction = 'remove';
    remove.dataset.dishId = String(id);
    remove.textContent = 'Remove';
    controls.append(decrement, count, increment, remove);
    row.append(description, controls);
    target.append(row);
  }
  updateOrderSummary();
}
async function loadOrderingData() {
  const previousBranch = byId('order-branch').value;
  const previousCustomer = byId('order-customer').value;
  const [branches, dishes, customers] = await Promise.all([
    api('branches'), api('menu'), api('customers')
  ]);
  ordering.branches = branches;
  ordering.dishes = dishes.filter(dish => dish.active);
  ordering.customers = customers.filter(customer => customer.active &&
    (role !== 'customer' || customer.id === loggedInCustomerId));
  setOptions(byId('order-branch'), ordering.branches, branch => branch.name, 'Choose a branch');
  setOptions(byId('order-customer'), ordering.customers,
    customer => `${customer.name} · ${customer.points} points`,
    role === 'customer' ? 'Your customer account' : 'Choose a customer');
  setOptions(byId('dish-selection'), ordering.dishes,
    dish => `${dish.name} · ${money(dish.price)}`, 'Choose a dish');
  if (ordering.branches.some(branch => branch.id === Number(previousBranch))) byId('order-branch').value = previousBranch;
  if (role === 'customer' && ordering.customers.some(customer => customer.id === loggedInCustomerId)) {
    byId('order-customer').value = String(loggedInCustomerId);
  } else if (ordering.customers.some(customer => customer.id === Number(previousCustomer))) {
    byId('order-customer').value = previousCustomer;
  }
  byId('order-customer').disabled = role === 'customer';
  byId('order-customer-label').firstChild.textContent = role === 'customer' ? 'Your account' : 'Customer';
  renderOrderCart();
}
function menuLabel(item) {
  return `${item.name} · ${money(item.price)}${item.active ? '' : ' · inactive'}`;
}
function ingredientLabel(ingredient) {
  return `${ingredient.name} (${ingredient.unit})`;
}
function renderMenuOptions(selectedId = selectedMenuId) {
  setOptions(byId('menu-record'), menuRecords, menuLabel, 'Create a new dish');
  setSelectedOption(byId('menu-record'), selectedId);
}
function renderIngredientOptions(selectedId = selectedIngredientId) {
  setOptions(byId('ingredient-record'), ingredientRecords, ingredientLabel, 'Create a new ingredient');
  setSelectedOption(byId('ingredient-record'), selectedId);
}
function appendRecipeLine(component = {}) {
  const row = document.createElement('div');
  row.className = 'recipe-line';
  const ingredientSelect = document.createElement('select');
  ingredientSelect.className = 'recipe-ingredient';
  ingredientSelect.setAttribute('aria-label', 'Recipe ingredient');
  setOptions(ingredientSelect, ingredientRecords, ingredientLabel, 'Choose ingredient');
  setSelectedOption(ingredientSelect, component.ingredient_id);
  const quantity = document.createElement('input');
  quantity.className = 'recipe-quantity';
  quantity.type = 'number';
  quantity.min = '0.001';
  quantity.step = '0.001';
  quantity.max = '99999999999.999';
  quantity.value = component.quantity ?? '';
  quantity.required = true;
  quantity.setAttribute('aria-label', 'Ingredient quantity');
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'danger';
  remove.textContent = 'Remove';
  remove.addEventListener('click', () => row.remove());
  row.append(ingredientSelect, quantity, remove);
  byId('recipe-lines').append(row);
}
function renderRecipeForMenu(menuId) {
  const lines = recipeRecords.filter(recipe => recipe.menu_item_id === Number(menuId));
  byId('recipe-lines').replaceChildren();
  for (const component of lines) appendRecipeLine(component);
  byId('recipe-fieldset').disabled = !menuId;
  byId('recipe-help').textContent = menuId
    ? 'Add one or more ingredients, then save to replace the full recipe. Ingredients must be unique and quantities greater than zero, with at most three decimal places.'
    : 'Save a new dish or select an existing dish to edit its recipe.';
}
async function loadMenuManagement(selectMenuId = selectedMenuId, selectIngredientId = selectedIngredientId) {
  const [menus, ingredients, recipes] = await Promise.all([
    api('menu'), api('ingredients'), api('recipes')
  ]);
  menuRecords = menus;
  ingredientRecords = ingredients;
  recipeRecords = recipes;
  selectedMenuId = menuRecords.some(item => item.id === Number(selectMenuId)) ? Number(selectMenuId) : null;
  selectedIngredientId = ingredientRecords.some(item => item.id === Number(selectIngredientId))
    ? Number(selectIngredientId) : null;
  renderMenuOptions();
  renderIngredientOptions();
  const selectedMenu = menuRecords.find(item => item.id === selectedMenuId);
  byId('dish-name').value = selectedMenu?.name ?? '';
  byId('dish-price').value = selectedMenu?.price ?? '';
  byId('delete-dish').disabled = !selectedMenu;
  renderRecipeForMenu(selectedMenuId);
  const selectedIngredient = ingredientRecords.find(item => item.id === selectedIngredientId);
  byId('ingredient-name').value = selectedIngredient?.name ?? '';
  byId('ingredient-unit').value = selectedIngredient?.unit ?? 'g';
  byId('delete-ingredient').disabled = !selectedIngredient;
}
function recipePayload() {
  const rows = [...byId('recipe-lines').querySelectorAll('.recipe-line')];
  if (!rows.length) throw new Error('A recipe must contain at least one ingredient.');
  const seen = new Set();
  const ingredients = rows.map(row => {
    const ingredientId = Number(row.querySelector('.recipe-ingredient').value);
    const quantityInput = row.querySelector('.recipe-quantity');
    const quantityText = quantityInput.value.trim();
    const quantity = Number(quantityText);
    if (!ingredientId) throw new Error('Choose an ingredient for every recipe row.');
    if (seen.has(ingredientId)) throw new Error('An ingredient may only appear once in a recipe.');
    seen.add(ingredientId);
    if (!quantityInput.validity.valid || !Number.isFinite(quantity) || quantity <= 0 ||
        !/^\d+(\.\d{1,3})?$/.test(quantityText)) {
      throw new Error('Each ingredient quantity must be greater than zero with at most three decimal places.');
    }
    return {ingredient_id: ingredientId, quantity: quantityText};
  });
  return {ingredients};
}
function showReceipt(result, cart, branch, customer) {
  byId('receipt-heading').textContent =
    `Order #${result.order_id} · ${branch?.name ?? 'Branch'} · ${customer?.name ?? 'Customer'}`;
  const items = byId('receipt-items');
  items.replaceChildren();
  for (const [id, quantity] of cart) {
    const dish = ordering.dishes.find(item => item.id === id);
    const line = document.createElement('li');
    line.textContent = `${dish?.name ?? `Dish #${id}`} × ${quantity}`;
    items.append(line);
  }
  byId('receipt-subtotal').textContent = money(result.subtotal);
  byId('receipt-discount').textContent = '−' + money(result.discount);
  byId('receipt-total').textContent = money(result.total);
  byId('order-receipt').hidden = false;
}
async function loadView(path) {
  const apiPath=path==='menu-management'?'menu':path;
  try { render(await api(apiPath), byId('results'));byId('view-title').textContent=path==='menu-management'?'menu management':path.replace('analytics/','').replaceAll('_',' ');
    document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===path));
  } catch(error){message(error.message,true);}
}
byId('login').addEventListener('submit', async event=>{
  event.preventDefault();
  try {const result=await api('auth/login','POST',Object.fromEntries(new FormData(event.target)));
    token=result.access_token;role=result.role;loggedInCustomerId=result.customer_id;
    byId('workspace').hidden=false;byId('login-card').hidden=true;
    byId('welcome').textContent=role[0].toUpperCase()+role.slice(1)+' workspace';
    document.querySelectorAll('[data-manager]').forEach(x=>x.hidden=role!=='manager');
    document.querySelectorAll('[data-staff]').forEach(x=>x.hidden=role==='customer');
    byId('staff-forms').hidden=role==='customer';
    byId('legacy-checkout-card').hidden=role==='manager';
    byId('restock-card').hidden=role!=='manager';
    byId('review-card').hidden=role!=='customer';
    byId('order-card').hidden=role!=='customer';
    message('Signed in.');
    
    if (role==='manager'||role==='customer') {
      try { await loadOrderingData(); }
      catch(error) { message('Signed in, but ordering options could not be loaded: '+error.message,true); }
    }
    if (role==='manager') {
      try { await loadMenuManagement(); }
      catch(error) { message('Signed in, but menu management data could not be loaded: '+error.message,true); }
    }
    await loadView('menu');
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
byId('menu-record').addEventListener('change',()=>{
  selectedMenuId=Number(byId('menu-record').value);
  const item=menuRecords.find(record=>record.id===selectedMenuId);
  byId('dish-name').value=item?.name??'';
  byId('dish-price').value=item?.price??'';
  byId('delete-dish').disabled=!item;
  renderRecipeForMenu(selectedMenuId);
});
byId('new-dish').addEventListener('click',()=>{
  selectedMenuId=null;
  byId('menu-record').selectedIndex=0;
  byId('dish-name').value='';
  byId('dish-price').value='';
  byId('delete-dish').disabled=true;
  renderRecipeForMenu(null);
  byId('dish-name').focus();
});
byId('dish-editor').addEventListener('submit',async event=>{
  event.preventDefault();
  const item=menuRecords.find(record=>record.id===selectedMenuId);
  const payload={name:byId('dish-name').value.trim(),price:byId('dish-price').value,
    active:item?.active??true};
  const button=byId('save-dish');
  button.disabled=true;
  try{
    const saved=await api(selectedMenuId?`menu/${selectedMenuId}`:'menu',selectedMenuId?'PUT':'POST',payload);
    await loadMenuManagement(saved.id,selectedIngredientId);
    await loadOrderingData();
    message(`Dish "${saved.name}" saved. Save its recipe before placing orders.`,false);
  }catch(error){message(error.message,true);}
  finally{button.disabled=false;}
});
byId('delete-dish').addEventListener('click',async()=>{
  if(!selectedMenuId||!window.confirm('Delete this dish? Dishes with order history cannot be deleted.'))return;
  try{
    await api(`menu/${selectedMenuId}`,'DELETE');
    selectedMenuId=null;
    await loadMenuManagement(null,selectedIngredientId);
    await loadOrderingData();
    message('Dish deleted.');
  }catch(error){message(error.message,true);}
});
byId('add-recipe-line').addEventListener('click',()=>appendRecipeLine());
byId('recipe-editor').addEventListener('submit',async event=>{
  event.preventDefault();
  if(!selectedMenuId){message('Save or select a dish before saving its recipe.',true);return;}
  let payload;
  try{payload=recipePayload();}
  catch(error){message(error.message,true);return;}
  const button=byId('save-recipe');
  button.disabled=true;
  try{
    await api(`menu/${selectedMenuId}/recipe`,'PUT',payload);
    await loadMenuManagement(selectedMenuId,selectedIngredientId);
    message('Recipe saved.');
  }catch(error){message(error.message,true);}
  finally{button.disabled=false;}
});
byId('ingredient-record').addEventListener('change',()=>{
  selectedIngredientId=Number(byId('ingredient-record').value);
  const ingredient=ingredientRecords.find(record=>record.id===selectedIngredientId);
  byId('ingredient-name').value=ingredient?.name??'';
  byId('ingredient-unit').value=ingredient?.unit??'g';
  byId('delete-ingredient').disabled=!ingredient;
});
byId('new-ingredient').addEventListener('click',()=>{
  selectedIngredientId=null;
  byId('ingredient-record').selectedIndex=0;
  byId('ingredient-name').value='';
  byId('ingredient-unit').value='g';
  byId('delete-ingredient').disabled=true;
  byId('ingredient-name').focus();
});
byId('ingredient-editor').addEventListener('submit',async event=>{
  event.preventDefault();
  const payload={name:byId('ingredient-name').value.trim(),unit:byId('ingredient-unit').value.trim()};
  const button=byId('save-ingredient');
  button.disabled=true;
  try{
    const saved=await api(selectedIngredientId?`ingredients/${selectedIngredientId}`:'ingredients',
      selectedIngredientId?'PUT':'POST',payload);
    await loadMenuManagement(selectedMenuId,saved.id);
    await loadOrderingData();
    message(`Ingredient "${saved.name}" saved.`);
  }catch(error){message(error.message,true);}
  finally{button.disabled=false;}
});
byId('delete-ingredient').addEventListener('click',async()=>{
  if(!selectedIngredientId||!window.confirm('Delete this ingredient? Referenced ingredients cannot be deleted.'))return;
  try{
    await api(`ingredients/${selectedIngredientId}`,'DELETE');
    selectedIngredientId=null;
    await loadMenuManagement(selectedMenuId,null);
    await loadOrderingData();
    message('Ingredient deleted.');
  }catch(error){message(error.message,true);}
});
byId('add-dish').addEventListener('click',()=>{
  const id=Number(byId('dish-selection').value);
  const dish=ordering.dishes.find(item=>item.id===id);
  if(!dish){message('Choose an available dish first.',true);return;}
  const quantity=orderCart.get(id)||0;
  if(!quantity&&orderCart.size>=20){message('A cart can contain at most 20 different dishes.',true);return;}
  if(quantity>=100){message('A dish quantity cannot exceed 100.',true);return;}
  orderCart.set(id,quantity+1);
  byId('order-receipt').hidden=true;
  renderOrderCart();
  message('');
});
byId('order-cart').addEventListener('click',event=>{
  const button=event.target.closest('button[data-cart-action]');
  if(!button)return;
  const id=Number(button.dataset.dishId);
  const quantity=orderCart.get(id)||0;
  if(button.dataset.cartAction==='remove'||(button.dataset.cartAction==='decrease'&&quantity<=1))orderCart.delete(id);
  else if(button.dataset.cartAction==='decrease')orderCart.set(id,quantity-1);
  else if(button.dataset.cartAction==='increase'&&quantity<100)orderCart.set(id,quantity+1);
  byId('order-receipt').hidden=true;
  renderOrderCart();
});
byId('order-customer').addEventListener('change',updateOrderSummary);
byId('redeem-points').addEventListener('input',updateOrderSummary);
byId('multi-checkout').addEventListener('submit',async event=>{
  event.preventDefault();
  if(!orderCart.size){message('Add at least one dish to the cart.',true);return;}
  const customer=selectedCustomer();
  const branch=ordering.branches.find(item=>item.id===Number(byId('order-branch').value));
  const redeemPoints=Number(byId('redeem-points').value);
  const subtotal=cartSubtotal();
  const cap=redemptionCap(subtotal,customer);
  if(!branch||!customer){message('Choose a branch and customer before checkout.',true);return;}
  if(!Number.isInteger(redeemPoints)||redeemPoints<0||redeemPoints%100!==0||redeemPoints>cap){
    message(`Redeem a multiple of 100 points, up to ${cap} points for this order.`,true);return;
  }
  const cart=[...orderCart].map(([menu_item_id,quantity])=>({menu_item_id,quantity}))
    .sort((a,b)=>a.menu_item_id-b.menu_item_id);
  const payload={branch_id:branch.id,customer_id:customer.id,redeem_points:redeemPoints,lines:cart};
  const signature=JSON.stringify(payload);
  if(!pendingSale||pendingSale.signature!==signature)pendingSale={signature,key:crypto.randomUUID()};
  const button=byId('place-order');
  button.disabled=true;
  try{
    const result=await api('orders','POST',{...payload,request_key:pendingSale.key});
    const completedCart=new Map(orderCart);
    showReceipt(result,completedCart,branch,customer);
    orderCart.clear();
    byId('redeem-points').value='0';
    byId('order-receipt').scrollIntoView({behavior:'smooth',block:'nearest'});
    pendingSale=null;
    renderOrderCart();
    message(`Order #${result.order_id} completed. Total: ${money(result.total)}.`);
    try { await loadOrderingData(); }
    catch(error) { message(`Order #${result.order_id} completed, but points could not be refreshed: ${error.message}`,true); }
    await loadView('orders');
  }catch(error){message(error.message,true);}
  finally{button.disabled=false;}
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

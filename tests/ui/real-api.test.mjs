import test, {before} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {beginSubmit, button, confirm, createApp, fill, idle, login, submit, view, visible, visibleViews, waitFor} from './helpers.mjs';

const base = process.env.UI_TEST_BASE_URL;
const integration = process.env.RUN_UI_INTEGRATION === '1' && base ? test : test.skip;
const uniqueEmail = () => 'ui-' + randomUUID() + '@example.test';
const password = 'UiCustomerTestPass123!';

before(async () => {
  if (integration === test.skip) return;
  const url = new URL(base);
  assert.equal(url.origin, 'http://127.0.0.1:8097');
  const marker = await (await fetch(new URL('/__test_fixture__', base))).json();
  assert.equal(marker.purpose, 'disposable-step7-ui-test');
  assert.match(marker.database, /^hawkerflow_ui_[0-9a-f]{32}_test$/);
  const served = await (await fetch(new URL('/static/app.js', base))).text();
  assert.equal(served, await readFile(new URL('../../app/static/app.js', import.meta.url), 'utf8'));
});

function appFor(t) {
  const app = createApp((path, options) => fetch(new URL(path, base), options), base);
  t.after(app.close);
  return app;
}

integration('Admin account tools create a Customer, edit details, reset credentials and delete an unused disabled account', async t => {
  const admin = await authorized(), email = uniqueEmail(), updatedEmail = uniqueEmail();
  const orders = await (await admin('orders')).json();
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'accounts');
  const creating = beginSubmit(app, 'account-editor', {email, role: 'customer', name: 'Managed Customer', password, confirm_password: password});
  await confirm(app); await idle(creating); assert.match(app.id('message').textContent, /Account created/);
  let list = await (await admin('accounts')).json();
  const original = list.find(account => account.email === email);
  assert.equal(original.name, 'Managed Customer'); assert.ok(original.customer_id > 0);
  let own = await authorized(email, password);
  const findRow = () => [...app.id('results').querySelectorAll('tbody tr')].find(row => row.children[0].textContent === String(original.id));
  button(findRow(), 'Edit details').click(); await waitFor(() => visible(app.id('account-details')));
  const edit = beginSubmit(app, 'account-details', {email: updatedEmail, name: 'Updated Customer'});
  await confirm(app); await idle(edit); assert.match(app.id('message').textContent, /details updated/);
  assert.equal((await own('auth/me')).status, 401);
  list = await (await admin('accounts')).json(); const updated = list.find(account => account.id === original.id);
  assert.equal(updated.email, updatedEmail); assert.equal(updated.name, 'Updated Customer');
  assert.equal(updated.customer_id, original.customer_id);
  own = await authorized(updatedEmail, password);
  button(findRow(), 'Reset password').click(); await waitFor(() => visible(app.id('account-password')));
  const newPassword = 'ManagedNewPassword123!';
  const reset = beginSubmit(app, 'account-password', {password: newPassword, confirm_password: newPassword});
  await confirm(app); await idle(reset); assert.match(app.id('message').textContent, /Password reset/);
  assert.equal(app.id('account-password').elements.password.value, '');
  assert.equal((await own('auth/me')).status, 401);
  const denied = await fetch(new URL('/api/auth/login', base), {method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email: updatedEmail, password})});
  assert.equal(denied.status, 401);
  const fresh = await authorized(updatedEmail, newPassword);
  assert.equal((await (await fresh('auth/me')).json()).id, original.id);
  for (const forbidden of [fresh, await authorized('manager@hawkerflow.local', 'DemoPass123!')]) {
    assert.equal((await forbidden('accounts/'+original.id, 'PUT', {email: uniqueEmail()})).status, 403);
    assert.equal((await forbidden('accounts/'+original.id+'/password', 'PUT', {password})).status, 403);
    assert.equal((await forbidden('accounts/'+original.id, 'DELETE')).status, 403);
  }
  assert.equal((await admin('accounts/'+original.id, 'DELETE')).status, 409);
  button(findRow(), 'Deactivate account').click(); await confirm(app);
  await waitFor(() => !app.id('results').querySelector('.loading') && !findRow());
  await submit(app, 'account-search', {query: updatedEmail.toUpperCase()});
  assert.ok(findRow()); assert.ok(findRow().textContent.includes('Disabled'));
  button(findRow(), 'Delete unused account').click(); await confirm(app);
  await waitFor(() => app.id('message').textContent === 'Unused account deleted.' && !app.id('results').querySelector('.loading'));
  assert.equal((await fresh('auth/me')).status, 401);
  assert.equal((await (await admin('accounts')).json()).some(account => account.id === original.id), false);
  assert.equal((await (await admin('customers')).json()).some(customer => customer.id === original.customer_id), false);
  assert.deepEqual(await (await admin('orders')).json(), orders);
});

integration('purchase history and Mongo reply authors prevent account deletion', async t => {
  const admin = await authorized(), staff = await authorized('manager@hawkerflow.local', 'DemoPass123!');
  const {me, request: own} = await createCustomer(t);
  const sale = await staff('orders', 'POST', {request_key: randomUUID(), branch_id: 1, customer_id: me.customer_id,
    lines: [{menu_item_id: 1, quantity: 1}]});
  assert.equal(sale.status, 201); const order = await sale.json();
  const orders = await (await admin('orders')).json();
  assert.equal((await admin('accounts/'+me.id+'/status', 'PUT', {active: false})).status, 200);
  assert.equal((await admin('accounts/'+me.id, 'DELETE')).status, 409);
  assert.deepEqual(await (await admin('orders')).json(), orders);
  assert.equal((await admin('accounts/'+me.id+'/status', 'PUT', {active: true})).status, 200);
  const email = uniqueEmail();
  const author = await admin('accounts', 'POST', {email, password, role: 'staff'});
  assert.equal(author.status, 201); const account = await author.json();
  const freshCustomer = await authorized((await (await admin('accounts')).json()).find(account => account.id === me.id).email, password);
  assert.equal((await freshCustomer('reviews', 'POST', {order_id: order.order_id, rating: 5, text: 'Account lifecycle review', tags: ['food']})).status, 201);
  const authorRequest = await authorized(email, password);
  assert.equal((await authorRequest('reviews/'+order.order_id+'/replies', 'POST', {text: 'Reply history must be retained.'})).status, 200);
  assert.equal((await admin('accounts/'+account.id+'/status', 'PUT', {active: false})).status, 200);
  const deletion = await admin('accounts/'+account.id, 'DELETE');
  assert.equal(deletion.status, 409); assert.match((await deletion.json()).detail, /reviews or preferences/);
  assert.ok((await (await freshCustomer('reviews')).json())[0].replies.some(reply => reply.manager_user_id === account.id));
  assert.equal((await own('auth/me')).status, 401);
});

integration('Admin point corrections and removals update the balance while preserving original orders and earnings', async t => {
  const buyer = await createCustomer(t), admin = await authorized(), staff = await authorized('manager@hawkerflow.local', 'DemoPass123!');
  const sale = await staff('orders', 'POST', {request_key: randomUUID(), branch_id: 1, customer_id: buyer.me.customer_id,
    lines: [{menu_item_id: 1, quantity: 1}]});
  assert.equal(sale.status, 201); const order = await sale.json();
  const originalOrders = await (await admin('orders')).json();
  const originalMovements = await (await admin('stock/movements')).json();
  const originalEarn = (await (await buyer.request('loyalty')).json()).find(row => row.order_id === order.order_id && row.kind === 'earn');
  assert.ok(originalEarn.delta >= 2);
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'loyalty');
  const earnedRow = () => [...app.id('results').querySelectorAll('tbody tr')].find(row =>
    row.children[1].textContent === String(buyer.me.customer_id) && row.children[3].textContent === 'earn');
  button(earnedRow(), 'Edit points').click();
  await waitFor(() => app.id('points-editor').elements.expected_points.value === String(originalEarn.delta));
  const edit = beginSubmit(app, 'points-editor', {value: '2', reason: 'Fraud review correction'});
  await confirm(app); await idle(edit); assert.match(app.id('message').textContent, /Customer points updated/);
  const balances = async () => (await (await admin('customers')).json()).find(customer => customer.id === buyer.me.customer_id);
  assert.equal((await balances()).points, 2);
  button(earnedRow(), 'Remove points').click();
  await waitFor(() => app.id('points-editor').elements.action.value === 'remove');
  const removal = beginSubmit(app, 'points-editor', {value: '1', reason: 'Confirmed fraudulent point'});
  await confirm(app); await idle(removal); assert.match(app.id('message').textContent, /Customer points updated/);
  assert.equal((await balances()).points, 1);
  const history = (await (await admin('loyalty')).json()).filter(entry => entry.customer_id === buyer.me.customer_id);
  assert.equal(history.filter(entry => entry.kind === 'adjustment').length, 2);
  assert.deepEqual(history.find(entry => entry.kind === 'earn'), originalEarn);
  const correction = history.find(entry => entry.reason === 'Confirmed fraudulent point');
  assert.equal(correction.previous_points, 2); assert.equal(correction.points, 1); assert.equal(correction.delta, -1);
  assert.ok(correction.actor_user_id > 0);
  assert.deepEqual(await (await admin('orders')).json(), originalOrders);
  assert.deepEqual(await (await admin('stock/movements')).json(), originalMovements);
  const body = {points: 0, expected_points: 1, reason: 'Forbidden correction'};
  const basePath = 'loyalty/customers/'+buyer.me.customer_id+'/points';
  for (const request of [staff, buyer.request]) {
    assert.equal((await request(basePath, 'PUT', body)).status, 403);
    assert.equal((await request(basePath+'/removals', 'POST', {amount: 1, expected_points: 1, reason: 'Forbidden removal'})).status, 403);
  }
  assert.equal((await admin(basePath, 'PUT', {...body, expected_points: originalEarn.delta})).status, 409);
  assert.equal((await admin(basePath, 'PUT', {...body, points: '1e3'})).status, 422);
  const ownHistory = await (await buyer.request('loyalty')).json();
  assert.equal(ownHistory.length, 3);
  assert.ok(ownHistory.every(entry => entry.customer_id === buyer.me.customer_id && !('reason' in entry) && !('actor_user_id' in entry)));
  await view(buyer.app, 'loyalty');
  assert.equal(visible(buyer.app.id('points-editor')), false);
  assert.equal(buyer.app.id('results').querySelector('button'), null);
  assert.equal((await balances()).points, 1);
});

integration('Admin creates and edits recipes through the website while history and role boundaries are preserved', async t => {
  const request = await authorized(), staff = await authorized('manager@hawkerflow.local', 'DemoPass123!');
  const customer = await authorized('customer1@hawkerflow.local', 'DemoPass123!');
  const name = 'Recipe UI ' + randomUUID();
  const created = await request('menu', 'POST', {name, price: '5.00'});
  assert.equal(created.status, 201); const item = await created.json();
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'recipes');
  fill(app, 'recipe-editor', {menu_item_id: String(item.id)});
  const rows = () => [...app.id('recipe-components').querySelectorAll('[data-recipe-component]')];
  const setRow = (row, ingredient, quantity) => {
    const select = row.querySelector('select'); select.value = String(ingredient);
    select.dispatchEvent(new app.window.Event('change', {bubbles: true})); row.querySelector('input').value = quantity;
  };
  const save = async () => {
    const form = beginSubmit(app, 'recipe-editor'); await confirm(app); await idle(form);
    assert.match(app.id('message').textContent, /Recipe saved/);
  };
  setRow(rows()[0], 1, '2.000'); await save();
  assert.match(app.id('results').textContent, new RegExp(name));
  const firstSale = await staff('orders', 'POST', {request_key: randomUUID(), branch_id: 1, customer_id: 1,
    lines: [{menu_item_id: item.id, quantity: 1}]});
  assert.equal(firstSale.status, 201); const first = await firstSale.json();
  const beforeOrders = await (await request('orders')).json();
  const beforeMovements = await (await request('stock/movements')).json();
  const beforeStocks = await (await request('stock')).json();
  const beforePoints = await (await request('loyalty')).json();
  setRow(rows()[0], 1, '3.125'); app.id('add-recipe-ingredient').click(); setRow(rows()[1], 2, '0.500');
  app.id('add-recipe-ingredient').click(); button(rows()[2], 'Remove ingredient').click(); await save();
  assert.deepEqual(await (await request('orders')).json(), beforeOrders);
  assert.deepEqual(await (await request('stock/movements')).json(), beforeMovements);
  assert.deepEqual(await (await request('stock')).json(), beforeStocks);
  assert.deepEqual(await (await request('loyalty')).json(), beforePoints);
  const body = {components: [{ingredient_id: 1, quantity: '1.000'}],
    expected_components: [{ingredient_id: 1, quantity: '3.125'}, {ingredient_id: 2, quantity: '0.500'}]};
  assert.equal((await staff('recipes/'+item.id, 'PUT', body)).status, 403);
  assert.equal((await customer('recipes/'+item.id, 'PUT', body)).status, 403);
  assert.equal((await customer('recipes')).status, 403);
  assert.equal((await request('recipes/'+item.id, 'PUT', {...body, expected_components: []})).status, 409);
  assert.equal((await request('recipes/'+item.id, 'PUT', {...body, components: body.components.concat(body.components)})).status, 422);
  const secondSale = await staff('orders', 'POST', {request_key: randomUUID(), branch_id: 1, customer_id: 1,
    lines: [{menu_item_id: item.id, quantity: 1}]});
  assert.equal(secondSale.status, 201);
  const afterStocks = await (await request('stock')).json();
  for (const [ingredient, used] of [[1, 3.125], [2, 0.500]]) {
    const find = stocks => stocks.find(row => row.branch_id === 1 && row.ingredient_id === ingredient);
    assert.equal(Number(find(afterStocks).quantity), Number(find(beforeStocks).quantity)-used);
  }
  const afterOrders = await (await request('orders')).json();
  assert.deepEqual(afterOrders.find(row => row.order_id === first.order_id), beforeOrders.find(row => row.order_id === first.order_id));
  const afterMovements = await (await request('stock/movements')).json();
  assert.deepEqual(afterMovements.filter(row => row.order_id === first.order_id), beforeMovements.filter(row => row.order_id === first.order_id));
  button(rows()[1], 'Remove ingredient').click(); await save();
  assert.deepEqual(await (await request('stock')).json(), afterStocks);
  assert.deepEqual(await (await request('orders')).json(), afterOrders);
  assert.deepEqual(await (await request('stock/movements')).json(), afterMovements);
  const recipe = (await (await request('recipes')).json()).filter(row => row.menu_item_id === item.id);
  assert.equal(recipe.length, 1); assert.equal(recipe[0].quantity, '3.125');
});

integration('Admin stock corrections are audited, restricted and preserve placed orders', async t => {
  const request = await authorized();
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'stock');
  const initial = (await (await request('stock')).json())[0];
  const orders = await (await request('orders')).json();
  fill(app, 'stock-editor', {branch_id: String(initial.branch_id), ingredient_id: String(initial.ingredient_id)});
  await waitFor(() => app.id('stock-editor').elements.expected_quantity.value !== '');
  const corrected = (Number(initial.quantity) - 1).toFixed(3);
  const form = beginSubmit(app, 'stock-editor', {quantity: corrected, reason: 'UI physical stock count'});
  await confirm(app); await idle(form);
  assert.match(app.id('message').textContent, /Stock quantity corrected/);
  const current = (await (await request('stock')).json()).find(row => row.branch_id === initial.branch_id && row.ingredient_id === initial.ingredient_id);
  assert.equal(Number(current.quantity), Number(corrected));
  const movement = (await (await request('stock/movements')).json())[0];
  assert.equal(movement.kind, 'adjustment');
  assert.equal(movement.reason, 'UI physical stock count');
  assert.equal(Number(movement.delta), -1);
  const path = 'stock/' + initial.branch_id + '/' + initial.ingredient_id;
  const body = {quantity: initial.quantity, expected_quantity: initial.quantity, reason: 'Stale correction'};
  assert.equal((await request(path, 'PUT', {...body, quantity: '1e3', expected_quantity: corrected})).status, 422);
  assert.equal((await request('stock/receipts', 'POST', {branch_id: initial.branch_id, ingredient_id: initial.ingredient_id, quantity: '1e3'})).status, 422);
  assert.equal((await request(path, 'PUT', body)).status, 409);
  for (const email of ['manager@hawkerflow.local', 'customer1@hawkerflow.local']) {
    const other = await authorized(email, 'DemoPass123!');
    assert.equal((await other(path, 'PUT', {...body, expected_quantity: corrected})).status, 403);
  }
  for (const method of ['PUT', 'PATCH', 'DELETE']) assert.equal((await request('orders/' + orders[0].order_id, method, {total: '0.00'})).status, 404);
  assert.deepEqual(await (await request('orders')).json(), orders);
  assert.equal((await request(path, 'PUT', {...body, expected_quantity: corrected, reason: 'Restore disposable fixture balance'})).status, 200);
});
async function authorized(email = 'ui-admin@example.test', secret = 'UiAdminTestPass123!') {
  const response = await fetch(new URL('/api/auth/login', base), {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email, password: secret})});
  assert.equal(response.status, 200);
  const result = await response.json();
  return async (path, method = 'GET', body) => fetch(new URL('/api/' + path, base), {method,
    headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + result.access_token},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})});
}
async function createCustomer(t) {
  const app = appFor(t), email = uniqueEmail();
  app.id('show-signup').click();
  await submit(app, 'signup', {name: 'UI customer', email, password, confirm_password: password});
  assert.match(app.id('message').textContent, /ready/);
  await login(app, email, password);
  const request = await authorized(email, password);
  const me = await (await request('auth/me')).json();
  return {app, email, request, me};
}

integration('last Admin cannot demote itself through the website', async t => {
  const request = await authorized();
  const others = (await (await request('accounts')).json()).filter(account => account.role === 'admin' && account.email !== 'ui-admin@example.test');
  t.after(async () => {
    for (const account of others) assert.equal((await request('accounts/' + account.id + '/role', 'PUT', {role: 'admin'})).status, 200);
  });
  for (const account of others) assert.equal((await request('accounts/' + account.id + '/role', 'PUT', {role: 'staff'})).status, 200);
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'accounts');
  const row = [...app.id('results').querySelectorAll('tbody tr')].find(row => row.textContent.includes('ui-admin@example.test'));
  const form = beginSubmit(app, row.querySelector('form'), {role: 'staff'});
  await confirm(app); await idle(form);
  assert.match(app.id('message').textContent, /last Admin/);
  const admin = await authorized();
  assert.equal((await (await admin('auth/me')).json()).role, 'admin');
});

integration('public website signup creates Customer, signs in, and cannot call privileged APIs', async t => {
  const {app, request, me} = await createCustomer(t);
  assert.equal(me.role, 'customer');
  assert.equal(app.id('customer-points').textContent, 'Points balance: 0');
  assert.deepEqual(await (await request('orders')).json(), []);
  assert.deepEqual(await (await request('loyalty')).json(), []);
  await view(app, 'orders'); assert.equal(app.id('results').textContent, 'You have no purchases yet.');
  assert.deepEqual(visibleViews(app), ['menu','orders','loyalty','reviews','profiles/me']);
  assert.equal((await request('accounts')).status, 403);
  assert.equal((await request('accounts', 'POST', {email: uniqueEmail(), password, role: 'admin'})).status, 403);
  assert.equal((await request('profiles')).status, 403);
  assert.equal((await request('auth/signup', 'POST', {name: 'Forged', email: uniqueEmail(), password, role: 'admin'})).status, 422);
  await view(app, 'profiles/me');
  await submit(app, 'profile-editor', {dietary_preferences: 'vegetarian', favourite_tags: 'food'});
  assert.match(app.id('message').textContent, /saved/);
  assert.deepEqual((await (await request('profiles/me')).json()).dietary_preferences, ['vegetarian']);
});

integration('birthday signup persists a valid date, rejects invalid details and keeps private fields scoped to the customer', async t => {
  const app = appFor(t), email = uniqueEmail();
  app.id('show-signup').click();
  await submit(app, 'signup', {name: 'Birthday Buyer', email, birthday: '2000-02-29', password, confirm_password: password});
  assert.match(app.id('message').textContent, /ready/);
  await login(app, email, password);
  assert.equal(app.id('customer-points').textContent, 'Points balance: 0');
  assert.equal(app.id('customer-birthday').textContent, 'Birthday: 2000-02-29');
  const own = await authorized(email, password), admin = await authorized();
  const summary = await (await own('customers/me?customer_id=1')).json();
  assert.equal(summary.birthday, '2000-02-29'); assert.equal(summary.name, 'Birthday Buyer');
  assert.equal(summary.points, 0); assert.ok(summary.id > 50);
  assert.equal((await admin('customers/me')).status, 403);
  const staff = await authorized('manager@hawkerflow.local', 'DemoPass123!');
  assert.equal((await staff('customers/me')).status, 403);
  assert.ok((await (await staff('customers')).json()).every(customer => !('birthday' in customer)));
  const existing = await (await admin('accounts')).json();
  const post = body => fetch(new URL('/api/auth/signup', base), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const body = {name: 'Invalid Buyer', email: uniqueEmail(), password, confirm_password: password};
  for (const birthday of ['2001-02-29', '2999-01-01', '2000-01-01T00:00:00Z']) {
    const response = await post({...body, birthday}); assert.equal(response.status, 422);
    assert.equal((await response.text()).includes(password), false);
  }
  assert.equal((await post({...body, confirm_password: 'DifferentPassword123!'})).status, 422);
  assert.equal((await post({...body, email: email.toUpperCase()})).status, 409);
  assert.deepEqual(await (await admin('accounts')).json(), existing);
  app.id('customer-view-orders').click(); await waitFor(() => app.id('results').textContent === 'You have no purchases yet.');
});

integration('Staff can reply to feedback while backend rejects review administration and profiles', async t => {
  const app = appFor(t); await login(app, 'manager@hawkerflow.local', 'DemoPass123!'); await view(app, 'reviews');
  assert.equal(visibleViews(app).includes('accounts'), false);
  assert.equal(visible(app.id('review-editor')), false);
  const first = app.id('results').querySelector('article');
  const orderId = Number(first.querySelector('h4').textContent.match(/Order (\d+)/)[1]);
  const request = await authorized('manager@hawkerflow.local', 'DemoPass123!');
  const before = (await (await request('reviews')).json()).find(review => review.order_id === orderId);
  await submit(app, first.querySelector('.reply-form'), {text: 'UI Staff business reply'});
  assert.match(app.id('message').textContent, /reply added/);
  const after = (await (await request('reviews')).json()).find(review => review.order_id === orderId);
  assert.equal(after.replies.at(-1).text, 'UI Staff business reply');
  assert.equal(after.text, before.text);
  assert.equal((await request('reviews/' + orderId, 'DELETE')).status, 403);
  assert.equal((await request('reviews/' + orderId, 'PUT', {order_id: orderId, rating: 1, text: 'Forbidden', tags: []})).status, 403);
  assert.equal((await request('reviews/' + orderId + '/replies/0', 'PUT', {text: 'Forbidden'})).status, 403);
  assert.equal((await request('profiles/me')).status, 403);
  assert.equal((await request('profiles')).status, 403);
});

integration('Admin creates Staff and Admin accounts through forms; both can sign in', async t => {
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'accounts');
  const admin = await authorized(), initial = await (await admin('accounts')).json();
  for (const role of ['staff', 'admin']) {
    const email = uniqueEmail();
    const form = beginSubmit(app, 'account-editor', {email, role, password, confirm_password: password});
    await confirm(app); await idle(form);
    assert.match(app.id('message').textContent, /Account created/);
    assert.equal(form.elements.password.value, '');
    const newApp = appFor(t); await login(newApp, email, password);
    assert.match(newApp.id('welcome').textContent, new RegExp(role, 'i'));
  }
  const after = await (await admin('accounts')).json();
  for (const original of initial) assert.deepEqual(after.find(account => account.id === original.id), original);
});

integration('Admin role change preserves ID and updates an already signed-in Staff workspace', async t => {
  const staff = appFor(t); await login(staff, 'cashier@hawkerflow.local', 'DemoPass123!');
  const app = appFor(t); await login(app, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(app, 'accounts');
  const request = await authorized(), before = await (await request('accounts')).json();
  const account = before.find(item => item.email === 'cashier@hawkerflow.local');
  const row = [...app.id('results').querySelectorAll('tbody tr')].find(row => row.textContent.includes(account.email));
  const form = beginSubmit(app, row.querySelector('form'), {role: 'admin'});
  await confirm(app); await idle(form);
  assert.match(app.id('message').textContent, /role updated/);
  staff.id('refresh-view').click();
  await waitFor(() => staff.id('welcome').textContent === 'Admin workspace');
  assert.equal(visibleViews(staff).includes('accounts'), true);
  const after = (await (await request('accounts')).json()).find(item => item.id === account.id);
  assert.equal(after.email, account.email); assert.equal(after.customer_id, account.customer_id);
  assert.equal((await request('accounts/' + account.id + '/role', 'PUT', {role: 'staff'})).status, 200);
  staff.id('refresh-view').click();
  await waitFor(() => staff.id('welcome').textContent === 'Staff workspace' && staff.id('results').querySelector('tbody tr') && !staff.id('results').querySelector('.loading'));
  assert.equal(visibleViews(staff).includes('accounts'), false);
});

integration('Staff website handles stock receipts, customer records and a cash sale', async t => {
  const {me} = await createCustomer(t);
  const app = appFor(t); await login(app, 'manager@hawkerflow.local', 'DemoPass123!');
  await view(app, 'stock');
  await submit(app, 'restock', {branch_id: '1', ingredient_id: '1', quantity: '10', note: 'UI test receipt'});
  assert.match(app.id('message').textContent, /Receipt recorded/);
  await view(app, 'customers');
  await submit(app, 'customer-editor', {name: 'Operational customer', email: uniqueEmail()});
  assert.match(app.id('message').textContent, /record saved/);
  await view(app, 'orders');
  await submit(app, 'checkout', {branch_id: '1', customer_id: String(me.customer_id), menu_item_id: '1', quantity: '1', redeem_points: '0'});
  assert.match(app.id('message').textContent, /Sale completed. Order \d+/);
  await view(app, 'analytics/sql');
  assert.equal(app.id('results').textContent.includes('gross sales'), true);
});

integration('Customer manages a verified purchase review; Admin moderates replies and preferences', async t => {
  const {app: customer, me, request: own} = await createCustomer(t);
  const staff = await authorized('manager@hawkerflow.local', 'DemoPass123!');
  const sale = await staff('orders', 'POST', {request_key: randomUUID(), branch_id: 1, customer_id: me.customer_id,
    lines: [{menu_item_id: 1, quantity: 1}]});
  assert.equal(sale.status, 201);
  const order = await sale.json();
  await view(customer, 'reviews');
  await submit(customer, 'review-editor', {order_id: String(order.order_id), rating: '5', text: 'UI verified purchase review', tags: 'food', food: '5'});
  assert.match(customer.id('message').textContent, /Review saved/);
  const reviews = await (await own('reviews')).json();
  assert.equal(reviews.length, 1); assert.equal(reviews[0].order_id, order.order_id);
  assert.equal((await staff('reviews/' + order.order_id + '/replies', 'POST', {text: 'Initial business reply'})).status, 200);
  await view(customer, 'profiles/me');
  await submit(customer, 'profile-editor', {dietary_preferences: 'vegetarian', favourite_tags: 'food'});
  const admin = appFor(t); await login(admin, 'ui-admin@example.test', 'UiAdminTestPass123!'); await view(admin, 'reviews');
  const card = [...admin.id('results').querySelectorAll('article')].find(item => item.querySelector('h4').textContent.startsWith('Order ' + order.order_id + ' '));
  assert.ok(card);
  button(card, 'Edit reply').click();
  await submit(admin, card.querySelector('.reply form'), {text: 'Admin moderated business reply'});
  assert.match(admin.id('message').textContent, /reply updated/);
  const updated = (await (await own('reviews')).json())[0];
  assert.equal(updated.replies[0].text, 'Admin moderated business reply');
  await view(admin, 'profiles');
  const profileRow = [...admin.id('results').querySelectorAll('tbody tr')].find(row => row.firstElementChild.textContent === String(me.customer_id));
  assert.ok(profileRow);
  button(profileRow, 'Edit preferences').click();
  await submit(admin, 'profile-editor', {dietary_preferences: 'vegetarian, low sugar', favourite_tags: 'service'});
  assert.match(admin.id('message').textContent, /Preferences saved/);
  assert.deepEqual((await (await own('profiles/me')).json()).favourite_tags, ['service']);
});


integration('Admin deactivation preserves IDs and blocks login and old sessions after reactivation', async t => {
  const {app: customer, me, email, request: original} = await createCustomer(t);
  const admin = appFor(t); await login(admin, 'ui-admin@example.test', 'UiAdminTestPass123!');
  await view(admin, 'accounts');
  const findRow = () => [...admin.id('results').querySelectorAll('tbody tr')].find(row => row.textContent.includes(email));
  button(findRow(), 'Deactivate account').click();
  await confirm(admin);
  await waitFor(() => admin.id('message').textContent === 'Account deactivated.' && !admin.id('results').querySelector('.loading') && !findRow());
  admin.id('account-status-view').click();
  await waitFor(() => findRow()?.textContent.includes('Reactivate account'));
  assert.equal((await original('auth/me')).status, 401);
  const denied = await fetch(new URL('/api/auth/login', base), {method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email, password})});
  assert.equal(denied.status, 401);
  button(findRow(), 'Reactivate account').click(); await confirm(admin);
  await waitFor(() => admin.id('message').textContent === 'Account reactivated.' && !admin.id('results').querySelector('.loading') && !findRow());
  admin.id('account-status-view').click();
  await waitFor(() => findRow()?.textContent.includes('Deactivate account'));
  assert.equal((await original('auth/me')).status, 401);
  await login(customer, email, password);
  const fresh = await authorized(email, password);
  assert.equal((await (await fresh('auth/me')).json()).id, me.id);
});

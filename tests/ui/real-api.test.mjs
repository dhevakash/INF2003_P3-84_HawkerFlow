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
  await waitFor(() => admin.id('message').textContent === 'Account deactivated.' && !admin.id('results').querySelector('.loading') && findRow()?.textContent.includes('Reactivate account'));
  assert.equal((await original('auth/me')).status, 401);
  const denied = await fetch(new URL('/api/auth/login', base), {method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email, password})});
  assert.equal(denied.status, 401);
  button(findRow(), 'Reactivate account').click(); await confirm(admin);
  await waitFor(() => admin.id('message').textContent === 'Account reactivated.' && !admin.id('results').querySelector('.loading') && findRow()?.textContent.includes('Deactivate account'));
  assert.equal((await original('auth/me')).status, 401);
  await login(customer, email, password);
  const fresh = await authorized(email, password);
  assert.equal((await (await fresh('auth/me')).json()).id, me.id);
});

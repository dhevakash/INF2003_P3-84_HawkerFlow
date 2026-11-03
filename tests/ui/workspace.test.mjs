import test from 'node:test';
import assert from 'node:assert/strict';
import {beginSubmit, button, confirm, fill, idle, login, mockedApp, submit, view, visible, visibleViews, waitFor} from './helpers.mjs';

const allViews = ['menu','orders','stock','recipes','stock/movements','customers','loyalty','reviews','analytics/sql','analytics/mongo','profiles/me','profiles','accounts'];
const password = 'NewCustomerPass123!';

test('Admin selects branch and ingredient directly to unlock a stock correction', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  app.mock.overrides.set('GET stock', () => [
    {branch_id: 1, branch: 'North', ingredient_id: 1, ingredient: 'Rice', unit: 'g', quantity: '10.000'},
    {branch_id: 1, branch: 'North', ingredient_id: 2, ingredient: 'Oil', unit: 'kg', quantity: '1.125'},
    {branch_id: 2, branch: 'South', ingredient_id: 3, ingredient: 'Eggs', unit: 'pcs', quantity: '7.000'}
  ]);
  await view(app, 'stock');
  const form = app.id('stock-editor');
  assert.equal(form.elements.branch_id.tagName, 'SELECT');
  assert.equal(form.elements.ingredient_id.disabled, true);
  assert.equal(form.elements.quantity.disabled, true);
  fill(app, form, {branch_id: '2', ingredient_id: '3'});
  assert.equal(form.elements.quantity.disabled, false);
  assert.equal(form.elements.reason.disabled, false);
  assert.equal(form.elements.quantity.value, '7.000');
  assert.equal(form.elements.expected_quantity.value, '7.000');
  assert.match(app.id('stock-editor-context').textContent, /South.*Eggs/);
  assert.equal(app.id('stock-quantity-label').textContent, 'Correct quantity (pcs)');
  fill(app, form, {branch_id: '1'});
  assert.equal(form.elements.expected_quantity.value, '');
  assert.equal(form.elements.quantity.disabled, true);
  assert.equal([...form.elements.ingredient_id.options].some(option => option.value === '3'), false);
  fill(app, form, {ingredient_id: '2'});
  assert.equal(form.elements.expected_quantity.value, '1.125');
  form.querySelector('[data-reset]').click();
  assert.equal(form.elements.branch_id.value, '');
  assert.equal(form.elements.quantity.disabled, true);
  fill(app, 'restock', {branch_id: '1', ingredient_id: '2'});
  assert.equal(app.id('restock-quantity-label').textContent, 'Quantity (kg)');
});

test('stock quantities reject typed letters, exponent notation, invalid paste and excess decimal places', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'stock');
  fill(app, 'stock-editor', {branch_id: '1', ingredient_id: '1'});
  for (const id of ['restock', 'stock-editor']) {
    const input = app.id(id).elements.quantity;
    assert.equal(input.type, 'text'); assert.equal(input.inputMode, 'decimal');
    input.value = '12'; input.dispatchEvent(new app.window.Event('input'));
    input.setSelectionRange(2, 2);
    for (const text of ['e', 'E', '+', '-', 'x', ',']) {
      const event = new app.window.InputEvent('beforeinput', {data: text, inputType: 'insertText', cancelable: true});
      input.dispatchEvent(event); assert.equal(event.defaultPrevented, true, text);
    }
    const dot = new app.window.InputEvent('beforeinput', {data: '.', inputType: 'insertText', cancelable: true});
    input.dispatchEvent(dot); assert.equal(dot.defaultPrevented, false);
    input.value = '12.5'; input.dispatchEvent(new app.window.Event('input'));
    input.setSelectionRange(0, input.value.length);
    for (const text of ['1e3', '2E4', 'abc', '1,000', '1.2345']) {
      const event = new app.window.Event('paste', {cancelable: true});
      Object.defineProperty(event, 'clipboardData', {value: {getData: () => text}});
      input.dispatchEvent(event); assert.equal(event.defaultPrevented, true, text);
      assert.equal(input.value, '12.5');
    }
    input.value = '1e3'; input.dispatchEvent(new app.window.Event('input'));
    assert.equal(input.value, '12.5');
  }
  await submit(app, 'restock', {branch_id: '1', ingredient_id: '1', quantity: '1e3'});
  assert.equal(app.requests('stock/receipts').length, 0);
  assert.match(app.id('message').textContent, /digits/);
  await submit(app, 'stock-editor', {quantity: '1e3', reason: 'Invalid exponent'});
  assert.equal(app.requests('stock/1/1', 'PUT').length, 0);
  assert.equal(app.id('confirmation').open, false);
});

test('Admin corrects stock with the displayed balance, a reason and confirmation', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'stock');
  assert.equal(visible(app.id('stock-editor')), true);
  button(app.id('results'), 'Edit stock').click();
  await waitFor(() => app.id('stock-editor').elements.expected_quantity.value === '10.000');
  assert.match(app.id('stock-editor-context').textContent, /Demo branch.*Rice.*10.000 g/);
  assert.equal(app.id('stock-quantity-label').textContent, 'Correct quantity (g)');
  const form = beginSubmit(app, 'stock-editor', {quantity: '0.000', reason: ' Physical count '});
  await waitFor(() => app.id('confirmation').open);
  assert.equal(app.requests('stock/1/1', 'PUT').length, 0);
  await confirm(app); await idle(form);
  assert.deepEqual(app.requests('stock/1/1', 'PUT')[0].body,
    {quantity: '0.000', expected_quantity: '10.000', reason: 'Physical count'});
  assert.match(app.id('message').textContent, /Stock quantity corrected/);
  assert.equal(app.id('stock-editor').elements.expected_quantity.value, '');
});

test('cancelling a stock correction sends no mutation and stale balances show the backend message', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'stock');
  button(app.id('results'), 'Edit stock').click();
  await waitFor(() => app.id('stock-editor').elements.expected_quantity.value === '10.000');
  const form = beginSubmit(app, 'stock-editor', {quantity: '8.000', reason: 'Wastage'});
  await confirm(app, 'cancel'); await idle(form);
  assert.equal(app.requests('stock/1/1', 'PUT').length, 0);
  app.mock.overrides.set('PUT stock/1/1', () => ({status: 409, data: {detail: 'Stock has changed. Refresh Stock and try again.'}}));
  const retry = beginSubmit(app, 'stock-editor');
  await confirm(app); await idle(retry);
  assert.match(app.id('message').textContent, /Stock has changed/);
  assert.equal(app.id('stock-editor').elements.quantity.value, '8.000');
});

for (const role of ['staff', 'customer']) test(role + ' cannot correct stock through forged visible controls', async t => {
  const app = mockedApp(role); t.after(app.close); await login(app);
  if (role === 'staff') await view(app, 'stock');
  assert.equal(visible(app.id('stock-editor')), false);
  assert.equal(app.id('results').textContent.includes('Edit stock'), false);
  await submit(app, 'stock-editor', {branch_id: '1', ingredient_id: '1', quantity: '1.000', expected_quantity: '10.000', reason: 'Forged'});
  assert.equal(app.requests('stock/1/1', 'PUT').length, 0);
  assert.match(app.id('message').textContent, /not allowed/);
  if (role === 'staff') assert.equal(visible(app.id('restock')), true);
});

test('Admin order records have no edit or delete action', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  app.mock.overrides.set('GET orders', () => [{order_id: 7, total: '5.00'}]);
  await view(app, 'orders');
  assert.equal(app.id('results').querySelector('button'), null);
});

for (const role of ['admin', 'staff', 'customer']) test(role + ' signs in and out with a named id control shadowing the form id', async t => {
  const app = mockedApp(role); t.after(app.close);
  const menu = app.id('menu-editor'), customer = app.id('customer-editor');
  assert.equal(menu.id, menu.elements.namedItem('id'));
  assert.equal(customer.id, customer.elements.namedItem('id'));
  fill(app, menu, {name: 'Unsaved item'});
  fill(app, customer, {name: 'Unsaved customer'});
  await login(app);
  assert.equal(menu.elements.namedItem('name').value, '');
  assert.equal(customer.elements.namedItem('name').value, '');
  assert.equal(app.id('message').textContent, 'Signed in.');
  app.id('logout').click();
  assert.equal(app.id('workspace').hidden, true);
  assert.equal(app.id('login-card').hidden, false);
  assert.equal(app.id('message').textContent, 'Signed out.');
});

test('saving menu and customer editors resets the actual form despite named id controls', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  await submit(app, 'menu-editor', {name: 'New dish', price: '7.00', active: true});
  assert.deepEqual(app.requests('menu')[0].body, {name: 'New dish', price: '7.00', active: true});
  assert.equal(app.id('menu-editor').elements.namedItem('name').value, '');
  assert.equal(app.id('menu-editor-title').textContent, 'Add a menu item');
  assert.equal(app.id('message').textContent, 'Menu item saved.');
  await view(app, 'customers');
  await submit(app, 'customer-editor', {name: 'New customer', email: 'new@example.test'});
  assert.deepEqual(app.requests('customers')[0].body, {name: 'New customer', email: 'new@example.test'});
  assert.equal(app.id('customer-editor').elements.namedItem('name').value, '');
  assert.equal(app.id('customer-editor-title').textContent, 'Add a customer record');
  assert.equal(app.id('message').textContent, 'Customer record saved.');
});

test('public signup has no role choice, sends customer fields only and clears passwords', async t => {
  const app = mockedApp(); t.after(app.close);
  assert.deepEqual(visibleViews(app), []);
  app.id('show-signup').click();
  assert.equal(app.id('signup').querySelector('select,[name="role"]'), null);
  await submit(app, 'signup', {name: 'New Buyer', email: 'new@example.test', password, confirm_password: password});
  assert.deepEqual(app.requests('auth/signup')[0].body, {name: 'New Buyer', email: 'new@example.test', password});
  assert.equal(app.id('login-card').hidden, false);
  assert.equal(app.id('login').elements.email.value, 'new@example.test');
  assert.equal(app.id('signup').elements.password.value, '');
  assert.equal(app.id('login').elements.password.value, '');
});

test('signup password mismatch makes no request', async t => {
  const app = mockedApp(); t.after(app.close);
  await submit(app, 'signup', {name: 'Buyer', email: 'new@example.test', password, confirm_password: 'different'});
  assert.equal(app.requests('auth/signup').length, 0);
  assert.match(app.id('message').textContent, /do not match/);
});

for (const role of ['admin', 'staff', 'customer']) test(role + ' has the agreed navigation and menu controls', async t => {
  const app = mockedApp(role); t.after(app.close); await login(app);
  const expected = role === 'customer' ? ['menu','orders','loyalty','reviews','profiles/me'] :
    allViews.filter(path => role === 'admin' ? path !== 'profiles/me' : !['profiles/me','profiles','accounts'].includes(path));
  assert.deepEqual(visibleViews(app), expected);
  assert.equal(visible(app.document.querySelector('[data-panel="menu"]')), role !== 'customer');
  assert.match(app.id('welcome').textContent, new RegExp(role, 'i'));
  assert.equal(app.window.localStorage.length, 0);
  assert.equal(app.window.sessionStorage.length, 0);
});

test('Staff can reply but cannot edit reviews, replies or preferences', async t => {
  const app = mockedApp('staff'); t.after(app.close); await login(app); await view(app, 'reviews');
  const text = app.id('results').textContent;
  for (const forbidden of ['Edit review', 'Delete review', 'Edit reply', 'Delete reply']) assert.equal(text.includes(forbidden), false);
  assert.equal(visible(app.id('review-editor')), false);
  assert.equal(visible(app.id('profile-editor')), false);
  const reply = app.id('results').querySelector('.reply-form');
  await submit(app, reply, {text: 'Thanks for your feedback'});
  assert.deepEqual(app.requests('reviews/7/replies')[0].body, {text: 'Thanks for your feedback'});
  assert.equal(app.requests('profiles', 'GET').length, 0);
});

test('Customer edits own review with category ratings and saves only own preferences', async t => {
  const app = mockedApp('customer'); t.after(app.close); await login(app); await view(app, 'reviews');
  assert.equal(app.id('results').querySelector('.reply-form'), null);
  button(app.id('results'), 'Edit review').click();
  await submit(app, 'review-editor', {text: 'Updated own feedback', service: '5'});
  const review = app.requests('reviews/7', 'PUT')[0].body;
  assert.equal(review.order_id, 7);
  assert.deepEqual(review.category_ratings, {food: 4, service: 5});
  await view(app, 'profiles/me');
  assert.equal(app.id('profile-editor').elements.dietary_preferences.value, 'vegetarian');
  await submit(app, 'profile-editor', {customer_id: '999', dietary_preferences: 'vegan, low sugar', favourite_tags: 'food'});
  assert.deepEqual(app.requests('profiles/me', 'PUT')[0].body, {dietary_preferences: ['vegan','low sugar'], favourite_tags: ['food']});
  assert.equal(app.requests('profiles/999', 'PUT').length, 0);
});

test('Admin can edit/delete business replies and edit another customer profile', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'reviews');
  const reply = app.id('results').querySelector('.reply');
  button(reply, 'Edit reply').click();
  await submit(app, reply.querySelector('form'), {text: 'Updated business reply'});
  assert.deepEqual(app.requests('reviews/7/replies/0', 'PUT')[0].body, {text: 'Updated business reply'});
  button(app.id('results').querySelector('.reply'), 'Delete reply').click();
  await confirm(app);
  await waitFor(() => app.requests('reviews/7/replies/0', 'DELETE').length === 1);
  await view(app, 'profiles');
  button(app.id('results'), 'Edit preferences').click();
  await submit(app, 'profile-editor', {dietary_preferences: 'vegetarian', favourite_tags: 'service'});
  assert.deepEqual(app.requests('profiles/1', 'PUT')[0].body, {dietary_preferences: ['vegetarian'], favourite_tags: ['service']});
});

for (const role of ['admin','staff']) test('Admin creates ' + role + ' only after confirmation, without confirmation field in the API', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  const form = beginSubmit(app, 'account-editor', {email: 'new@example.test', role, password, confirm_password: password});
  await waitFor(() => app.id('confirmation').open);
  assert.equal(app.requests('accounts').length, 0);
  await confirm(app); await idle(form);
  assert.deepEqual(app.requests('accounts')[0].body, {email: 'new@example.test', password, role});
  assert.equal(app.id('account-editor').elements.password.value, '');
});

test('cancelled privileged creation makes no request', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  const form = beginSubmit(app, 'account-editor', {email: 'new@example.test', password, confirm_password: password});
  await confirm(app, 'cancel'); await idle(form);
  assert.equal(app.requests('accounts').length, 0);
});

test('role editing targets the existing ID and surfaces last-Admin rejection', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  const row = [...app.id('results').querySelectorAll('tbody tr')].find(row => row.textContent.includes('staff@example.test'));
  const form = beginSubmit(app, row.querySelector('form'), {role: 'admin'});
  await confirm(app); await idle(form);
  assert.deepEqual(app.requests('accounts/1/role', 'PUT')[0].body, {role: 'admin'});
  assert.equal(app.mock.requests.filter(request => request.method === 'DELETE').length, 0);
  app.mock.overrides.set('PUT accounts/4/role', () => ({status: 409, data: {detail: 'The last Admin account must retain Admin access.'}}));
  const adminRow = [...app.id('results').querySelectorAll('tbody tr')].find(row => row.textContent.includes('admin@example.test'));
  const adminForm = beginSubmit(app, adminRow.querySelector('form'), {role: 'staff'});
  await confirm(app); await idle(adminForm);
  assert.match(app.id('message').textContent, /last Admin/);
});

test('changing role removes stale private data and resets privileged forms', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  fill(app, 'account-editor', {password, confirm_password: password});
  app.mock.role = 'staff';
  app.id('refresh-view').click();
  await waitFor(() => app.id('welcome').textContent === 'Staff workspace' && app.id('view-title').textContent === 'Menu');
  assert.equal(visibleViews(app).includes('accounts'), false);
  assert.equal(app.id('account-editor').elements.password.value, '');
  assert.equal(app.id('results').textContent.includes('admin@example.test'), false);
});

test('forged visible Admin controls cannot make a Staff account-creation request', async t => {
  const app = mockedApp('staff'); t.after(app.close); await login(app);
  app.document.querySelector('[data-view="accounts"]').hidden = false;
  app.document.querySelector('[data-view="accounts"]').click();
  await waitFor(() => !app.id('results').querySelector('.loading'));
  await submit(app, 'account-editor', {email: 'forged@example.test', password, confirm_password: password});
  assert.equal(app.requests('accounts', 'GET').length, 0);
  assert.equal(app.requests('accounts').length, 0);
  assert.match(app.id('message').textContent, /not allowed/);
});

test('expired session clears private results and requires sign-in', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  app.mock.expired = true; app.id('refresh-view').click();
  await waitFor(() => app.id('workspace').hidden);
  assert.equal(app.id('results').textContent, '');
  assert.equal(app.id('login-card').hidden, false);
  assert.deepEqual(visibleViews(app), []);
  assert.match(app.id('message').textContent, /sign in again/);
});

test('unsupported roles never open a workspace', async t => {
  const app = mockedApp('manager'); t.after(app.close);
  await submit(app, 'login', {email: 'old@example.test', password: 'TestPass123!'});
  assert.equal(app.id('workspace').hidden, true);
  assert.deepEqual(visibleViews(app), []);
  assert.match(app.id('message').textContent, /cannot open/);
});

test('logout discards delayed private responses and pending passwords', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  let resolve;
  app.mock.overrides.set('GET accounts', () => new Promise(done => { resolve = done; }));
  app.document.querySelector('[data-view="accounts"]').click();
  await waitFor(() => resolve);
  fill(app, 'account-editor', {password});
  app.id('logout').click();
  resolve([{id: 99, email: 'private@example.test', role: 'admin', customer_id: null}]);
  await new Promise(done => setImmediate(done));
  assert.equal(app.id('workspace').hidden, true);
  assert.equal(app.id('results').textContent, '');
  assert.equal(app.id('account-editor').elements.password.value, '');
});

test('a late failed navigation cannot overwrite the newer view', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  let resolve;
  app.mock.overrides.set('GET stock', () => new Promise(done => { resolve = done; }));
  app.document.querySelector('[data-view="stock"]').click();
  await waitFor(() => resolve);
  await view(app, 'accounts');
  resolve({status: 503, data: {detail: 'Stock unavailable'}});
  await new Promise(done => setImmediate(done));
  assert.equal(app.id('view-title').textContent, 'Accounts');
  assert.equal(app.id('results').textContent.includes('admin@example.test'), true);
});

test('untrusted review text renders as text and validation does not echo secret input', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  app.mock.overrides.set('GET reviews', () => [{order_id: 1, rating: 5, text: '<img src=x onerror=alert(1)>', tags: ['<script>'], replies: []}]);
  await view(app, 'reviews');
  assert.equal(app.id('results').querySelector('img,script'), null);
  assert.equal(app.id('results').textContent.includes('<img'), true);
  app.mock.overrides.set('POST auth/signup', () => ({status: 422, data: {detail: [{msg: 'Invalid password', input: password}]}}));
  app.id('logout').click();
  await submit(app, 'signup', {name: 'Buyer', email: 'new@example.test', password, confirm_password: password});
  assert.equal(app.id('message').textContent, 'Invalid password');
});

test('cash-sale retry preserves request key after network failure', async t => {
  const app = mockedApp('staff'); t.after(app.close); await login(app); await view(app, 'orders');
  let first = true;
  app.mock.overrides.set('POST orders', () => { if (first) { first = false; throw new Error('Network failure'); } return {order_id: 99}; });
  const cart = {branch_id: '1', customer_id: '1', menu_item_id: '1', quantity: '1', redeem_points: '0'};
  await submit(app, 'checkout', cart);
  await submit(app, 'checkout', cart);
  const calls = app.requests('orders');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].body.request_key, calls[1].body.request_key);
  assert.match(app.id('message').textContent, /Order 99/);
});


test('Admin status controls deactivate and reactivate the same account ID', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  const account = {id: 1, email: 'staff@example.test', role: 'staff', customer_id: null, active: true};
  app.mock.overrides.set('GET accounts', () => [account]);
  app.mock.overrides.set('PUT accounts/1/status', request => { account.active = request.body.active; return {...account}; });
  await view(app, 'accounts');
  button(app.id('results'), 'Deactivate account').click();
  await confirm(app);
  await waitFor(() => app.id('results').textContent.includes('Reactivate account'));
  assert.deepEqual(app.requests('accounts/1/status', 'PUT')[0].body, {active: false});
  button(app.id('results'), 'Reactivate account').click();
  await confirm(app);
  await waitFor(() => app.requests('accounts/1/status', 'PUT').length === 2 && app.id('results').textContent.includes('Deactivate account') && !app.id('results').querySelector('.loading'));
  assert.deepEqual(app.requests('accounts/1/status', 'PUT')[1].body, {active: true});
});

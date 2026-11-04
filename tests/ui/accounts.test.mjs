import test from 'node:test';
import assert from 'node:assert/strict';
import {beginSubmit, button, confirm, fill, idle, login, mockedApp, submit, view, visible, waitFor} from './helpers.mjs';

const password = 'ManagedCustomerPass123!';
const accounts = [
  {id: 1, email: 'staff@example.test', role: 'staff', customer_id: null, name: null, active: true},
  {id: 2, email: 'buyer@example.test', role: 'customer', customer_id: 1, name: 'Buyer Name', active: true},
  {id: 7, email: 'disabled@example.test', role: 'customer', customer_id: 8, name: 'Hidden Buyer', active: false}
];
async function setup(t, role = 'admin') {
  const app = mockedApp(role); t.after(app.close);
  app.mock.overrides.set('GET accounts', () => accounts.map(account => ({...account})));
  await login(app);
  if (role === 'admin') await view(app, 'accounts');
  return app;
}
const rowFor = (app, email) => [...app.id('results').querySelectorAll('tbody tr')].find(row => row.textContent.includes(email));

test('active accounts appear by default and universal search finds disabled accounts by name, email, role and ID', async t => {
  const app = await setup(t);
  assert.ok(rowFor(app, 'staff@example.test')); assert.equal(rowFor(app, 'disabled@example.test'), undefined);
  for (const query of ['hidden buyer', 'DISABLED@EXAMPLE.TEST', '7', 'customer']) {
    await submit(app, 'account-search', {query}); assert.ok(rowFor(app, 'disabled@example.test'));
  }
  app.id('account-search-clear').click(); await waitFor(() => !rowFor(app, 'disabled@example.test'));
  app.id('account-status-view').click(); await waitFor(() => rowFor(app, 'disabled@example.test'));
  assert.equal(rowFor(app, 'staff@example.test'), undefined);
  await submit(app, 'account-search', {query: 'staff@example.test'});
  assert.ok(rowFor(app, 'staff@example.test'));
  app.id('account-status-view').click(); await waitFor(() => rowFor(app, 'buyer@example.test'));
  await submit(app, 'account-search', {query: '<script>'});
  assert.equal(app.id('results').textContent, 'No accounts match your search.');
});

test('Admin creates Customer with a name and keeps existing Staff/Admin creation fields', async t => {
  const app = await setup(t), form = app.id('account-editor');
  fill(app, form, {role: 'customer'});
  assert.ok(visible(app.id('account-create-name'))); assert.ok(form.elements.name.required);
  const creating = beginSubmit(app, form, {email: 'new@example.test', name: 'New Buyer', password, confirm_password: password});
  await confirm(app); await idle(creating);
  assert.deepEqual(app.requests('accounts')[0].body, {email: 'new@example.test', role: 'customer', name: 'New Buyer', password});
  assert.equal(form.elements.password.value, ''); assert.equal(form.elements.name.value, '');
  assert.equal(form.elements.name.disabled, true); assert.equal(visible(app.id('account-create-name')), false);
});

test('Edit details updates permitted fields on the same account and does not send role, status or points', async t => {
  const app = await setup(t);
  button(rowFor(app, 'buyer@example.test'), 'Edit details').click();
  await waitFor(() => visible(app.id('account-details')));
  assert.equal(app.id('account-details').elements.name.value, 'Buyer Name');
  const editing = beginSubmit(app, 'account-details', {email: 'updated@example.test', name: 'Updated Name'});
  await confirm(app); await idle(editing);
  assert.deepEqual(app.requests('accounts/2', 'PUT')[0].body, {email: 'updated@example.test', name: 'Updated Name'});
  assert.equal(visible(app.id('account-details')), false);
  button(rowFor(app, 'staff@example.test'), 'Edit details').click();
  await waitFor(() => visible(app.id('account-details')));
  assert.equal(visible(app.id('account-details-name')), false);
  const staff = beginSubmit(app, 'account-details', {email: 'staff-new@example.test'});
  await confirm(app); await idle(staff);
  assert.deepEqual(app.requests('accounts/1', 'PUT')[0].body, {email: 'staff-new@example.test'});
});

test('password reset requires matching confirmation and clears passwords on success and Cancel reset', async t => {
  const app = await setup(t);
  button(rowFor(app, 'staff@example.test'), 'Reset password').click();
  await waitFor(() => visible(app.id('account-password')));
  await submit(app, 'account-password', {password, confirm_password: 'MismatchPassword!'});
  assert.equal(app.requests('accounts/1/password', 'PUT').length, 0);
  assert.match(app.id('message').textContent, /Passwords do not match/);
  const reset = beginSubmit(app, 'account-password', {password, confirm_password: password});
  await confirm(app, 'cancel'); await idle(reset);
  assert.equal(app.requests('accounts/1/password', 'PUT').length, 0);
  const saved = beginSubmit(app, 'account-password', {password, confirm_password: password});
  await confirm(app); await idle(saved);
  assert.deepEqual(app.requests('accounts/1/password', 'PUT')[0].body, {password});
  assert.equal(app.id('account-password').elements.password.value, '');
  assert.equal(visible(app.id('account-password')), false);
  button(rowFor(app, 'staff@example.test'), 'Reset password').click();
  await waitFor(() => visible(app.id('account-password')));
  fill(app, 'account-password', {password, confirm_password: password});
  button(app.id('account-password'), 'Cancel reset').click();
  assert.equal(app.id('account-password').elements.password.value, '');
});

test('only disabled accounts offer deletion and backend linked-history rejection keeps the account', async t => {
  const app = await setup(t);
  assert.equal(app.id('results').textContent.includes('Delete unused account'), false);
  app.id('account-status-view').click(); await waitFor(() => rowFor(app, 'disabled@example.test'));
  app.mock.overrides.set('DELETE accounts/7', () => ({status: 409, data: {detail: 'This account has linked orders. Keep it disabled to preserve history.'}}));
  button(rowFor(app, 'disabled@example.test'), 'Delete unused account').click();
  await confirm(app, 'cancel'); await waitFor(() => !app.id('confirmation').open);
  assert.equal(app.requests('accounts/7', 'DELETE').length, 0);
  await waitFor(() => !button(rowFor(app, 'disabled@example.test'), 'Delete unused account').disabled);
  button(rowFor(app, 'disabled@example.test'), 'Delete unused account').click(); await confirm(app);
  await waitFor(() => app.id('message').textContent.includes('linked orders'));
  assert.ok(rowFor(app, 'disabled@example.test'));
  assert.equal(app.requests('accounts/7', 'DELETE').length, 1);
});

test('account details and reset drafts clear on navigation, sign-out and access changes', async t => {
  const app = await setup(t);
  button(rowFor(app, 'staff@example.test'), 'Reset password').click();
  await waitFor(() => visible(app.id('account-password')));
  fill(app, 'account-password', {password, confirm_password: password});
  await view(app, 'menu'); assert.equal(app.id('account-password').elements.password.value, '');
  await view(app, 'accounts');
  button(rowFor(app, 'staff@example.test'), 'Reset password').click();
  await waitFor(() => visible(app.id('account-password')));
  fill(app, 'account-password', {password, confirm_password: password});
  app.mock.role = 'staff'; app.id('refresh-view').click();
  await waitFor(() => app.id('welcome').textContent === 'Staff workspace');
  assert.equal(app.id('account-password').elements.password.value, '');
  assert.equal(app.id('results').textContent.includes('disabled@example.test'), false);
});

for (const role of ['staff', 'customer']) test(role + ' cannot use forged account management forms', async t => {
  const app = await setup(t, role);
  for (const [id, values] of [['account-details', {account_id: '1', email: 'forged@example.test'}],
    ['account-password', {account_id: '1', password, confirm_password: password}], ['account-search', {query: 'admin'}]]) {
    await submit(app, id, values);
  }
  assert.equal(app.requests('accounts/1', 'PUT').length, 0);
  assert.equal(app.requests('accounts/1/password', 'PUT').length, 0);
  assert.equal(app.requests('accounts', 'GET').length, 0);
});

test('resetting the signed-in Admin password returns to sign-in and clears the private form', async t => {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'accounts');
  button(rowFor(app, 'admin@example.test'), 'Reset password').click();
  await waitFor(() => visible(app.id('account-password')));
  const form = beginSubmit(app, 'account-password', {password, confirm_password: password});
  await confirm(app); await idle(form);
  assert.equal(app.id('workspace').hidden, true);
  assert.equal(app.id('account-password').elements.password.value, '');
  assert.match(app.id('message').textContent, /sign in with your new password/);
});

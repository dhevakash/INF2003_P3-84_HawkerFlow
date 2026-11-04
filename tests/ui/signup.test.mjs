import test from 'node:test';
import assert from 'node:assert/strict';
import {beginSubmit, fill, idle, login, mockedApp, submit, view, visible, waitFor} from './helpers.mjs';

const password = 'BirthdayCustomerPass123!';

test('signup sends optional birthday and confirmation without any privileged fields', async t => {
  const app = mockedApp(); t.after(app.close);
  app.id('show-signup').click();
  const input = app.id('signup').elements.birthday;
  assert.equal(input.type, 'date'); assert.equal(input.required, false);
  assert.match(input.max, /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/);
  await submit(app, 'signup', {name: 'Birthday Buyer', email: 'birthday@example.test', birthday: '2000-02-29', password, confirm_password: password});
  assert.deepEqual(app.requests('auth/signup')[0].body, {name: 'Birthday Buyer', email: 'birthday@example.test',
    birthday: '2000-02-29', password, confirm_password: password});
  assert.equal(input.value, ''); assert.equal(app.id('signup').elements.password.value, '');
  assert.equal(app.id('login').elements.email.value, 'birthday@example.test');
});

test('a new Customer sees zero points and their own empty purchase history immediately after sign-in', async t => {
  const app = mockedApp('customer'); t.after(app.close);
  app.mock.overrides.set('GET customers/me', () => ({id: 1, name: 'New Buyer', email: 'new@example.test', birthday: null, points: 0}));
  app.mock.overrides.set('GET orders', () => []);
  await login(app, 'new@example.test', password);
  assert.equal(visible(app.id('customer-summary')), true);
  assert.equal(app.id('customer-points').textContent, 'Points balance: 0');
  assert.equal(visible(app.id('customer-birthday')), false);
  app.id('customer-view-orders').click();
  await waitFor(() => app.id('results').textContent === 'You have no purchases yet.');
  assert.equal(app.requests('customers', 'GET').length, 0);
});

test('own birthday and points refresh from the server and clear on sign-out', async t => {
  const app = mockedApp('customer'); t.after(app.close);
  let points = 0;
  app.mock.overrides.set('GET customers/me', () => ({id: 1, name: 'Buyer', email: 'buyer@example.test', birthday: '2000-02-29', points}));
  await login(app);
  assert.equal(app.id('customer-birthday').textContent, 'Birthday: 2000-02-29');
  assert.ok(visible(app.id('customer-birthday')));
  points = 23; await view(app, 'loyalty');
  assert.equal(app.id('customer-points').textContent, 'Points balance: 23');
  app.id('logout').click();
  assert.equal(visible(app.id('customer-summary')), false);
  assert.equal(app.id('customer-birthday').textContent, '');
  assert.equal(app.id('customer-points').textContent.includes('23'), false);
});

test('returning to login clears birthday and passwords; duplicate signup displays the backend rejection', async t => {
  const app = mockedApp(); t.after(app.close);
  app.id('show-signup').click(); fill(app, 'signup', {birthday: '2000-02-29', password, confirm_password: password});
  app.id('show-login').click(); assert.equal(app.id('signup').elements.birthday.value, '');
  assert.equal(app.id('signup').elements.password.value, '');
  app.mock.overrides.set('POST auth/signup', () => ({status: 409, data: {detail: 'This email is already in use.'}}));
  app.id('show-signup').click();
  await submit(app, 'signup', {name: 'Duplicate', email: 'buyer@example.test', password, confirm_password: password});
  assert.match(app.id('message').textContent, /already in use/);
  assert.equal(app.id('signup-card').hidden, false);
});

test('a delayed private customer summary is discarded after logout', async t => {
  const app = mockedApp('customer'); t.after(app.close); await login(app);
  let resolve;
  app.mock.overrides.set('GET customers/me', () => new Promise(done => { resolve = done; }));
  app.id('refresh-view').click(); await waitFor(() => resolve);
  app.id('logout').click();
  resolve({id: 1, name: 'Private', email: 'buyer@example.test', birthday: '2000-02-29', points: 999});
  await new Promise(done => setTimeout(done, 20));
  assert.equal(visible(app.id('customer-summary')), false);
  assert.equal(app.id('customer-birthday').textContent, '');
  assert.equal(app.id('customer-points').textContent.includes('999'), false);
});

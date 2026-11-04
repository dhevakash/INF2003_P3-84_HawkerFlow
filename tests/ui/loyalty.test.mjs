import test from 'node:test';
import assert from 'node:assert/strict';
import {beginSubmit, button, confirm, fill, idle, login, mockedApp, submit, view, visible, waitFor} from './helpers.mjs';

async function admin(t) {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'loyalty'); return app;
}

test('Admin edits a customer balance from a history-row button with reason and confirmation', async t => {
  const app = await admin(t);
  button(app.id('results'), 'Edit points').click();
  await waitFor(() => app.id('points-editor').elements.expected_points.value === '100');
  assert.equal(app.id('points-editor').elements.value.value, '100');
  assert.match(app.id('points-current-balance').textContent, /Buyer.*100 points/);
  const form = beginSubmit(app, 'points-editor', {value: '80', reason: ' Fraud correction '});
  await waitFor(() => app.id('confirmation').open);
  assert.match(app.id('confirmation-text').textContent, /100 → 80/);
  assert.equal(app.requests('loyalty/customers/1/points', 'PUT').length, 0);
  await confirm(app); await idle(form);
  assert.deepEqual(app.requests('loyalty/customers/1/points', 'PUT')[0].body,
    {points: 80, expected_points: 100, reason: 'Fraud correction'});
  assert.match(app.id('message').textContent, /Customer points updated/);
});

test('Admin removes a chosen amount while preserving the history entry', async t => {
  const app = await admin(t);
  button(app.id('results'), 'Remove points').click();
  await waitFor(() => app.id('points-editor').elements.action.value === 'remove');
  assert.equal(app.id('points-editor').elements.value.value, '5');
  assert.equal(app.id('points-value-label').textContent, 'Points to remove');
  const form = beginSubmit(app, 'points-editor', {value: '30', reason: 'Fraudulent points'});
  await confirm(app); await idle(form);
  assert.deepEqual(app.requests('loyalty/customers/1/points/removals')[0].body,
    {amount: 30, expected_points: 100, reason: 'Fraudulent points'});
  assert.equal(app.mock.requests.some(request => request.method === 'DELETE'), false);
  assert.match(app.id('results').textContent, /earn/);
});

test('points corrections reject decimals, exponents, excessive removal and missing reasons', async t => {
  const app = await admin(t);
  fill(app, 'points-editor', {customer_id: '1'});
  const input = app.id('points-editor').elements.value; input.focus(); input.setSelectionRange(input.value.length, input.value.length);
  for (const char of ['e', 'E', '.', '-', '+']) {
    const event = new app.window.InputEvent('beforeinput', {data: char, inputType: 'insertText', cancelable: true});
    input.dispatchEvent(event); assert.equal(event.defaultPrevented, true);
  }
  for (const value of ['1e3', '1.5', '-1', '2147483648']) {
    await submit(app, 'points-editor', {value, reason: 'Fraud'});
    assert.match(app.id('message').textContent, /whole-number/);
  }
  await submit(app, 'points-editor', {value: '80', reason: ' '});
  assert.match(app.id('message').textContent, /reason/);
  await submit(app, 'points-editor', {action: 'remove', value: '101', reason: 'Fraud'});
  assert.match(app.id('message').textContent, /available balance/);
  assert.equal(app.mock.requests.some(request => request.path.startsWith('loyalty/customers/')), false);
});

test('cancelling a points edit sends no request and stale balances keep the draft', async t => {
  const app = await admin(t); fill(app, 'points-editor', {customer_id: '1', value: '80', reason: 'Fraud'});
  const form = beginSubmit(app, 'points-editor'); await confirm(app, 'cancel'); await idle(form);
  assert.equal(app.requests('loyalty/customers/1/points', 'PUT').length, 0);
  app.mock.overrides.set('PUT loyalty/customers/1/points', () => ({status: 409,
    data: {detail: 'This points balance has changed. Refresh Points history and select the customer again.'}}));
  const retry = beginSubmit(app, 'points-editor'); await confirm(app); await idle(retry);
  assert.match(app.id('message').textContent, /balance has changed/);
  assert.equal(app.id('points-editor').elements.value.value, '80');
});

for (const role of ['staff', 'customer']) test(role + ' cannot correct points through forged controls', async t => {
  const app = mockedApp(role); t.after(app.close); await login(app); await view(app, 'loyalty');
  assert.equal(visible(app.id('points-editor')), false);
  assert.equal(app.id('results').querySelector('button'), null);
  assert.equal(app.requests('customers', 'GET').length, 0);
  await submit(app, 'points-editor', {value: '80', reason: 'Forged'});
  assert.match(app.id('message').textContent, /not allowed/);
  assert.equal(app.mock.requests.some(request => request.path.startsWith('loyalty/customers/')), false);
});

test('correction details render safely and points drafts clear on sign-out', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  app.mock.overrides.set('GET loyalty', () => [{id: null, adjustment_id: 1, customer_id: 1,
    order_id: null, kind: 'adjustment', delta: -20, previous_points: 100, points: 80, actor_user_id: 4,
    reason: '<img src=x onerror=alert(1)>', created_at: '2026-11-04T00:00:00Z'}]);
  await view(app, 'loyalty');
  assert.match(app.id('results').querySelector('details').textContent, /100 → 80.*Admin ID: 4/);
  assert.equal(app.id('results').querySelector('img'), null);
  fill(app, 'points-editor', {customer_id: '1', value: '80', reason: 'Private investigation'});
  app.id('logout').click();
  assert.equal(app.id('points-editor').elements.reason.value, '');
  assert.equal(app.id('points-editor').elements.customer_id.options.length, 1);
});

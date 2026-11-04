import test from 'node:test';
import assert from 'node:assert/strict';
import {beginSubmit, button, confirm, fill, idle, login, mockedApp, submit, view, visible, waitFor} from './helpers.mjs';

const rows = app => [...app.id('recipe-components').querySelectorAll('[data-recipe-component]')];
function component(app, row, id, quantity) {
  const select = row.querySelector('select'); select.value = String(id);
  select.dispatchEvent(new app.window.Event('change', {bubbles: true}));
  row.querySelector('input').value = quantity;
}
async function admin(t) {
  const app = mockedApp(); t.after(app.close); await login(app); await view(app, 'recipes');
  fill(app, 'recipe-editor', {menu_item_id: '1'});
  return app;
}

test('Admin edits quantities and adds/removes named ingredients with units before confirming a recipe', async t => {
  const app = await admin(t);
  assert.equal(visible(app.id('recipe-editor')), true);
  assert.match(app.id('results').textContent, /Rice meal/);
  assert.match(rows(app)[0].textContent, /Quantity per serving \(g\)/);
  component(app, rows(app)[0], 1, '3.125');
  app.id('add-recipe-ingredient').click(); component(app, rows(app)[1], 2, '0.500');
  assert.match(rows(app)[1].textContent, /Quantity per serving \(kg\)/);
  app.id('add-recipe-ingredient').click();
  button(rows(app)[2], 'Remove ingredient').click();
  assert.equal(rows(app).length, 2);
  const form = beginSubmit(app, 'recipe-editor');
  await waitFor(() => app.id('confirmation').open);
  assert.match(app.id('confirmation-text').textContent, /Future sales/);
  assert.equal(app.requests('recipes/1', 'PUT').length, 0);
  await confirm(app); await idle(form);
  assert.deepEqual(app.requests('recipes/1', 'PUT')[0].body, {
    components: [{ingredient_id: 1, quantity: '3.125'}, {ingredient_id: 2, quantity: '0.500'}],
    expected_components: [{ingredient_id: 1, quantity: '2.000'}]
  });
  assert.match(app.id('message').textContent, /Recipe saved/);
});

test('Admin can create a recipe for a menu item that has no ingredients yet', async t => {
  const app = mockedApp(); t.after(app.close); await login(app);
  app.mock.overrides.set('GET menu', () => [{id: 2, name: 'New dish', active: true}]);
  await view(app, 'recipes'); fill(app, 'recipe-editor', {menu_item_id: '2'});
  assert.equal(rows(app).length, 1);
  component(app, rows(app)[0], 3, '2');
  const form = beginSubmit(app, 'recipe-editor'); await confirm(app); await idle(form);
  assert.deepEqual(app.requests('recipes/2', 'PUT')[0].body,
    {components: [{ingredient_id: 3, quantity: '2'}], expected_components: []});
});

test('recipe editor rejects duplicate ingredients, zero, exponent strings and an empty recipe', async t => {
  const app = await admin(t);
  app.id('add-recipe-ingredient').click(); component(app, rows(app)[1], 1, '1');
  await submit(app, 'recipe-editor'); assert.match(app.id('message').textContent, /only once/);
  button(rows(app)[1], 'Remove ingredient').click();
  const quantity = rows(app)[0].querySelector('input');
  quantity.focus();
  const event = new app.window.InputEvent('beforeinput', {data: 'e', inputType: 'insertText', cancelable: true});
  quantity.dispatchEvent(event); assert.equal(event.defaultPrevented, true);
  for (const value of ['0', '1e3', '-1', '1.2345']) {
    quantity.value = value; await submit(app, 'recipe-editor');
    assert.match(app.id('message').textContent, /positive quantity/);
  }
  button(rows(app)[0], 'Remove ingredient').click(); await submit(app, 'recipe-editor');
  assert.match(app.id('message').textContent, /needs between 1 and 100/);
  assert.equal(app.requests('recipes/1', 'PUT').length, 0);
});

test('cancelled recipe saves send no request and stale edits retain the entered quantities', async t => {
  const app = await admin(t); component(app, rows(app)[0], 1, '4.000');
  const form = beginSubmit(app, 'recipe-editor'); await confirm(app, 'cancel'); await idle(form);
  assert.equal(app.requests('recipes/1', 'PUT').length, 0);
  app.mock.overrides.set('PUT recipes/1', () => ({status: 409, data: {detail: 'This recipe has changed. Refresh Recipes and select the menu item again.'}}));
  const retry = beginSubmit(app, 'recipe-editor'); await confirm(app); await idle(retry);
  assert.match(app.id('message').textContent, /recipe has changed/);
  assert.equal(rows(app)[0].querySelector('input').value, '4.000');
});

for (const role of ['staff', 'customer']) test(role + ' cannot submit recipe edits through forged controls', async t => {
  const app = mockedApp(role); t.after(app.close); await login(app);
  if (role === 'staff') {
    await view(app, 'recipes');
    assert.match(app.id('results').textContent, /Rice meal/);
    assert.match(app.id('results').textContent, /Rice/);
    assert.equal(app.id('results').querySelector('button'), null);
  }
  assert.equal(visible(app.id('recipe-editor')), false);
  assert.equal(app.requests('ingredients', 'GET').length, 0);
  await submit(app, 'recipe-editor');
  assert.match(app.id('message').textContent, /not allowed/);
  assert.equal(app.requests('recipes/1', 'PUT').length, 0);
});

test('recipe drafts and ingredient choices are cleared on sign-out', async t => {
  const app = await admin(t);
  assert.equal(rows(app).length, 1);
  app.id('logout').click();
  assert.equal(rows(app).length, 0);
  assert.equal(app.id('recipe-editor').elements.menu_item_id.options.length, 1);
});

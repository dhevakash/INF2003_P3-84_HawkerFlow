import {readFile} from 'node:fs/promises';
import {setTimeout as pause} from 'node:timers/promises';
import {randomUUID} from 'node:crypto';
import {JSDOM, VirtualConsole} from 'jsdom';

const html = await readFile(new URL('../../app/static/index.html', import.meta.url), 'utf8');
const script = await readFile(new URL('../../app/static/app.js', import.meta.url), 'utf8');

export async function waitFor(predicate, description = 'UI update', timeout = 5000) {
  const end = Date.now() + timeout;
  while (!predicate()) {
    if (Date.now() > end) throw new Error('Timed out waiting for ' + description);
    await pause(5);
  }
}

export function createApp(fetcher, url = 'http://localhost/') {
  const errors = [], virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html, {url, runScripts: 'outside-only', virtualConsole});
  const {window} = dom;
  // Browsers expose named controls ahead of native form properties; jsdom does not.
  // Model the existing name="id" controls so sign-in/reset tests catch that collision.
  for (const form of window.document.forms) {
    const namedId = form.elements.namedItem('id');
    if (namedId) Object.defineProperty(form, 'id', {get: () => namedId});
  }
  window.fetch = fetcher;
  window.HTMLElement.prototype.scrollIntoView = function () {};
  Object.defineProperty(window.crypto, 'randomUUID', {value: randomUUID});
  // jsdom has no native dialog UI/layout. Model the standard close event.
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function (value = '') {
    this.returnValue = value; this.open = false; this.dispatchEvent(new window.Event('close'));
  };
  window.eval(script);
  const document = window.document;
  return {dom, window, document, errors,
    id: id => document.getElementById(id),
    close: () => { window.close(); if (errors.length) throw new AggregateError(errors, 'UI runtime errors'); }};
}

export function fill(app, idOrForm, values) {
  const form = typeof idOrForm === 'string' ? app.id(idOrForm) : idOrForm;
  for (const [name, value] of Object.entries(values)) {
    const element = form.elements.namedItem(name);
    if (!element) throw new Error('Missing form field: ' + name);
    if (element.type === 'checkbox') element.checked = value;
    else element.value = value;
    if (element.tagName === 'SELECT') element.dispatchEvent(new app.window.Event('change', {bubbles: true}));
  }
  return form;
}

export function beginSubmit(app, idOrForm, values = {}) {
  const form = fill(app, idOrForm, values);
  form.dispatchEvent(new app.window.Event('submit', {bubbles: true, cancelable: true}));
  return form;
}

export async function idle(form) { await waitFor(() => !form.dataset.busy, 'form submission', 15000); }
export async function submit(app, idOrForm, values = {}) { await idle(beginSubmit(app, idOrForm, values)); }
export async function confirm(app, value = 'confirm') {
  await waitFor(() => app.id('confirmation').open, 'confirmation');
  app.id('confirmation').close(value);
}
export async function login(app, email = 'admin@example.test', password = 'TestPass123!') {
  await submit(app, 'login', {email, password});
  if (app.id('workspace').hidden) throw new Error(app.id('message').textContent || 'Sign-in failed');
}
export async function view(app, path) {
  const button = app.document.querySelector('[data-view="' + path + '"]');
  button.click();
  await waitFor(() => button.getAttribute('aria-current') === 'page' && !app.id('results').querySelector('.loading'), 'view ' + path);
}
export function button(parent, text) {
  const result = [...parent.querySelectorAll('button')].find(element => element.textContent === text);
  if (!result) throw new Error('Missing button: ' + text);
  return result;
}
export function visible(element) { return element !== null && !element.closest('[hidden]'); }
export function visibleViews(app) {
  return [...app.document.querySelectorAll('[data-view]')].filter(visible).map(element => element.dataset.view);
}

export function mockedApp(role = 'admin') {
  const mock = {role, requests: [], overrides: new Map(), expired: false};
  const defaults = {
    health: {sql: 'connected', sql_dialect: 'test', mongo: 'connected'},
    menu: [{id: 1, name: 'Rice meal', price: '5.00', active: true}],
    stock: [{branch_id: 1, branch: 'Demo branch', ingredient_id: 1, ingredient: 'Rice', unit: 'g', quantity: '10.000'}],
    accounts: [
      {id: 1, email: 'staff@example.test', role: 'staff', customer_id: null, active: true},
      {id: 4, email: 'admin@example.test', role: 'admin', customer_id: null, active: true},
      {id: 2, email: 'buyer@example.test', role: 'customer', customer_id: 1, active: true}
    ],
    reviews: [{order_id: 7, customer_id: 1, rating: 5, text: 'Good food', tags: ['food'],
      category_ratings: {food: 4}, replies: [{manager_user_id: 1, text: 'Thank you', created_at: '2026-10-30T00:00:00Z'}]}],
    'profiles/me': {customer_id: 1, dietary_preferences: ['vegetarian'], favourite_tags: ['food']},
    profiles: [{customer_id: 1, dietary_preferences: ['vegetarian'], favourite_tags: ['food']}]
  };
  const app = createApp(async (url, options = {}) => {
    const path = url.replace('/api/', ''), method = options.method || 'GET';
    const body = options.body === undefined ? undefined : JSON.parse(options.body);
    const request = {path, method, body, headers: options.headers};
    mock.requests.push(request);
    let result;
    const override = mock.overrides.get(method + ' ' + path);
    if (override) result = await override(request);
    else if (path === 'auth/login') result = {access_token: 'test-token', role: mock.role, customer_id: mock.role === 'customer' ? 1 : null};
    else if (path === 'auth/me') result = mock.expired ? {status: 401, data: {detail: 'Expired'}} :
      {id: mock.role === 'customer' ? 2 : 4, role: mock.role, customer_id: mock.role === 'customer' ? 1 : null};
    else if (path === 'auth/signup') result = {id: 88, email: body.email, role: 'customer', customer_id: 88};
    else if (path === 'orders' && method === 'POST') result = {order_id: 99};
    else result = method === 'GET' ? (defaults[path] ?? []) : {ok: true};
    const status = result?.status || 200;
    return {ok: status >= 200 && status < 300, status, json: async () => result?.data ?? result};
  });
  return {...app, mock, requests: (path, method = 'POST') => mock.requests.filter(request => request.path === path && request.method === method)};
}

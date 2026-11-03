(() => {
  'use strict';
  // Credentials and tokens live in memory only. Refresh requires sign-in.
  let token = null, principal = null, currentView = 'menu', pendingSale = null;
  let sessionVersion = 0, viewVersion = 0;
  let stockRows = [];
  const byId = id => document.getElementById(id);
  const OPERATIONS = ['admin', 'staff'], REVIEWERS = ['admin', 'customer'];
  const ROLES = ['admin', 'staff', 'customer'];
  const VIEWS = {
    menu: ['Menu', ROLES], orders: ['Orders', ROLES], stock: ['Stock', OPERATIONS],
    recipes: ['Recipes', OPERATIONS], 'stock/movements': ['Stock movements', OPERATIONS],
    customers: ['Customers', OPERATIONS], loyalty: ['Points history', ROLES],
    reviews: ['My feedback', ROLES], 'reviews/shared': ['Others\u2019 feedback', ROLES],
    'analytics/sql': ['Sales insights', OPERATIONS],
    'analytics/mongo': ['Feedback insights', OPERATIONS],
    'profiles/me': ['My preferences', ['customer']], profiles: ['Customer preferences', ['admin']],
    accounts: ['Accounts', ['admin']]
  };
  class Cancelled extends Error {}
  const allowed = roles => principal !== null && roles.includes(principal.role);
  const values = form => Object.fromEntries(new FormData(form));
  const field = (form, name) => form.elements.namedItem(name);
  const labels = value => value.split(',').map(item => item.trim()).filter(Boolean);
  const titleCase = value => value[0].toUpperCase() + value.slice(1);
  // Backend sends money as preformatted strings like "5.00"; show them with a currency sign.
  const money = value => '$' + value;
  const formatDate = iso => { const date = new Date(iso); return isNaN(date) ? iso : date.toLocaleString(); };
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function message(text, error = false) {
    byId('message').textContent = text;
    byId('message').className = error ? 'error' : 'success';
  }
  function resetEditor(target) {
    const form = typeof target === 'string' ? byId(target) : target;
    // A control named "id" shadows form.id in browsers. Read the attribute instead.
    const id = form.getAttribute('id');
    form.reset();
    if (id === 'review-editor') {
      field(form, 'order_id').readOnly = false;
      byId('review-editor-title').textContent = 'Review a purchase';
    }
    if (id === 'menu-editor') byId('menu-editor-title').textContent = 'Add a menu item';
    if (id === 'customer-editor') byId('customer-editor-title').textContent = 'Add a customer record';
    if (id === 'stock-editor' || id === 'restock') resetStockChoices(form);
  }
  function setChoices(select, choices, placeholder) {
    select.replaceChildren();
    const prompt = node('option', placeholder); prompt.value = ''; select.append(prompt);
    for (const [id, name] of choices) {
      const option = node('option', name + ' (ID ' + id + ')'); option.value = String(id); select.append(option);
    }
    select.value = '';
  }
  function resetStockChoices(form) {
    setChoices(field(form, 'branch_id'), new Map(stockRows.map(row => [row.branch_id, row.branch])), 'Choose a branch');
    updateStockIngredients(form);
  }
  function updateStockIngredients(form) {
    const branchId = field(form, 'branch_id').value;
    const rows = stockRows.filter(row => String(row.branch_id) === branchId);
    const ingredient = field(form, 'ingredient_id');
    setChoices(ingredient, new Map(rows.map(row => [row.ingredient_id, row.ingredient])),
      branchId ? 'Choose an ingredient' : 'Choose a branch first');
    ingredient.disabled = !branchId || rows.length === 0;
    updateStockSelection(form);
  }
  function updateStockSelection(form) {
    const selected = stockRows.find(row => String(row.branch_id) === field(form, 'branch_id').value &&
      String(row.ingredient_id) === field(form, 'ingredient_id').value);
    if (form.getAttribute('id') === 'restock') {
      byId('restock-quantity-label').textContent = selected ? 'Quantity (' + selected.unit + ')' : 'Quantity';
      return;
    }
    field(form, 'expected_quantity').value = selected ? selected.quantity : '';
    field(form, 'quantity').value = selected ? selected.quantity : '';
    field(form, 'quantity').disabled = !selected;
    field(form, 'reason').value = ''; field(form, 'reason').disabled = !selected;
    byId('stock-editor-context').textContent = selected ? selected.branch + ' · ' + selected.ingredient +
      ' · Current: ' + selected.quantity + ' ' + selected.unit :
      'Choose a branch and ingredient here, or select Edit stock in the table below.';
    byId('stock-quantity-label').textContent = selected ? 'Correct quantity (' + selected.unit + ')' : 'Correct quantity';
  }
  function chooseStockRow(stock) {
    const form = byId('stock-editor');
    field(form, 'branch_id').value = String(stock.branch_id); updateStockIngredients(form);
    field(form, 'ingredient_id').value = String(stock.ingredient_id); updateStockSelection(form);
    focusEditor('stock-editor'); field(form, 'quantity').focus();
  }
  function validateStockQuantity(value, allowZero) {
    if (typeof value !== 'string' || !/^[0-9]{1,11}(?:\.[0-9]{1,3})?$/.test(value) ||
        (!allowZero && !/[1-9]/.test(value))) {
      throw new Error('Enter a ' + (allowZero ? 'nonnegative' : 'positive') + ' quantity using digits and up to three decimal places.');
    }
  }
  function installStockDecimalInput(input) {
    const editable = /^[0-9]{0,11}(?:\.[0-9]{0,3})?$/;
    let previous = input.value;
    const remember = () => { if (editable.test(input.value)) previous = input.value; };
    const proposed = text => input.value.slice(0, input.selectionStart) + text + input.value.slice(input.selectionEnd);
    input.addEventListener('focus', remember);
    input.addEventListener('beforeinput', event => {
      remember();
      if (event.data !== null && event.inputType.startsWith('insert') && !editable.test(proposed(event.data))) event.preventDefault();
    });
    input.addEventListener('paste', event => {
      remember();
      if (event.clipboardData && !editable.test(proposed(event.clipboardData.getData('text')))) event.preventDefault();
    });
    input.addEventListener('input', () => {
      if (editable.test(input.value)) previous = input.value;
      else input.value = previous;
    });
    input.form.addEventListener('reset', () => { previous = input.defaultValue; });
  }
  function updateVisibility() {
    document.querySelectorAll('[data-roles]').forEach(element => {
      const roleAllowed = allowed(element.dataset.roles.split(' '));
      const inView = !element.dataset.panel || element.dataset.panel.split(' ').includes(currentView);
      element.hidden = !(roleAllowed && inView);
    });
    const customerId = field(byId('profile-editor'), 'customer_id');
    customerId.required = allowed(['admin']) && currentView === 'profiles';
    customerId.disabled = !allowed(['admin']);
    document.querySelectorAll('[data-view]').forEach(button => {
      const active = button.dataset.view === currentView;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }
  function endSession() {
    token = null; principal = null; pendingSale = null; stockRows = [];
    sessionVersion++; viewVersion++; currentView = 'menu';
    byId('workspace').hidden = true; byId('login-card').hidden = false;
    byId('signup-card').hidden = true; byId('results').replaceChildren();
    document.querySelectorAll('form[id]').forEach(form => resetEditor(form));
    if (byId('confirmation').open) byId('confirmation').close('cancel');
    updateVisibility();
  }
  function applyPrincipal(user) {
    if (!ROLES.includes(user.role) || !Number.isInteger(user.id) || user.id <= 0) {
      endSession();
      throw new Error('This account cannot open a workspace. Contact an administrator.');
    }
    const changed = !principal || principal.id !== user.id || principal.role !== user.role;
    principal = user;
    if (changed) {
      sessionVersion++; viewVersion++; pendingSale = null; stockRows = [];
      byId('results').replaceChildren();
      document.querySelectorAll('#workspace form[id]').forEach(form => resetEditor(form));
      if (!allowed(VIEWS[currentView][1])) currentView = 'menu';
    }
    byId('workspace').hidden = false; byId('login-card').hidden = true; byId('signup-card').hidden = true;
    byId('welcome').textContent = titleCase(user.role) + ' workspace';
    byId('view-title').textContent = VIEWS[currentView][0];
    byId('role-description').textContent = {
      admin: 'Operations, account administration, reviews and customer preferences.',
      staff: 'Sales, stock, customer records and insights. Read feedback and add business replies.',
      customer: 'Your purchases, points, reviews and food preferences.'
    }[user.role];
    updateVisibility();
  }
  async function api(path, method = 'GET', body) {
    const requestToken = token, version = sessionVersion;
    const response = await fetch('/api/' + path, {
      method,
      headers: {'Content-Type': 'application/json', ...(requestToken ? {Authorization: 'Bearer ' + requestToken} : {})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    if (requestToken && (requestToken !== token || version !== sessionVersion)) throw new Cancelled();
    let data;
    try { data = await response.json(); }
    catch { throw new Error('The service returned an unexpected response. Try again.'); }
    if (requestToken && (requestToken !== token || version !== sessionVersion)) throw new Cancelled();
    if (!response.ok) {
      if (response.status === 401 && requestToken) {
        endSession();
        message('Your session has ended. Please sign in again.', true);
        throw new Cancelled();
      }
      // Validation responses can include submitted inputs. Display messages only.
      const detail = typeof data.detail === 'string' ? data.detail :
        Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(' ') : 'The request could not be completed.';
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return data;
  }
  async function syncPrincipal() {
    if (!token) throw new Cancelled();
    applyPrincipal(await api('auth/me'));
  }
  async function showError(error) {
    if (error instanceof Cancelled) return;
    if (error.status === 403 && token) {
      try { await syncPrincipal(); } catch (refreshError) { if (!(refreshError instanceof Cancelled)) message(refreshError.message, true); return; }
    }
    message(error.message || 'Unable to connect. Try again.', true);
  }
  async function run(roles, work) {
    const version = sessionVersion;
    await syncPrincipal();
    if (version !== sessionVersion) throw new Error('Your access has changed. Review the workspace and try again.');
    if (!allowed(roles)) throw new Error('This action is not allowed for your role.');
    return work();
  }
  function handleForm(form, roles, work) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const buttons = [...form.querySelectorAll('button')];
      if (form.dataset.busy) return;
      form.dataset.busy = 'true'; buttons.forEach(button => { button.disabled = true; });
      const submitted = values(form);
      try {
        if (roles) await run(roles, () => work(submitted, form));
        else await work(submitted, form);
      } catch (error) { await showError(error); }
      finally { delete form.dataset.busy; buttons.forEach(button => { button.disabled = false; }); }
    });
  }
  function action(label, work, className = 'secondary') {
    const button = node('button', label, className); button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await work(); } catch (error) { await showError(error); }
      finally { button.disabled = false; }
    });
    return button;
  }
  async function confirmAction(text, label = 'Confirm') {
    const dialog = byId('confirmation'), version = sessionVersion;
    if (dialog.open) return false;
    byId('confirmation-text').textContent = text;
    byId('confirm-action').textContent = label;
    dialog.returnValue = 'cancel';
    const result = new Promise(resolve => dialog.addEventListener('close',
      () => resolve(dialog.returnValue === 'confirm' && version === sessionVersion && token !== null), {once: true}));
    dialog.showModal();
    return result;
  }
  function focusEditor(id) {
    const form = byId(id);
    form.scrollIntoView({behavior: 'smooth', block: 'center'});
    form.querySelector('input:not([type="hidden"]):not([disabled]),textarea,select')?.focus();
  }
  function fillProfile(profile) {
    const form = byId('profile-editor');
    field(form, 'customer_id').value = profile.customer_id || '';
    field(form, 'dietary_preferences').value = (profile.dietary_preferences || []).join(', ');
    field(form, 'favourite_tags').value = (profile.favourite_tags || []).join(', ');
  }
  function table(data, target, rowActions) {
    if (!data.length) { target.textContent = 'No records yet.'; return; }
    const result = node('table'), head = node('thead'), headings = node('tr');
    const columns = [...new Set(data.flatMap(row => Object.keys(row)))];
    for (const key of columns) headings.append(node('th', key.replaceAll('_', ' ')));
    if (rowActions) headings.append(node('th', 'Actions'));
    head.append(headings); result.append(head);
    const body = node('tbody');
    for (const row of data) {
      const tr = node('tr');
      for (const key of columns) {
        const value = typeof row[key] === 'object' ? JSON.stringify(row[key]) : String(row[key] ?? '');
        tr.append(node('td', value));
      }
      if (rowActions) {
        const cell = node('td'); rowActions(row, cell); tr.append(cell);
      }
      body.append(tr);
    }
    result.append(body); target.append(result);
  }
  function render(data, target, rowActions) {
    target.replaceChildren();
    if (Array.isArray(data)) { table(data, target, rowActions); return; }
    for (const [name, value] of Object.entries(data)) {
      target.append(node('h4', name.replaceAll('_', ' ')));
      const section = node('div'); target.append(section);
      if (Array.isArray(value)) render(value, section);
      else section.append(node('pre', JSON.stringify(value, null, 2)));
    }
  }
  function renderAccounts(accounts, target) {
    render(accounts, target, (account, cell) => {
      const form = node('form', undefined, 'inline-form'), label = node('label', 'Role');
      const select = node('select'); select.name = 'role';
      select.setAttribute('aria-label', 'Role for ' + account.email);
      for (const role of ROLES) {
        const option = node('option', titleCase(role)); option.value = role;
        option.disabled = role === 'customer' && account.customer_id === null;
        option.selected = role === account.role; select.append(option);
      }
      label.append(select); form.append(label);
      const save = node('button', 'Save role'); save.type = 'submit'; form.append(save);
      handleForm(form, ['admin'], async data => {
        if (data.role === account.role) { message('This account already has that role.'); return; }
        if (!await confirmAction('Change ' + account.email + ' to ' + titleCase(data.role) + '? The account ID will stay the same.', 'Change role')) return;
        await api('accounts/' + account.id + '/role', 'PUT', {role: data.role});
        message('Account role updated.'); await loadView('accounts');
      });
      cell.append(form);
      cell.append(action(account.active ? 'Deactivate account' : 'Reactivate account', () => run(['admin'], async () => {
        const verb = account.active ? 'Deactivate' : 'Reactivate';
        if (!await confirmAction(verb + ' ' + account.email + '? Existing account IDs and purchase history will be preserved.', verb + ' account')) return;
        await api('accounts/' + account.id + '/status', 'PUT', {active: !account.active});
        message('Account ' + (account.active ? 'deactivated' : 'reactivated') + '.');
        await loadView('accounts');
      }), account.active ? 'danger' : 'secondary'));
    });
  }
  function buildReceipt(order) {
    const body = byId('receipt-body');
    body.replaceChildren();
    body.append(node('h2', 'Order ' + order.order_id));
    const branchName = order.branch?.name || ('Branch ' + order.branch?.id);
    body.append(node('p', formatDate(order.created_at) + ' · ' + branchName, 'muted'));
    const table = node('table'), head = node('thead'), headRow = node('tr');
    for (const heading of ['Dish', 'Qty', 'Unit price', 'Line total']) headRow.append(node('th', heading));
    head.append(headRow); table.append(head);
    const tbody = node('tbody');
    for (const line of order.lines || []) {
      const row = node('tr');
      row.append(node('td', line.name), node('td', String(line.quantity)),
        node('td', money(line.unit_price)), node('td', money(line.line_total)));
      tbody.append(row);
    }
    table.append(tbody); body.append(table);
    const totals = node('dl', undefined, 'totals');
    const line = (term, value) => {
      const row = node('div'); row.append(node('dt', term), node('dd', value)); return row;
    };
    totals.append(line('Subtotal', money(order.subtotal)));
    totals.append(line('Points discount', '-' + money(order.discount)));
    const grand = line('Total paid', money(order.total)); grand.className = 'grand-total';
    totals.append(grand);
    body.append(totals);
    body.append(node('p', 'Points earned: ' + order.points_earned + ' · Points redeemed: ' + order.points_redeemed, 'muted'));
  }
  async function showReceipt(orderId) {
    const dialog = byId('receipt'), version = sessionVersion;
    if (dialog.open) return;
    const order = await api('orders/' + orderId);
    if (version !== sessionVersion || token === null) return;
    buildReceipt(order);
    dialog.showModal();
  }
  async function fillOwnOrderOptions() {
    // Suggest the customer's own order ids in the review editor datalist.
    const list = byId('own-order-ids');
    if (!list) return;
    try {
      const orders = await api('orders');
      list.replaceChildren();
      for (const order of orders) {
        const option = node('option'); option.value = String(order.order_id);
        option.label = money(order.total) + ' \u00b7 ' + formatDate(order.created_at);
        list.append(option);
      }
    } catch { /* suggestions are optional; ignore load failures */ }
  }
  function renderOrders(orders, target) {
    target.replaceChildren();
    if (!orders.length) { target.textContent = 'No purchases yet.'; return; }
    for (const order of orders) {
      const card = node('article', undefined, 'review-record');
      card.append(node('h4', 'Order ' + order.order_id + ' · ' + money(order.total)));
      card.append(node('p', formatDate(order.created_at), 'muted'));
      const controls = node('div', undefined, 'actions');
      controls.append(action('View receipt', () => showReceipt(order.order_id)));
      card.append(controls);
      target.append(card);
    }
  }
  function renderReviews(reviews, target) {
    target.replaceChildren();
    if (!reviews.length) { target.textContent = 'No reviews yet.'; return; }
    for (const review of reviews) {
      const card = node('article', undefined, 'review-record');
      card.append(node('h4', 'Order ' + review.order_id + ' · ' + review.rating + '/5'));
      card.append(node('p', review.text));
      card.append(node('p', 'Tags: ' + (review.tags || []).join(', '), 'muted'));
      if (Object.keys(review.category_ratings || {}).length)
        card.append(node('p', Object.entries(review.category_ratings).map(([name, rating]) => name + ': ' + rating + '/5').join(' · '), 'muted'));
      if (allowed(REVIEWERS)) {
        const controls = node('div', undefined, 'actions');
        controls.append(action('Edit review', () => {
          const form = byId('review-editor');
          field(form, 'editing').value = 'true';
          field(form, 'order_id').value = review.order_id; field(form, 'order_id').readOnly = true;
          field(form, 'rating').value = review.rating; field(form, 'text').value = review.text;
          field(form, 'tags').value = (review.tags || []).join(', ');
          for (const category of ['food', 'service', 'value']) field(form, category).value = review.category_ratings?.[category] || '';
          byId('review-editor-title').textContent = 'Edit review for order ' + review.order_id; focusEditor('review-editor');
        }));
        controls.append(action('Delete review', () => run(REVIEWERS, async () => {
          if (!await confirmAction('Delete the review and business replies for order ' + review.order_id + '? This cannot be undone.', 'Delete review')) return;
          await api('reviews/' + review.order_id, 'DELETE');
          resetEditor('review-editor'); message('Review deleted.'); await loadView('reviews');
        }), 'danger'));
        card.append(controls);
      }
      for (const [index, reply] of (review.replies || []).entries()) {
        const section = node('section', undefined, 'reply');
        section.append(node('strong', 'Business reply'), node('p', reply.text));
        if (allowed(['admin'])) {
          const edit = node('form'), label = node('label', 'Edit business reply'), text = node('textarea');
          text.name = 'text'; text.maxLength = 1000; text.required = true; text.value = reply.text; label.append(text);
          const save = node('button', 'Save reply'); save.type = 'submit'; edit.append(label, save); edit.hidden = true;
          handleForm(edit, ['admin'], async data => {
            await api('reviews/' + review.order_id + '/replies/' + index, 'PUT', {text: data.text});
            message('Business reply updated.'); await loadView('reviews');
          });
          const controls = node('div', undefined, 'actions');
          controls.append(action('Edit reply', () => { edit.hidden = !edit.hidden; if (!edit.hidden) text.focus(); }));
          controls.append(action('Delete reply', () => run(['admin'], async () => {
            if (!await confirmAction('Delete this business reply? This cannot be undone.', 'Delete reply')) return;
            await api('reviews/' + review.order_id + '/replies/' + index, 'DELETE');
            message('Business reply deleted.'); await loadView('reviews');
          }), 'danger'));
          section.append(controls, edit);
        }
        card.append(section);
      }
      if (allowed(OPERATIONS)) {
        const form = node('form', undefined, 'reply-form'), label = node('label', 'Business reply');
        const text = node('textarea'); text.name = 'text'; text.required = true; text.maxLength = 1000;
        label.append(text);
        const submit = node('button', 'Add reply'); submit.type = 'submit';
        if ((review.replies || []).length >= 20) {
          submit.disabled = true; text.disabled = true;
          form.append(node('p', 'This review has reached the 20-reply limit.', 'muted'));
        }
        form.append(label, submit);
        handleForm(form, OPERATIONS, async data => {
          await api('reviews/' + review.order_id + '/replies', 'POST', {text: data.text});
          message('Business reply added.'); await loadView('reviews');
        });
        card.append(form);
      }
      target.append(card);
    }
  }
  function sharedReviewCard(review) {
    // Shared reviews are anonymous: no order id, customer id or author shown.
    const card = node('article', undefined, 'review-record');
    card.append(node('h4', review.rating + '/5'));
    card.append(node('p', review.text));
    if ((review.tags || []).length) card.append(node('p', 'Tags: ' + review.tags.join(', '), 'muted'));
    if (Object.keys(review.category_ratings || {}).length)
      card.append(node('p', Object.entries(review.category_ratings).map(([name, rating]) => name + ': ' + rating + '/5').join(' \u00b7 '), 'muted'));
    for (const reply of review.replies || []) {
      const section = node('section', undefined, 'reply');
      section.append(node('strong', 'Business reply'), node('p', reply.text));
      card.append(section);
    }
    return card;
  }
  async function renderSharedReviews(initialReviews, target) {
    target.replaceChildren();
    // Branch filter: labels come from GET /api/branches; "All branches" clears the filter.
    let branches = [];
    try { branches = await api('branches'); } catch { branches = []; }
    const picker = node('label', 'Branch');
    const select = node('select'); select.id = 'shared-branch';
    select.setAttribute('aria-label', 'Filter shared feedback by branch');
    const all = node('option', 'All branches'); all.value = ''; select.append(all);
    for (const branch of branches) {
      const option = node('option', branch.name); option.value = String(branch.id); select.append(option);
    }
    picker.append(select); target.append(picker);
    const list = node('div'); target.append(list);
    const paint = reviews => {
      list.replaceChildren();
      if (!reviews.length) { list.append(node('p', 'No shared feedback yet.', 'muted')); return; }
      for (const review of reviews) list.append(sharedReviewCard(review));
    };
    paint(initialReviews);
    select.addEventListener('change', async () => {
      const version = sessionVersion;
      list.replaceChildren(node('p', 'Loading\u2026', 'loading'));
      try {
        const reviews = await api('reviews/shared' + (select.value ? '?branch_id=' + select.value : ''));
        if (version !== sessionVersion) return;
        paint(reviews);
      } catch (error) {
        if (version !== sessionVersion) return;
        list.replaceChildren(node('p', 'Unable to load shared feedback. Try again.'));
        await showError(error);
      }
    });
  }
  async function loadView(requested = currentView) {
    let request = null, version = sessionVersion;
    try {
      await syncPrincipal();
      const path = VIEWS[requested] && allowed(VIEWS[requested][1]) ? requested : 'menu';
      request = ++viewVersion; version = sessionVersion;
      currentView = path; updateVisibility();
      byId('view-title').textContent = VIEWS[path][0];
      byId('results').replaceChildren(node('p', 'Loading…', 'loading'));
      const data = await api(path);
      if (request !== viewVersion || version !== sessionVersion) return;
      const target = byId('results');
      if (path === 'reviews') { renderReviews(data, target); if (allowed(['customer'])) fillOwnOrderOptions(); }
      else if (path === 'reviews/shared') await renderSharedReviews(data, target);
      else if (path === 'orders') renderOrders(data, target);
      else if (path === 'accounts') renderAccounts(data, target);
      else if (path === 'stock') {
        stockRows = data;
        resetEditor('restock'); resetEditor('stock-editor');
        render(data, target, allowed(['admin']) ? (stock, cell) =>
          cell.append(action('Edit stock', () => run(['admin'], () => chooseStockRow(stock)))) : undefined);
      }
      else if (path === 'profiles/me') {
        target.replaceChildren(
          node('p', 'Points balance: ' + (data.points ?? 0)),
          node('p', 'Dietary preferences: ' + ((data.dietary_preferences || []).join(', ') || 'None saved')),
          node('p', 'Favourite tags: ' + ((data.favourite_tags || []).join(', ') || 'None saved')));
        fillProfile(data);
      }
      else if (path === 'profiles') {
        resetEditor('profile-editor');
        render(data, target, (profile, cell) => {
          const controls = node('div', undefined, 'actions');
          controls.append(action('Edit preferences', () => { fillProfile(profile); focusEditor('profile-editor'); }));
          controls.append(action('Delete preferences', () => run(['admin'], async () => {
            if (!await confirmAction('Delete preferences for customer ' + profile.customer_id + '? Purchases and the customer account will remain.', 'Delete preferences')) return;
            await api('profiles/' + profile.customer_id, 'DELETE'); message('Preferences deleted.'); await loadView('profiles');
          }), 'danger'));
          cell.append(controls);
        });
      } else if (path === 'menu' && allowed(OPERATIONS)) {
        render(data, target, (item, cell) => {
          const controls = node('div', undefined, 'actions');
          controls.append(action('Edit item', () => {
            const form = byId('menu-editor');
            for (const name of ['id', 'name', 'price']) field(form, name).value = item[name];
            field(form, 'active').checked = item.active;
            byId('menu-editor-title').textContent = 'Edit menu item ' + item.id; focusEditor('menu-editor');
          }));
          controls.append(action('Delete item', () => run(OPERATIONS, async () => {
            if (!await confirmAction('Delete ' + item.name + '? Items used in past sales must be marked unavailable instead.', 'Delete item')) return;
            await api('menu/' + item.id, 'DELETE'); resetEditor('menu-editor');
            message('Menu item deleted.'); await loadView('menu');
          }), 'danger'));
          cell.append(controls);
        });
      } else if (path === 'customers') {
        render(data, target, (customer, cell) => cell.append(action('Edit customer', () => {
          const form = byId('customer-editor');
          for (const name of ['id', 'name', 'email']) field(form, name).value = customer[name];
          byId('customer-editor-title').textContent = 'Edit customer ' + customer.id; focusEditor('customer-editor');
        })));
      } else render(data, target);
    } catch (error) {
      if ((request !== null && request !== viewVersion) || version !== sessionVersion) return;
      if (!(error instanceof Cancelled)) byId('results').replaceChildren(node('p', 'Unable to load records. Use Refresh to try again.'));
      await showError(error);
    }
  }
  byId('show-signup').onclick = () => {
    byId('login').reset(); byId('login-card').hidden = true; byId('signup-card').hidden = false;
    message(''); field(byId('signup'), 'name').focus();
  };
  byId('show-login').onclick = () => {
    byId('signup').reset(); byId('signup-card').hidden = true; byId('login-card').hidden = false;
    message(''); field(byId('login'), 'email').focus();
  };
  handleForm(byId('signup'), null, async (data, form) => {
    if (data.password !== data.confirm_password) throw new Error('Passwords do not match.');
    const result = await api('auth/signup', 'POST', {name: data.name, email: data.email, password: data.password});
    form.reset(); byId('signup-card').hidden = true; byId('login-card').hidden = false;
    field(byId('login'), 'email').value = result.email;
    field(byId('login'), 'password').value = ''; field(byId('login'), 'password').focus();
    message('Your customer account is ready. Sign in to continue.');
  });
  handleForm(byId('login'), null, async (data, form) => {
    const result = await api('auth/login', 'POST', {email: data.email, password: data.password});
    form.reset(); token = result.access_token;
    try { await syncPrincipal(); } catch (error) { endSession(); throw error; }
    message('Signed in.'); await loadView('menu');
  });
  byId('logout').onclick = () => { endSession(); message('Signed out.'); };
  byId('refresh-view').onclick = () => loadView();
  document.querySelectorAll('[data-view]').forEach(button => { button.onclick = () => loadView(button.dataset.view); });
  document.querySelectorAll('[data-reset]').forEach(button => { button.onclick = () => resetEditor(button.dataset.reset); });
  document.querySelectorAll('[data-stock-quantity]').forEach(installStockDecimalInput);
  for (const id of ['restock', 'stock-editor']) {
    const form = byId(id);
    field(form, 'branch_id').addEventListener('change', () => updateStockIngredients(form));
    field(form, 'ingredient_id').addEventListener('change', () => updateStockSelection(form));
  }
  handleForm(byId('menu-editor'), OPERATIONS, async (data, form) => {
    await api(data.id ? 'menu/' + data.id : 'menu', data.id ? 'PUT' : 'POST',
      {name: data.name, price: data.price, active: field(form, 'active').checked});
    resetEditor(form); message('Menu item saved.'); await loadView('menu');
  });
  handleForm(byId('customer-editor'), OPERATIONS, async (data, form) => {
    await api(data.id ? 'customers/' + data.id : 'customers', data.id ? 'PUT' : 'POST', {name: data.name, email: data.email});
    resetEditor(form); message('Customer record saved.'); await loadView('customers');
  });
  handleForm(byId('checkout'), OPERATIONS, async data => {
    const cart = {branch_id: Number(data.branch_id), customer_id: Number(data.customer_id), redeem_points: Number(data.redeem_points),
      lines: [{menu_item_id: Number(data.menu_item_id), quantity: Number(data.quantity)}]};
    const signature = JSON.stringify(cart);
    if (!pendingSale || pendingSale.signature !== signature) pendingSale = {signature, key: crypto.randomUUID()};
    const result = await api('orders', 'POST', {...cart, request_key: pendingSale.key});
    pendingSale = null; message('Sale completed. Order ' + result.order_id + '.'); await loadView('orders');
  });
  handleForm(byId('restock'), OPERATIONS, async data => {
    if (!stockRows.some(row => String(row.branch_id) === data.branch_id && String(row.ingredient_id) === data.ingredient_id))
      throw new Error('Choose a branch and ingredient from the stock list.');
    validateStockQuantity(data.quantity, false);
    await api('stock/receipts', 'POST', {branch_id: Number(data.branch_id), ingredient_id: Number(data.ingredient_id), quantity: data.quantity, note: data.note});
    message('Receipt recorded.'); await loadView('stock');
  });
  handleForm(byId('stock-editor'), ['admin'], async data => {
    if (!data.branch_id || !data.ingredient_id || data.expected_quantity === '') throw new Error('Choose a branch and ingredient first.');
    validateStockQuantity(data.quantity, true);
    if (!data.reason.trim()) throw new Error('Enter a reason for the stock correction.');
    if (!await confirmAction('Set stock for branch ' + data.branch_id + ', ingredient ' + data.ingredient_id +
        ' from ' + data.expected_quantity + ' to ' + data.quantity + '? This correction will be recorded in stock movements.', 'Save correction')) return;
    await api('stock/' + data.branch_id + '/' + data.ingredient_id, 'PUT',
      {quantity: data.quantity, expected_quantity: data.expected_quantity, reason: data.reason.trim()});
    resetEditor('stock-editor'); message('Stock quantity corrected. The adjustment is recorded in stock movements.'); await loadView('stock');
  });
  handleForm(byId('review-editor'), REVIEWERS, async (data, form) => {
    const category_ratings = {};
    for (const category of ['food', 'service', 'value']) if (data[category]) category_ratings[category] = Number(data[category]);
    await api(data.editing ? 'reviews/' + data.order_id : 'reviews', data.editing ? 'PUT' : 'POST',
      {order_id: Number(data.order_id), rating: Number(data.rating), text: data.text, tags: labels(data.tags), category_ratings});
    resetEditor(form); message('Review saved.'); await loadView('reviews');
  });
  handleForm(byId('profile-editor'), REVIEWERS, async data => {
    const path = allowed(['admin']) ? 'profiles/' + data.customer_id : 'profiles/me';
    await api(path, 'PUT', {dietary_preferences: labels(data.dietary_preferences), favourite_tags: labels(data.favourite_tags)});
    message('Preferences saved.'); await loadView(allowed(['admin']) ? 'profiles' : 'profiles/me');
  });
  handleForm(byId('account-editor'), ['admin'], async (data, form) => {
    if (data.password !== data.confirm_password) throw new Error('Passwords do not match.');
    if (!await confirmAction('Create a new ' + titleCase(data.role) + ' account for ' + data.email + '?', 'Create account')) return;
    await api('accounts', 'POST', {email: data.email, password: data.password, role: data.role});
    form.reset(); message('Account created. The new user can sign in.'); await loadView('accounts');
  });
  updateVisibility();
  api('health').then(status => {
    byId('health').textContent = 'SQL: ' + status.sql + ' (' + status.sql_dialect + ') · MongoDB: ' + status.mongo;
  }).catch(() => { byId('health').textContent = 'Service unavailable'; });
})();

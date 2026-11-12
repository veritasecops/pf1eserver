(() => {
  const bag = document.getElementById('character-backpack');
  if (!bag) return;
  const opener = document.getElementById('open-backpack');
  const sheet = document.getElementById('deluxe-form');
  const form = document.getElementById('backpack-add');
  const error = document.getElementById('backpack-error');
  const list = document.getElementById('backpack-list');
  const status = document.getElementById('backpack-status');
  const search = document.getElementById('backpack-search');
  const category = document.getElementById('backpack-category');
  const panel = document.getElementById('backpack-results');
  const tabs = [...bag.querySelectorAll('[data-backpack-tab]')];
  let activeTab = tabs[0];
  let items = JSON.parse(document.getElementById('backpack-items').textContent);
  const submit = form.querySelector('[type="submit"]');
  let pending = null;
  let busy = false;

  function groupItems() {
    const group = activeTab.dataset.backpackTab;
    return items.filter(item => group === 'all' || item.catalog?.kind === group);
  }

  function refreshCategories() {
    const selected = category.value;
    const labels = [...new Set(groupItems().flatMap(item => item.catalog?.categories || []))].sort();
    category.replaceChildren(new Option('All Categories', ''), ...labels.map(label => new Option(label, label)));
    category.value = labels.includes(selected) ? selected : '';
    window.PathkeeperDropdown?.refresh(category);
  }

  function render() {
    const gold = copper => (copper / 100).toLocaleString(undefined, {maximumFractionDigits: 2}) + ' gp';
    const query = search.value.trim().toLocaleLowerCase();
    const matches = groupItems().filter(item => item.name.toLocaleLowerCase().includes(query)
      && (!category.value || item.catalog?.categories?.includes(category.value)))
      .sort((a, b) => a.name.localeCompare(b.name));
    status.textContent = `${matches.length} matching ${matches.length === 1 ? 'entry' : 'entries'}`;
    const body = list.querySelector('tbody');
    body.replaceChildren(...matches.map(item => {
      const row = document.createElement('tr');
      const nameCell = document.createElement('th');
      nameCell.scope = 'row';
      row.append(nameCell);
      const catalog = item.catalog;
      const url = window.PathkeeperDropdown?.referenceURL(catalog?.url);
      const name = document.createElement(url ? 'a' : 'strong');
      name.textContent = item.name;
      if (url) {
        name.href = url;
        name.target = '_blank';
        name.rel = 'noopener noreferrer';
      }
      nameCell.append(name);
      const note = document.createElement('button');
      note.type = 'button';
      note.className = 'button small';
      note.textContent = item.notes ? 'Edit Note' : 'Add Note';
      note.addEventListener('click', () => editNote(item));
      nameCell.append(note);
      if (item.notes) {
        const text = document.createElement('span');
        text.className = 'secondary-text';
        text.textContent = item.notes;
        nameCell.append(text);
      }
      if (catalog) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Catalog Details';
        details.append(summary);
        const weight = catalog.weight_text || (catalog.weight == null ? '' : `${catalog.weight} lb.`);
        for (const value of [
          [catalog.group, ...(catalog.categories || [])].filter(Boolean).join(' · '),
          weight && `Weight per item: ${weight}`,
          catalog.cost_text && `Published price: ${catalog.cost_text}`,
          catalog.details, catalog.special, catalog.notes, catalog.source,
        ].filter(Boolean)) {
          const line = document.createElement('p');
          line.className = 'secondary-text';
          line.textContent = value;
          details.append(line);
        }
        nameCell.append(details);
      }
      for (const value of [item.quantity, gold(item.unit_cp), gold(item.unit_cp * item.quantity)]) {
        row.insertCell().textContent = value;
      }
      const actions = document.createElement('div');
      actions.className = 'ds-item-actions';
      for (const [action, symbol, label] of [['remove', '−', 'Remove'], ['sell', '$', 'Sell']]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'button ds-item-action';
        button.textContent = symbol;
        button.title = label;
        button.setAttribute('aria-label', `${label} ${item.name}`);
        Object.assign(button.dataset, {disposeEquipment: action, kind: 'backpack', row: item.id,
          name: item.name, quantity: item.quantity, unitCp: item.unit_cp});
        actions.append(button);
      }
      row.insertCell().append(actions);
      return row;
    }));
    if (!matches.length) {
      const message = body.insertRow().insertCell();
      message.colSpan = 5;
      message.textContent = items.length ? 'No matching items in this view.' : 'Your backpack is empty.';
    }
  }

  function selectTab(tab) {
    activeTab = tab;
    for (const button of tabs) {
      button.tabIndex = button === tab ? 0 : -1;
      button.setAttribute('aria-selected', String(button === tab));
    }
    panel.setAttribute('aria-labelledby', tab.id);
    category.value = '';
    refreshCategories();
    render();
  }

  for (const tab of tabs) {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', event => {
      const index = tabs.indexOf(tab);
      const destinations = {Home: 0, End: tabs.length - 1,
        ArrowLeft: (index + tabs.length - 1) % tabs.length, ArrowRight: (index + 1) % tabs.length};
      if (!Object.hasOwn(destinations, event.key)) return;
      event.preventDefault();
      const destination = tabs[destinations[event.key]];
      selectTab(destination);
      destination.focus();
    });
  }
  search.addEventListener('input', render);
  category.addEventListener('change', render);
  refreshCategories();
  render();
  bag.addEventListener('backpackchange', event => {
    items = event.detail;
    refreshCategories();
    render();
  });
  let trigger = opener;
  for (const button of [opener, ...document.querySelectorAll('[data-open-backpack]')]) {
    button.addEventListener('click', () => {
      trigger = button;
      items = items.map(item => {
        const note = sheet.elements.namedItem(`gear.${item.gear_row}.notes`);
        return note ? {...item, notes: note.value} : item;
      });
      render();
      bag.showModal();
    });
  }
  bag.addEventListener('close', () => trigger.focus());
  bag.querySelector('[data-close-backpack]').addEventListener('click', () => { if (!busy) bag.close(); });
  bag.addEventListener('cancel', event => { if (busy) event.preventDefault(); });

  async function editNote(item) {
    if (busy) return;
    const notes = window.prompt(`Note for ${item.name}`, item.notes || '');
    if (notes === null) return;
    busy = true;
    submit.disabled = true;
    error.hidden = true;
    try {
      await window.PathkeeperSheet.flush();
      const body = new FormData();
      for (const [key, value] of Object.entries({action: 'note', item_id: item.id, notes,
        version: sheet.elements.namedItem('version').value, csrf: sheet.elements.namedItem('csrf').value})) {
        body.set(key, value);
      }
      const response = await fetch(bag.dataset.endpoint, {method: 'POST', body, headers: {Accept: 'application/json'}});
      if (response.redirected) throw new Error('Sign in again before editing a note.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'The note could not be saved.');
      window.PathkeeperSheet.applyPurchase(result);
      items = result.backpack;
      render();
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      busy = false;
      submit.disabled = false;
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const body = new FormData(form);
    const fingerprint = JSON.stringify([...body]);
    if (pending?.fingerprint !== fingerprint) {
      pending = {fingerprint, id: Array.from(crypto.getRandomValues(new Uint8Array(16)),
        byte => byte.toString(16).padStart(2, '0')).join('')};
    }
    busy = true;
    submit.disabled = true;
    error.hidden = true;
    const controller = new AbortController();
    let timeout;
    try {
      await window.PathkeeperSheet.flush();
      body.set('item_id', pending.id);
      body.set('version', sheet.elements.namedItem('version').value);
      body.set('csrf', sheet.elements.namedItem('csrf').value);
      timeout = setTimeout(() => controller.abort(), 15000);
      const response = await fetch(bag.dataset.endpoint, {method: 'POST', body, signal: controller.signal,
        headers: {Accept: 'application/json'}});
      if (response.redirected) throw new Error('Sign in again before adding a backpack item.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'The backpack item could not be saved.');
      window.PathkeeperSheet.applyPurchase(result);
      items = result.backpack;
      search.value = '';
      selectTab(tabs[0]);
      pending = null;
      form.reset();
      form.elements.namedItem('name').focus();
    } catch (failure) {
      error.textContent = failure.name === 'AbortError' || failure instanceof TypeError
        ? 'The response was lost. Retry the same entry or reload the sheet.' : failure.message;
      error.hidden = false;
    } finally {
      clearTimeout(timeout);
      busy = false;
      submit.disabled = false;
    }
  });
})();

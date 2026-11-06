(() => {
  const bag = document.getElementById('character-backpack');
  if (!bag) return;
  const opener = document.getElementById('open-backpack');
  const sheet = document.getElementById('deluxe-form');
  const form = document.getElementById('backpack-add');
  const error = document.getElementById('backpack-error');
  const list = document.getElementById('backpack-list');
  const empty = document.getElementById('backpack-empty');
  const submit = form.querySelector('[type="submit"]');
  let pending = null;
  let busy = false;

  function render(items) {
    const gold = copper => (copper / 100).toLocaleString(undefined, {maximumFractionDigits: 2}) + ' gp';
    empty.hidden = items.length > 0;
    list.hidden = items.length === 0;
    list.querySelector('tbody').replaceChildren(...items.map(item => {
      const row = document.createElement('tr');
      const nameCell = row.insertCell();
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
      if (catalog) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Catalog details';
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
  }

  render(JSON.parse(document.getElementById('backpack-items').textContent));
  bag.addEventListener('backpackchange', event => render(event.detail));
  opener.addEventListener('click', () => bag.showModal());
  bag.querySelector('[data-close-backpack]').addEventListener('click', () => { if (!busy) bag.close(); });
  bag.addEventListener('cancel', event => { if (busy) event.preventDefault(); });

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
      render(result.backpack);
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

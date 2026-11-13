(() => {
  const sheet = document.getElementById('deluxe-form');
  const dialog = document.getElementById('sheet-class-ability-picker');
  if (!sheet || !dialog) return;
  const search = dialog.querySelector('[data-class-ability-search]');
  const results = dialog.querySelector('[data-class-ability-results]');
  const status = dialog.querySelector('[data-class-ability-status]');
  const error = dialog.querySelector('[data-class-ability-error]');
  const sheetError = document.getElementById('class-ability-error');
  const more = dialog.querySelector('[data-class-ability-more]');
  let catalog, busy = false, limit = 50;

  async function update(id, remove) {
    if (busy) return;
    busy = true;
    error.hidden = sheetError.hidden = true;
    render();
    try {
      await window.PathkeeperSheet.flush();
      const body = new FormData();
      body.set('csrf', sheet.elements.csrf.value);
      body.set('version', sheet.elements.version.value);
      body.set('ability', id);
      const response = await fetch(dialog.dataset.endpoint + (remove ? '/remove' : ''), {
        method: 'POST', body, headers: {Accept: 'application/json'},
      });
      if (response.redirected) throw new Error('Sign in again before changing class abilities.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Unable to update class abilities.');
      window.history.replaceState(null, '', result.location);
      window.location.reload();
    } catch (failure) {
      const target = remove ? sheetError : error;
      target.textContent = failure.message;
      target.hidden = false;
    } finally { busy = false; render(); }
  }

  function render() {
    results.replaceChildren();
    if (!catalog) { status.textContent = 'Loading abilities…'; more.hidden = true; return; }
    const query = search.value.trim().toLowerCase();
    const matches = catalog.options.filter(item => (item.name + ' ' + item.gains.map(gain => gain.name).join(' ')).toLowerCase().includes(query));
    status.textContent = matches.length ? `${matches.length} matching class abilities` : 'No matching class abilities.';
    for (const item of matches.slice(0, limit)) {
      const row = results.insertRow();
      const label = document.createElement(item.url ? 'a' : 'span');
      label.textContent = item.name;
      if (item.url) { label.href = item.url; label.target = '_blank'; label.rel = 'noopener noreferrer'; }
      row.insertCell().append(label);
      row.insertCell().textContent = item.gains.map(gain => gain.level).join(', ');
      const add = document.createElement('button');
      add.type = 'button'; add.className = 'button small';
      add.textContent = item.owned ? 'On sheet' : 'Add';
      add.disabled = busy || item.owned;
      add.setAttribute('aria-label', `Add ${item.name}`);
      add.addEventListener('click', () => update(item.id, false));
      row.insertCell().append(add);
    }
    more.hidden = matches.length <= limit;
  }

  document.getElementById('add-class-ability').addEventListener('click', async () => {
    catalog = null; search.value = ''; limit = 50; error.hidden = true;
    dialog.showModal(); search.focus(); render();
    try {
      await window.PathkeeperSheet.flush();
      const response = await fetch(dialog.dataset.endpoint, {headers: {Accept: 'application/json'}});
      if (response.redirected) throw new Error('Sign in again to load class abilities.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to load class abilities.');
      catalog = data; render();
    } catch (failure) { status.textContent = ''; error.textContent = failure.message; error.hidden = false; }
  });
  for (const button of sheet.querySelectorAll('[data-remove-class-ability]')) {
    button.addEventListener('click', async () => {
      if (busy || !window.confirm(button.getAttribute('aria-label') + '?')) return;
      button.disabled = true;
      try { await update(button.dataset.removeClassAbility, true); }
      finally { button.disabled = false; }
    });
  }
  for (const button of dialog.querySelectorAll('[data-class-ability-close]')) button.addEventListener('click', () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  search.addEventListener('input', () => { limit = 50; render(); });
  more.addEventListener('click', () => { limit += 50; render(); });
})();

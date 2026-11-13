(() => {
  const dialog = document.getElementById('sheet-feature-picker');
  if (!dialog) return;
  const sheet = document.getElementById('deluxe-form');
  const form = document.getElementById('sheet-feature-form');
  const launcher = document.getElementById('add-sheet-feature');
  const search = form.querySelector('[data-feature-search]');
  const target = form.elements.target;
  const results = form.querySelector('[data-feature-results]');
  const more = form.querySelector('[data-feature-more]');
  const status = form.querySelector('[data-feature-status]');
  const selection = form.querySelector('[data-feature-selection]');
  const error = form.querySelector('[data-feature-error]');
  const submit = form.querySelector('[type=submit]');
  let catalog, selected, busy = false, limit = 50;

  function render() {
    const query = search.value.trim().toLowerCase();
    const matches = (catalog?.options.feat || []).filter(item => item.name.toLowerCase().includes(query));
    status.textContent = catalog ? `${matches.length} matching entries` : 'Loading entries…';
    results.replaceChildren();
    for (const item of matches.slice(0, limit)) {
      const row = results.insertRow();
      const label = document.createElement(item.url ? 'a' : 'span');
      label.textContent = item.name;
      if (item.url) {
        label.href = item.url;
        label.target = '_blank';
        label.rel = 'noopener noreferrer';
      }
      row.insertCell().append(label);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'button small';
      button.textContent = item === selected ? 'Selected' : 'Choose';
      button.disabled = item === selected;
      button.setAttribute('aria-label', `Choose ${item.name}`);
      button.addEventListener('click', () => {
        choose(item);
        (item.choice ? target : submit).focus();
      });
      row.insertCell().append(button);
    }
    more.hidden = matches.length <= limit;
  }

  function choose(item) {
    selected = item;
    error.hidden = true;
    selection.textContent = item ? `Selected: ${item.name}` : 'No entry selected.';
    const kind = item?.choice;
    target.replaceChildren(new Option(kind ? `Choose a ${kind}` : '', ''),
      ...(item?.targets || []).map(key => new Option(catalog.targets[kind][key], key)));
    target.disabled = !kind;
    target.required = Boolean(kind);
    target.closest('[data-feature-target]').hidden = !kind;
    window.PathkeeperDropdown?.refresh(target);
    submit.disabled = !item || busy;
    render();
  }

  const removeError = document.getElementById('sheet-feat-remove-error');
  for (const button of sheet.querySelectorAll('[data-remove-feat]')) {
    button.addEventListener('click', async () => {
      if (busy || !window.confirm(button.getAttribute('aria-label') + '?')) return;
      busy = true;
      button.disabled = true;
      removeError.hidden = true;
      try {
        await window.PathkeeperSheet.flush();
        const body = new FormData();
        body.set('row', button.dataset.removeFeat);
        body.set('csrf', sheet.elements.csrf.value);
        body.set('version', sheet.elements.version.value);
        const response = await fetch(dialog.dataset.endpoint + '/remove', {
          method: 'POST', body, headers: {Accept: 'application/json'},
        });
        if (response.redirected) throw new Error('Sign in again before removing a feat.');
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Unable to remove the feat.');
        window.history.replaceState(null, '', result.location);
        window.location.reload();
      } catch (failure) {
        removeError.textContent = failure.message;
        removeError.hidden = false;
      } finally {
        busy = false;
        button.disabled = false;
      }
    });
  }

  for (const input of sheet.querySelectorAll('[data-class-ability-input]')) {
    input.addEventListener('input', () => {
      const field = sheet.elements.namedItem(`feature.${input.dataset.classAbilityInput}`);
      field.value = `${input.dataset.abilityLabel}: ${input.value}`;
    });
  }

  launcher.addEventListener('click', async () => {
    dialog.showModal();
    catalog = null;
    search.value = '';
    limit = 50;
    choose(null);
    try {
      await window.PathkeeperSheet.flush();
      const response = await fetch(dialog.dataset.endpoint, {headers: {Accept: 'application/json'}});
      if (!response.ok || response.redirected) throw new Error('Unable to load feats and abilities.');
      catalog = await response.json();
      render();
    } catch (failure) {
      status.textContent = failure.message;
    }
  });
  form.querySelectorAll('[data-feature-close]').forEach(button => button.addEventListener('click', () => {
    if (!busy) dialog.close();
  }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  search.addEventListener('input', () => { limit = 50; render(); });
  more.addEventListener('click', () => { limit += 50; render(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selected || busy) return;
    busy = true;
    const body = new FormData(form);
    body.set('kind', 'feat');
    body.set('feature', selected.name);
    submit.disabled = true;
    error.hidden = true;
    try {
      await window.PathkeeperSheet.flush();
      body.set('csrf', sheet.elements.csrf.value);
      body.set('version', sheet.elements.version.value);
      const response = await fetch(dialog.dataset.endpoint, {method: 'POST', body, headers: {Accept: 'application/json'}});
      if (response.redirected) throw new Error('Sign in again before adding an entry.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Unable to add the entry.');
      window.history.replaceState(null, '', result.location);
      window.location.reload();
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      busy = false;
      submit.disabled = false;
    }
  });
})();

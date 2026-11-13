(() => {
  const sheet = document.getElementById('deluxe-form');
  const dialog = document.getElementById('sheet-spell-picker');
  if (!sheet || !dialog) return;
  const search = dialog.querySelector('[data-spell-search]');
  const classes = dialog.querySelector('[data-spell-class]');
  const results = dialog.querySelector('[data-spell-results]');
  const status = dialog.querySelector('[data-spell-status]');
  const error = dialog.querySelector('[data-spell-error]');
  const more = dialog.querySelector('[data-spell-more]');
  const custom = dialog.querySelector('[data-spell-custom]');
  let catalog, level = 0, limit = 50, loading;
  const spellLinks = new Map();
  const spellKey = name => name.trim().toLowerCase().replaceAll('’', "'").replace(/\s+/g, ' ');
  for (const link of sheet.querySelectorAll('[data-spell-entries] a')) {
    spellLinks.set(spellKey(link.textContent), link.href);
  }
  const field = number => sheet.elements.namedItem(`spell.${number}.list`);
  const names = number => field(number).value.split('\n').map(name => name.trim()).filter(Boolean);
  const fail = message => { error.textContent = message; error.hidden = false; };

  function renderList(number) {
    const list = sheet.querySelector(`[data-spell-entries="${number}"]`);
    list.replaceChildren();
    const entries = names(number);
    entries.forEach((name, index) => {
      const row = document.createElement('li');
      const key = spellKey(name);
      const base = key.replace(/\s+\((?:domain(?:,\s*dc\s+\d+)?|dc\s+\d+)\)$/, '');
      const url = spellLinks.get(key) || spellLinks.get(base);
      const label = document.createElement(url ? 'a' : 'span');
      label.textContent = name;
      if (url) {
        label.href = url;
        label.target = '_blank';
        label.rel = 'noopener noreferrer';
      }
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'button small ds-remove-spell';
      remove.textContent = 'Remove';
      remove.setAttribute('aria-label', `Remove ${name}`);
      remove.addEventListener('click', () => {
        const current = names(number);
        current.splice(index, 1);
        field(number).value = current.join('\n');
        field(number).dispatchEvent(new Event('input', {bubbles: true}));
        renderList(number);
        const buttons = list.querySelectorAll('button');
        (buttons[Math.min(index, buttons.length - 1)] || sheet.querySelector(`[data-add-spells="${number}"]`)).focus();
      });
      row.append(label, remove);
      list.append(row);
    });
    if (!entries.length) {
      const row = document.createElement('li');
      row.textContent = 'No spells added.';
      list.append(row);
    }
  }

  function add(name) {
    name = name.trim();
    if (!name || /[\r\n]/.test(name)) return fail('Enter one spell name.');
    const current = names(level);
    if (current.some(item => item.toLowerCase() === name.toLowerCase())) return fail('That spell is already in this list.');
    const value = [...current, name].join('\n');
    if (value.length > field(level).maxLength) return fail('This spell list is full.');
    field(level).value = value;
    field(level).dispatchEvent(new Event('input', {bubbles: true}));
    error.hidden = true;
    renderList(level);
    render();
  }

  function render() {
    results.replaceChildren();
    if (!catalog) { status.textContent = 'Loading spells…'; more.hidden = true; return; }
    const query = search.value.trim().toLowerCase();
    const selectedClass = classes.value;
    const existing = new Set(names(level).map(name => name.toLowerCase()));
    const matches = catalog.spells.filter(item => item.name.toLowerCase().includes(query) &&
      (selectedClass ? (item.levels[selectedClass] || []).includes(level) : Object.values(item.levels).some(levels => levels.includes(level))));
    status.textContent = `${matches.length} matching spells`;
    for (const item of matches.slice(0, limit)) {
      const row = results.insertRow();
      const link = document.createElement(item.url ? 'a' : 'span');
      link.textContent = item.name;
      if (item.url) {
        link.href = item.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
      row.insertCell().append(link);
      row.insertCell().textContent = Object.entries(item.levels).map(([name, levels]) => `${name} ${levels.join('/')}`).join(' · ');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'button small';
      button.disabled = existing.has(item.name.toLowerCase());
      button.textContent = button.disabled ? 'Added' : 'Add';
      button.setAttribute('aria-label', `Add ${item.name}`);
      button.addEventListener('click', () => { add(item.name); search.focus(); });
      row.insertCell().append(button);
    }
    more.hidden = matches.length <= limit;
  }

  for (const button of sheet.querySelectorAll('[data-add-spells]')) {
    const number = Number(button.dataset.addSpells);
    renderList(number);
    button.addEventListener('click', async () => {
      level = number;
      limit = 50;
      search.value = custom.value = '';
      error.hidden = true;
      dialog.querySelector('[data-spell-level]').textContent = level ? `Level ${level} spells` : 'Cantrips / orisons';
      dialog.showModal();
      search.focus();
      render();
      try {
        if (!catalog) {
          loading ||= fetch(dialog.dataset.endpoint, {headers: {Accept: 'application/json'}}).then(async response => {
            if (response.redirected) throw new Error('Sign in again to load spells.');
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Unable to load spells.');
            for (const item of data.spells) {
              if (item.url) spellLinks.set(spellKey(item.name), item.url);
            }
            const choices = [...new Set(data.spells.flatMap(item => Object.keys(item.levels)))].sort();
            classes.replaceChildren(new Option('All classes', ''), ...choices.map(name => new Option(name, name)));
            classes.value = choices.includes(data.class_name) ? data.class_name : '';
            window.PathkeeperDropdown?.refresh(classes);
            catalog = data;
          }).finally(() => { loading = null; });
          await loading;
        }
        render();
      } catch (failure) { status.textContent = ''; fail(failure.message); }
    });
  }
  for (const button of dialog.querySelectorAll('[data-spell-close]')) button.addEventListener('click', () => dialog.close());
  search.addEventListener('input', () => { limit = 50; render(); });
  classes.addEventListener('change', () => { limit = 50; render(); });
  more.addEventListener('click', () => { limit += 50; render(); });
  dialog.querySelector('[data-spell-add-custom]').addEventListener('click', () => { add(custom.value); custom.value = ''; custom.focus(); });
  custom.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); add(custom.value); custom.value = ''; } });
})();

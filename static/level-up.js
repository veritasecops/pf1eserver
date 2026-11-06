(() => {
  const form = document.getElementById('level-up-form');
  if (!form) return;

  const steps = [...form.querySelectorAll('[data-level-step]')];
  const back = form.querySelector('[data-level-back]');
  const next = form.querySelector('[data-level-next]');
  const finish = form.querySelector('[data-level-submit]');
  const position = form.querySelector('[data-level-position]');
  const budget = form.querySelector('[data-rank-budget]');
  const ranks = [...form.querySelectorAll('[name^="rank_"]')];
  const nav = [...document.querySelectorAll('[data-level-nav]')];
  const slots = [...form.querySelectorAll('[data-feat-slot]')];
  const error = form.querySelector('[data-level-error]');
  const rules = JSON.parse(document.getElementById('level-up-feats').textContent);
  const limits = new WeakMap();
  let step = 0;

  function selected(slot) {
    return form.elements.namedItem('choice_' + slot.dataset.featSlot);
  }

  function target(slot) {
    return form.elements.namedItem('target_' + slot.dataset.featSlot);
  }

  function eligible(slot, name) {
    const feat = Object.hasOwn(rules.options, name) ? rules.options[name] : null;
    if (!feat || (slot.dataset.featKind && !feat[slot.dataset.featKind]) || feat.bab > rules.bab) return false;
    if (Object.entries(feat.scores).some(([key, score]) =>
      rules.scores[key] + Number(form.elements.ability?.value === key) < score)) return false;
    const taken = rules.owned.concat(slots.filter(other => other !== slot).map(other => [selected(other).value, target(other).value]));
    if (taken.some(([other]) => other === name) && !feat.repeatable) return false;
    if (feat.choice && !Object.keys(rules.targets[feat.choice] || {}).some(key =>
      !taken.some(([other, used]) => other === name && used === key))) return false;
    return !feat.requires || taken.some(([other]) => other === feat.requires);
  }

  function featLink(name) {
    const url = rules.options[name]?.url;
    const node = document.createElement(url ? 'a' : 'span');
    node.textContent = name;
    if (url) {
      node.href = url;
      node.target = '_blank';
      node.rel = 'noopener noreferrer';
      node.className = 'level-reference';
    }
    return node;
  }

  function renderSlot(slot) {
    const value = selected(slot).value;
    const current = slot.querySelector('[data-feat-selection]');
    current.replaceChildren(value ? featLink(value) : 'No feat selected');
    const field = target(slot);
    const kind = rules.options[value]?.choice || '';
    const prior = field.value || field.dataset.saved;
    const excluded = rules.owned.concat(slots.filter(other => other !== slot)
      .map(other => [selected(other).value, target(other).value]))
      .filter(([name]) => name === value).map(([, key]) => key);
    const choices = Object.entries(rules.targets[kind] || {}).filter(([key]) => !excluded.includes(key));
    if (kind) {
      field.replaceChildren(new Option(`Choose a ${kind}`, ''),
        ...choices.map(([key, label]) => new Option(label, key)));
      field.value = choices.some(([key]) => key === prior) ? prior : '';
    }
    field.dataset.saved = '';
    field.disabled = !kind;
    field.required = Boolean(kind);
    slot.querySelector('[data-feat-target]').hidden = !kind;
    window.PathkeeperDropdown?.refresh(field);

    const query = slot.querySelector('[data-feat-search]').value.trim().toLowerCase();
    const matches = Object.keys(rules.options).filter(name => name.toLowerCase().includes(query) && eligible(slot, name));
    const rows = slot.querySelector('[data-feat-results]');
    const limit = limits.get(slot) || 30;
    rows.replaceChildren();
    for (const name of matches.slice(0, limit)) {
      const row = rows.insertRow();
      row.insertCell().append(featLink(name));
      const button = document.createElement('button');
      button.className = 'button small';
      button.type = 'button';
      button.textContent = name === value ? 'Selected' : 'Choose';
      button.disabled = name === value;
      button.setAttribute('aria-label', 'Choose ' + name);
      button.addEventListener('click', () => {
        selected(slot).value = name;
        target(slot).value = '';
        slots.forEach(renderSlot);
        slot.querySelector('[data-feat-search]').focus();
      });
      row.insertCell().append(button);
    }
    if (!matches.length) {
      const cell = rows.insertRow().insertCell();
      cell.colSpan = 2;
      cell.textContent = 'No eligible feats match this search.';
    }
    slot.querySelector('[data-more-feats]').hidden = matches.length <= limit;
  }

  for (const slot of slots) {
    slot.querySelector('[data-feat-search]').addEventListener('input', () => {
      limits.delete(slot);
      renderSlot(slot);
    });
    slot.querySelector('[data-more-feats]').addEventListener('click', () => {
      limits.set(slot, (limits.get(slot) || 30) + 30);
      renderSlot(slot);
    });
    target(slot).addEventListener('change', () => slots.filter(other => other !== slot).forEach(renderSlot));
  }

  const show = (index, focus = true) => {
    step = index;
    steps.forEach((section, i) => { section.hidden = i !== step; });
    position.textContent = `Step ${step + 1} of ${steps.length}`;
    position.hidden = false;
    nav.forEach((button, i) => {
      button.disabled = i > step + 1;
      if (i === step) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    if (step === 2) slots.forEach(renderSlot);
    back.hidden = step === 0;
    next.hidden = step === steps.length - 1;
    finish.hidden = !next.hidden;
    if (focus) {
      const heading = steps[step].querySelector('h2');
      heading.tabIndex = -1;
      heading.focus();
    }
  };

  const countRanks = () => {
    const base = Number(form.dataset.ranks);
    const score = Number(form.dataset.int);
    const before = Math.max(1, base + Math.floor((score - 10) / 2));
    const after = Math.max(1, base + Math.floor((score - 10 + (form.elements.ability?.value === 'int' ? 1 : 0)) / 2));
    const favored = Number(form.elements.favored.value === 'skill');
    const total = after + (after - before) * (Number(form.dataset.target) - 1) + Number(form.dataset.human) + favored;
    const assigned = ranks.reduce((sum, input) => sum + Number(input.value), 0);
    for (const input of ranks) {
      const row = input.closest('tr');
      const added = Number(input.value);
      row.querySelector('[data-new-ranks]').textContent = Number(row.querySelector('[data-current-ranks]').textContent) + added;
      input.max = Math.min(Number(input.dataset.rankLimit), Math.max(added, total - assigned + added));
    }
    budget.textContent = `${assigned} of ${total} skill ranks allocated.`;
    return assigned === total;
  };

  const forward = () => {
    const invalid = [...steps[step].querySelectorAll('input, select, textarea')].find(input => !input.checkValidity());
    if (invalid) return invalid.reportValidity();
    if (steps[step].contains(budget) && !countRanks()) {
      budget.tabIndex = -1;
      return budget.focus();
    }
    show(step + 1);
  };
  nav.forEach((button, i) => button.addEventListener('click', () => {
    if (i < step) show(i);
    else if (i === step + 1) forward();
  }));
  nav[0].parentElement.hidden = false;
  form.addEventListener('submit', event => {
    if (!countRanks()) {
      event.preventDefault();
      show(1);
      return;
    }
    const bad = slots.find(slot => !eligible(slot, selected(slot).value));
    const lines = input => input.value.split('\n').map(line => line.trim()).filter(Boolean);
    const invalidSpells = [...form.querySelectorAll('[data-spell-count]')]
      .find(input => lines(input).length !== Number(input.dataset.spellCount));
    const bookFields = [...form.querySelectorAll('[data-book-spells]')];
    const bookCount = Number(form.dataset.book);
    const badBook = bookFields.length && bookFields.flatMap(lines).length !== bookCount;
    const swap = form.elements.swap_spell;
    const replacement = form.elements.replacement_spell;
    const incompleteSwap = swap && Boolean(swap.value) !== Boolean(replacement.value.trim());
    let message = '';
    let focus;
    if (bad) {
      message = 'Choose an eligible feat for each feat slot.';
      focus = bad.querySelector('[data-feat-search]');
    } else if (invalidSpells) {
      message = `Enter ${invalidSpells.dataset.spellCount} new spells at that spell level.`;
      focus = invalidSpells;
    } else if (badBook) {
      message = `Enter ${bookCount} new spellbook or formula-book entries.`;
      focus = bookFields[0];
    } else if (incompleteSwap) {
      message = 'Choose a spell to replace and enter its replacement.';
      focus = replacement;
    }
    if (message) {
      event.preventDefault();
      if (step !== 2) show(2);
      error.textContent = message;
      error.hidden = false;
      focus.focus();
    }
  });
  back.addEventListener('click', () => show(step - 1));
  next.addEventListener('click', forward);
  form.addEventListener('input', countRanks);
  form.addEventListener('invalid', event => {
    const invalidStep = steps.findIndex(section => section.contains(event.target));
    if (invalidStep !== -1 && steps[invalidStep].hidden) show(invalidStep, false);
  }, true);
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches('[data-feat-search]')) {
      event.preventDefault();
      return;
    }
    if (event.key === 'Enter' && !next.hidden && event.target.matches('input:not([type="checkbox"])')) {
      event.preventDefault();
      forward();
    }
  });
  countRanks();
  show(0, false);
})();

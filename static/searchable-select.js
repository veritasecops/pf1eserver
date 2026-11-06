(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));
  const render = ({ label, context='', path, value='', options=[], allowCustom=false, placeholder='Choose an option' }) => {
    const name = context ? `${context}: ${label}` : label;
    const id = `pw-select-${path.replace(/[^a-z0-9-]/gi,'-')}`;
    const items = [...options];
    if (value && !items.some(item => item.value === value)) items.push({ value, label:value, hint:'Saved selection; confirm with your GM.' });
    const selected = items.find(item => item.value === value);
    const url = window.PathkeeperDropdown.referenceURL(selected?.url);
    return `<div class="pw-search-select" data-search-select data-allow-custom="${allowCustom}" data-custom-label="GM approval required">
      <span class="pw-search-label">${escape(label)}</span>
      <input type="hidden" data-search-select-value data-path="${escape(path)}" value="${escape(value)}">
      <span class="dropdown-picker"><a class="dropdown-value" id="${id}-selected" data-search-selected ${url?`href="${escape(url)}"`:''} target="_blank" rel="noopener noreferrer">${escape(selected?.label || value || placeholder)}</a><button type="button" class="pw-search-trigger dropdown-arrow" role="combobox" aria-label="${escape(name)}" aria-haspopup="listbox" aria-expanded="false" aria-controls="${id}-list" aria-describedby="${id}-selected" data-search-trigger><span aria-hidden="true">▾</span></button></span>
      <div class="pw-search-panel" data-search-panel hidden>
        <div class="pw-search-box"><input type="search" data-search-query aria-label="Search ${escape(name)}" placeholder="Search options…" autocomplete="off"></div>
        <div class="pw-search-options" id="${id}-list" role="listbox" aria-label="${escape(name)} options" data-search-options>
          <button type="button" role="option" tabindex="-1" aria-label="No selection" aria-selected="${!value}" data-search-option data-value="" data-filter="">No selection</button>
          ${items.map((item,index)=>`<button type="button" role="option" tabindex="-1" aria-label="${escape(item.label)}" ${item.hint?`aria-describedby="${id}-hint-${index}"`:""} aria-selected="${item.value === value}" data-search-option data-value="${escape(item.value)}" data-reference-url="${escape(item.url || '')}" data-filter="${escape(`${item.label} ${item.hint || ''}`.toLowerCase())}" ${item.disabled?'disabled aria-disabled="true"':''}><span>${escape(item.label)}</span>${item.hint?`<span class="secondary-text" id="${id}-hint-${index}">${escape(item.hint)}</span>`:''}</button>`).join('')}
          ${allowCustom?'<button type="button" role="option" tabindex="-1" aria-selected="false" data-search-custom hidden></button>':''}
          <p class="pw-search-empty" data-search-empty hidden>No matching options.</p>
        </div>
      </div>
    </div>`;
  };
  window.PathkeeperSearchSelect = { render };

  const close = (widget, focus=false) => {
    widget.querySelector('[data-search-panel]').hidden = true;
    widget.querySelector('[data-search-trigger]').setAttribute('aria-expanded','false');
    if (focus) widget.querySelector('[data-search-trigger]').focus();
  };
  const options = widget => [...widget.querySelectorAll('[role="option"]')].filter(option => !option.hidden && !option.disabled);
  const filter = widget => {
    const query = widget.querySelector('[data-search-query]').value.trim();
    const normalized = query.toLowerCase();
    let count = 0;
    const existing = [...widget.querySelectorAll('[data-search-option]')];
    for (const option of existing) {
      option.hidden = normalized ? !option.dataset.value || !option.dataset.filter.includes(normalized) : false;
      if (!option.hidden) count++;
    }
    const custom = widget.querySelector('[data-search-custom]');
    if (custom) {
      custom.hidden = !query || query.length > 100 || existing.some(option => option.dataset.value.toLowerCase() === normalized);
      custom.dataset.value = query;
      custom.textContent = `Use “${query}” (GM approval required)`;
      custom.setAttribute('aria-label',`Use ${query} (GM approval required)`);
      if (!custom.hidden) count++;
    }
    widget.querySelector('[data-search-empty]').hidden = count > 0;
  };
  const open = widget => {
    for (const other of document.querySelectorAll('[data-search-select]')) if (other !== widget) close(other);
    const panel = widget.querySelector('[data-search-panel]');
    panel.classList.remove('pw-search-above');
    panel.hidden = false;
    widget.querySelector('[data-search-trigger]').setAttribute('aria-expanded','true');
    const query = widget.querySelector('[data-search-query]');
    query.value = '';
    filter(widget);
    panel.style.removeProperty('--pw-search-space');
    const box = panel.getBoundingClientRect();
    const bounds = widget.getBoundingClientRect();
    const below = Math.max(0,innerHeight-bounds.bottom-12),above = Math.max(0,bounds.top-12);
    const useAbove = below < box.height && above > below;
    panel.classList.toggle('pw-search-above',useAbove);
    const searchHeight = widget.querySelector('.pw-search-box').getBoundingClientRect().height;
    panel.style.setProperty('--pw-search-space',`${Math.max(60,(useAbove?above:below)-searchHeight-4)}px`);
    query.focus({preventScroll:true});
  };

  document.addEventListener('click', event => {
    const widget = event.target.closest('[data-search-select]');
    if (!widget) {
      for (const current of document.querySelectorAll('[data-search-select]')) close(current);
      return;
    }
    if (event.target.closest('[data-search-trigger]')) {
      if (widget.querySelector('[data-search-panel]').hidden) open(widget);
      else close(widget);
      return;
    }
    const option = event.target.closest('[role="option"]');
    if (!option || option.disabled) return;
    const input = widget.querySelector('[data-search-select-value]');
    input.value = option.dataset.value;
    const selected = widget.querySelector('[data-search-selected]');
    selected.textContent = option.dataset.value ? option.getAttribute('aria-label').replace(/^Use (.*) \(GM approval required\)$/,'$1') : 'Choose an option';
    const url = window.PathkeeperDropdown.referenceURL(option.dataset.referenceUrl);
    if (url) selected.href = url;
    else selected.removeAttribute('href');
    close(widget,true);
    input.dispatchEvent(new Event('change',{bubbles:true}));
  });
  document.addEventListener('input', event => {
    if (event.target.matches('[data-search-query]')) filter(event.target.closest('[data-search-select]'));
  });
  document.addEventListener('keydown', event => {
    const widget = event.target.closest('[data-search-select]');
    if (!widget) return;
    const panel = widget.querySelector('[data-search-panel]');
    if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); event.stopPropagation(); close(widget,true); return; }
    if (event.target.matches('[data-search-trigger]') && ['ArrowDown','ArrowUp'].includes(event.key)) {
      event.preventDefault(); open(widget); return;
    }
    if (panel.hidden) return;
    const choices = options(widget);
    const index = choices.indexOf(document.activeElement);
    if (['ArrowDown','ArrowUp'].includes(event.key)) {
      event.preventDefault();
      const next = index < 0 ? (event.key === 'ArrowDown' ? 0 : choices.length-1) : (index+(event.key === 'ArrowDown'?1:-1)+choices.length)%choices.length;
      choices[next]?.focus();
    } else if (event.key === 'Enter' && event.target.matches('[data-search-query]')) {
      event.preventDefault();
      const first = choices.find(option => option.dataset.value) || choices[0];
      first?.click();
    }
  });
  document.addEventListener('focusout', event => {
    const widget = event.target.closest('[data-search-select]');
    // Some browsers don't move focus onto a mouse-clicked option. Let the
    // click handler finish that selection before treating a null target as exit.
    if (widget && event.relatedTarget && !widget.contains(event.relatedTarget)) close(widget);
  });
})();

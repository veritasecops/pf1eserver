(() => {
  function referenceURL(value) {
    try {
      const url = new URL(value);
      if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href;
    } catch {}
    return '';
  }

  function refresh(select) {
    if (select.multiple || select.size > 1) return;
    let picker = select.parentElement;
    if (!picker?.classList.contains('dropdown-picker')) {
      picker = document.createElement('span');
      picker.className = 'dropdown-picker';
      const link = document.createElement('a');
      link.className = 'dropdown-value';
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.addEventListener('click', event => {
        if (!link.hasAttribute('href')) event.preventDefault();
      });
      const arrow = document.createElement('span');
      arrow.className = 'dropdown-arrow';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '▾';
      select.before(picker);
      picker.append(link, arrow, select);
    }
    const link = picker.querySelector('.dropdown-value');
    const option = select.selectedOptions[0];
    const name = option?.label || '';
    if (link.textContent !== name) link.textContent = name;
    const url = referenceURL(option?.dataset.referenceUrl);
    if (url) link.href = url;
    else link.removeAttribute('href');
  }

  window.PathkeeperDropdown = {refresh, referenceURL};
  function find(node) {
    if (node instanceof HTMLSelectElement) refresh(node);
    else node.querySelectorAll?.('select').forEach(refresh);
  }
  find(document);
  for (const type of ['input', 'change']) {
    document.addEventListener(type, event => {
      if (event.target instanceof HTMLSelectElement) refresh(event.target);
    });
  }
  document.addEventListener('reset', event => {
    setTimeout(() => find(event.target), 0);
  });
  new MutationObserver(records => {
    for (const record of records) {
      const select = record.target.closest?.('select');
      if (select) refresh(select);
      else record.addedNodes.forEach(node => {
        if (node.isConnected) find(node);
      });
    }
  }).observe(document.body, {childList: true, subtree: true});
})();

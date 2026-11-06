(() => {
  function update(select) {
    const picker = select.closest('.deity-picker');
    const link = picker?.querySelector('[data-deity-reference]');
    if (!link) return;
    picker.dataset.ready = '';
    const option = select.selectedOptions[0];
    const name = option?.textContent || '';
    if (link.textContent !== name) link.textContent = name;
    const url = option?.dataset.descriptionUrl || '';
    try {
      if (['http:', 'https:'].includes(new URL(url).protocol)) {
        link.href = url;
        return;
      }
    } catch {}
    link.removeAttribute('href');
  }
  document.addEventListener('change', event => {
    if (event.target.matches('[data-deity-select]')) update(event.target);
  });
  function refresh() {
    document.querySelectorAll('[data-deity-select]').forEach(update);
  }
  refresh();
  const stage = document.getElementById('pw-stage');
  if (stage) new MutationObserver(refresh).observe(stage, {childList:true, subtree:true});
})();

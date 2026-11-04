(() => {
  const form = document.getElementById('deluxe-form');
  if (!form) return;
  const status = document.getElementById('sheet-save-status');
  let dirty = Boolean(document.querySelector('.deluxe-errors'));
  let timer;
  let pending;
  let revision = 0;
  let submitting = false;

  const calculate = async (expectedRevision) => {
    const controller = new AbortController();
    pending = controller;
    status.textContent = 'Updating totals…';
    try {
      const response = await fetch(`${form.action}/calculate`, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        signal: controller.signal,
        headers: { Accept: 'application/json' }
      });
      if (expectedRevision !== revision || submitting) return;
      if (!response.ok) {
        status.textContent = response.status === 409
          ? 'Character changed. Reload before saving.'
          : response.status === 422
            ? 'Check your entries to update totals.'
            : 'Totals unavailable. Save or reload to retry.';
        return;
      }
      const result = await response.json();
      if (expectedRevision !== revision || submitting) return;
      const locked = new Set(result.readonly);
      for (const input of form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"])')) {
        input.readOnly = locked.has(input.name);
        if (locked.has(input.name)) input.value = result.values[input.name];
      }
      status.textContent = 'Unsaved changes';
    } catch (error) {
      if (error.name !== 'AbortError' && expectedRevision === revision && !submitting) {
        status.textContent = 'Totals unavailable. Save or reload to retry.';
      }
    } finally {
      if (pending === controller) pending = null;
    }
  };

  const markDirty = () => {
    dirty = true;
    revision += 1;
    status.textContent = 'Unsaved changes';
    clearTimeout(timer);
    pending?.abort();
    const expectedRevision = revision;
    timer = setTimeout(() => calculate(expectedRevision), 250);
  };
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('submit', () => {
    submitting = true;
    dirty = false;
    revision += 1;
    clearTimeout(timer);
    pending?.abort();
    status.textContent = 'Saving…';
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  document.getElementById('print-sheet').addEventListener('click', () => window.print());
  if (dirty) {
    status.textContent = 'Unsaved changes';
    document.querySelector('.deluxe-errors').focus();
  }
})();

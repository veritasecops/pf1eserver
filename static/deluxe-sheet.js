(() => {
  const form = document.getElementById('deluxe-form');
  if (!form) return;
  const status = document.getElementById('sheet-save-status');
  let dirty = Boolean(document.querySelector('.deluxe-errors'));
  const markDirty = () => { dirty = true; status.textContent = 'Unsaved changes'; };
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('submit', () => { dirty = false; status.textContent = 'Saving…'; });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  document.getElementById('print-sheet').addEventListener('click', () => window.print());
  if (dirty) {
    status.textContent = 'Unsaved changes';
    document.querySelector('.deluxe-errors').focus();
  }
})();

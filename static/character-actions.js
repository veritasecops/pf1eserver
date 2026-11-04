(() => {
  const dialog = document.getElementById('delete-character');
  const open = document.getElementById('open-character-delete');
  if (!dialog || !open) return;
  open.addEventListener('click', () => dialog.showModal());
  document.getElementById('cancel-character-delete').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    dialog.querySelector('[name="confirm_name"]').value = '';
    open.focus();
  });
})();

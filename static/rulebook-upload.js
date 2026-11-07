for (const form of document.querySelectorAll('[data-rulebook-upload]')) {
  const input = form.elements.namedItem('pdf');
  const zone = form.querySelector('[data-rulebook-drop]');
  const status = form.querySelector('[data-rulebook-file-status]');
  const dialog = form.closest('dialog');
  const target = dialog || zone;
  const roles = [...form.querySelectorAll('[name="access_role"]')];

  function validateRoles() {
    roles[0].setCustomValidity(roles.some(role => role.checked) ? '' : 'Choose at least one access role.');
  }

  function showFile(files, dropped = false) {
    let message = '';
    if (files.length !== 1 || !/\.pdf$/i.test(files[0].name)) {
      message = 'Choose one PDF file.';
    } else if (files[0].size > 250 * 1024 * 1024) {
      message = 'Choose a PDF of 250 MB or smaller.';
    } else if (dropped) {
      try {
        input.files = files;
      } catch {
        message = 'Use the file browser to select your PDF.';
      }
    }
    if (message) input.value = '';
    status.textContent = message || `Selected: ${files[0].name}`;
  }

  for (const role of roles) role.addEventListener('change', validateRoles);
  validateRoles();
  input.addEventListener('change', () => {
    if (input.files.length) showFile(input.files);
    else status.textContent = '';
  });
  target.addEventListener('dragover', event => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    zone.classList.add('is-dragging');
  });
  target.addEventListener('dragleave', event => {
    if (!target.contains(event.relatedTarget)) zone.classList.remove('is-dragging');
  });
  target.addEventListener('drop', event => {
    zone.classList.remove('is-dragging');
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    showFile(event.dataTransfer.files, true);
  });
  form.querySelector('[data-rulebook-cancel]')?.addEventListener('click', () => dialog.close());
}

(() => {
  const form = document.getElementById('deluxe-form');
  if (!form) return;
  const status = document.getElementById('sheet-save-status');
  const errors = document.getElementById('sheet-autosave-errors');
  const retry = document.getElementById('retry-sheet-save');
  let dirty = Boolean(document.querySelector('.deluxe-errors:not([hidden])'));
  let timer;
  let revision = 0;
  let saving = false;
  let failed = null;
  let blocked = false;
  let attempts = 0;
  let currentSave = null;
  let saveError = '';

  const showError = message => {
    saveError = message;
    errors.textContent = message;
    errors.hidden = false;
  };
  const applyTotals = result => {
    for (const kind of ['weapon','armor']) {
    if (result[kind+'_links']) {
      for (const link of form.querySelectorAll(`[data-${kind}-reference]`)) {
        const row = link.dataset[kind+'Reference'];
        const reference = result[kind+'_links'][row];
        const name = form.elements.namedItem(`${kind}.${row}.name`)?.value.trim();
        link.hidden = !reference || reference.name !== name;
        if (!link.hidden) {
          link.href = reference.url;
          link.setAttribute('aria-label', `Reference for ${reference.name}`);
        } else link.removeAttribute('href');
      }
    }
    }
    const locked = new Set(result.readonly);
    for (const input of form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"])')) {
      input.readOnly = locked.has(input.name);
      if (result.formulas) window.PathkeeperFormulas?.update(input,result.formulas[input.name]);
      if (locked.has(input.name)) input.value = result.values[input.name];
    }
    window.PathkeeperEquipment?.update(result.equipment_state,result.equipment_groups);
    document.getElementById('sheet-character-name').textContent = result.name;
    document.title = `${result.name} · Pathkeeper`;
    const deleteName = document.getElementById('delete-character-name');
    if (deleteName) deleteName.textContent = result.name;
    const breadcrumb = document.querySelector('.topbar .breadcrumb strong');
    if (breadcrumb) breadcrumb.textContent = result.name;
  };
  const saveId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');

  const runSave = async () => {
    clearTimeout(timer);
    if (!dirty || saving || blocked) return;
    if (!failed && !form.checkValidity()) {
      status.textContent = 'Not saved. Complete the required fields.';
      return;
    }
    // Retry the identical payload and identifier if a response was lost. A
    // subsequent edit waits for its acknowledgement before using the new version.
    const job = failed || { body: new FormData(form), id: saveId(), revision };
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    saving = true;
    retry.hidden = true;
    status.textContent = 'Saving…';
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: job.body,
        signal: controller.signal,
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Sheet-Save-Id': job.id }
      });
      if (response.status >= 500 || response.status === 429) throw new Error('Temporary save failure');
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
        // Application error pages may be HTML. Report their status without
        // mistaking them for a successful save or overwriting local edits.
        if (response.status === 409) {
          blocked = true;
          failed = null;
          status.textContent = 'Not saved. Character changed elsewhere.';
          showError('Reload before editing again. Your current edits have not been saved.');
          return;
        }
        if (response.status === 403 || response.status === 404 || response.redirected) {
          blocked = true;
          failed = null;
          status.textContent = 'Not saved. Reload and check your access.';
          showError('Your session or character access changed. Your current edits have not been saved.');
          return;
        }
        throw new Error('Unexpected save response');
      }
      const result = await response.json();
      if (!response.ok) {
        failed = null;
        if (response.status === 409 || response.status === 403 || response.status === 404) blocked = true;
        status.textContent = response.status === 409 ? 'Not saved. Character changed elsewhere.' : 'Not saved. Check your entries.';
        showError(result.errors?.join(' ') || result.detail || 'Reload before editing again.');
        // A newer edit may have corrected an invalid field while this request ran.
        if (job.revision !== revision && !blocked) timer = setTimeout(save, 0);
        return;
      }
      form.elements.namedItem('version').value = String(result.version);
      const deleteVersion = document.querySelector('#delete-character input[name="version"]');
      if (deleteVersion) deleteVersion.value = String(result.version);
      failed = null;
      attempts = 0;
      errors.hidden = true;
      saveError = '';
      for (const oldError of document.querySelectorAll('.deluxe-errors:not(#sheet-autosave-errors)')) oldError.hidden = true;
      if (job.revision === revision) {
        applyTotals(result);
        dirty = false;
        status.textContent = 'All changes saved';
      } else {
        status.textContent = 'Saving newer changes…';
        timer = setTimeout(save, 0);
      }
    } catch (error) {
      failed = job;
      attempts += 1;
      status.textContent = 'Not saved. Retrying…';
      showError('Changes are still on this page. Keep it open until all changes are saved.');
      retry.hidden = false;
      if (attempts <= 3) timer = setTimeout(save, 1000 * 2 ** (attempts - 1));
      else status.textContent = 'Not saved. Retry when connected.';
    } finally {
      clearTimeout(timeout);
      saving = false;
    }
  };

  const save = () => {
    if (saving) return;
    currentSave = runSave();
    return currentSave;
  };
  window.PathkeeperSheet = {
    get hasPending() { return dirty || saving; },
    async flush() {
      clearTimeout(timer);
      if (blocked) throw new Error('Reload the character before purchasing.');
      if (!form.checkValidity()) throw new Error('Complete the required sheet fields before purchasing.');
      do {
        if (saving) await currentSave; else await save();
        if (blocked || failed || saveError) throw new Error(saveError || 'Save the sheet before purchasing.');
      } while (dirty || saving);
    },
    applyPurchase(result) {
      for (const [name,value] of Object.entries(result.purchase_fields)) {
        const input = form.elements.namedItem(name);
        if (input) {if(input.type==='checkbox')input.checked=value==='1';else input.value=value;}
      }
      form.elements.namedItem('version').value = String(result.version);
      const deleteVersion = document.querySelector('#delete-character input[name="version"]');
      if (deleteVersion) deleteVersion.value = String(result.version);
      applyTotals(result);
      dirty = false;
      failed = null;
      saveError = '';
      errors.hidden = true;
      status.textContent = 'All changes saved';
      form.dispatchEvent(new Event('sheetpurchase'));
    }
  };

  const markDirty = () => {
    dirty = true;
    revision += 1;
    if (blocked) return;
    clearTimeout(timer);
    status.textContent = saving ? 'Saving newer changes…' : 'Unsaved changes';
    timer = setTimeout(save, 400);
  };
  form.addEventListener('input', event => {
    const row = /^weapon\.(\d+)\.name$/.exec(event.target.name || '');
    if (row) {
      const link = form.querySelector(`[data-weapon-reference="${row[1]}"]`);
      if (link) { link.hidden = true; link.removeAttribute('href'); }
    }
    markDirty();
  });
  form.addEventListener('change', markDirty);
  form.addEventListener('focusout', () => { if (dirty && !saving && !blocked) save(); });
  form.addEventListener('submit', event => { event.preventDefault(); save(); });
  retry.addEventListener('click', () => { attempts = 0; save(); });
  window.addEventListener('online', () => { attempts = 0; save(); });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  document.getElementById('print-sheet').addEventListener('click', () => window.print());
  if (dirty) {
    status.textContent = 'Unsaved changes';
    document.querySelector('.deluxe-errors:not([hidden])')?.focus();
    timer = setTimeout(save, 400);
  }
})();

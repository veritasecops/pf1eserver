const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const fields = {
    version: { name: 'version', value: '1' },
    'ability.dex.score': { name: 'ability.dex.score', value: '10', readOnly: false },
    'ability.dex.mod': { name: 'ability.dex.mod', value: '0', readOnly: true },
    'initiative.total': { name: 'initiative.total', value: '0', readOnly: true }
  };
  const status = { textContent: 'All changes saved' };
  const errors = { textContent: '', hidden: true };
  const retry = { hidden: true, addEventListener: (name, fn) => { retry[name] = fn; } };
  const listeners = {};
  const windows = {};
  const timers = new Map();
  const calls = [];
  let timerId = 0;
  let random = 0;
  const form = {
    action: 'http://example.test/characters/1/play-sheet',
    elements: { namedItem: name => fields[name] },
    checkValidity: () => true,
    addEventListener: (name, fn) => { listeners[name] = fn; },
    querySelectorAll: () => Object.values(fields).filter(field => field.name !== 'version')
  };
  const nodes = {
    'deluxe-form': form, 'sheet-save-status': status,
    'sheet-autosave-errors': errors, 'retry-sheet-save': retry,
    'sheet-character-name': { textContent: 'Hero' },
    'print-sheet': { addEventListener: () => {} }
  };
  vm.runInNewContext(fs.readFileSync('static/deluxe-sheet.js', 'utf8'), {
    document: { getElementById: id => nodes[id], querySelector: () => null, querySelectorAll: () => [] },
    window: { addEventListener: (name, fn) => { windows[name] = fn; } },
    FormData: class {
      constructor() { this.values = Object.fromEntries(Object.entries(fields).map(([key,field]) => [key,field.value])); }
    },
    crypto: { getRandomValues: bytes => { bytes.fill(++random); return bytes; } },
    AbortController, Uint8Array,
    setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => calls.push({ url, options, resolve, reject }))
  });
  function change(value) { fields['ability.dex.score'].value = value; listeners.input({ target: fields['ability.dex.score'] }); }
  function run(delay) {
    const entry = [...timers].find(([,timer]) => timer.delay === delay);
    assert.ok(entry, `Expected a ${delay}ms timer`);
    timers.delete(entry[0]);
    return entry[1].fn();
  }
  function response(version, modifier, total) {
    return { ok: true, status: 200, redirected: false, headers: { get: () => 'application/json' },
      json: async () => ({ version, name: 'Hero', readonly: ['ability.dex.mod','initiative.total'],
        values: { 'ability.dex.mod': modifier, 'initiative.total': total } }) };
  }
  function unsaved() {
    const event = { prevented: false, preventDefault() { this.prevented = true; } };
    windows.beforeunload(event);
    return event.prevented;
  }
  return { fields, status, errors, retry, calls, listeners, change, run, response, unsaved };
}

test('autosaves are serialized and an older response cannot replace newer typing', async () => {
  const h = harness();
  h.change('18');
  const first = h.run(400);
  assert.equal(h.calls.length, 1);
  h.change('20');
  await h.run(400);
  assert.equal(h.calls.length, 1);
  h.calls[0].resolve(h.response(2, '4', '8'));
  await first;
  assert.equal(h.fields.version.value, '2');
  assert.equal(h.fields['ability.dex.score'].value, '20');
  assert.equal(h.fields['ability.dex.mod'].value, '0');
  assert.equal(h.unsaved(), true);
  const second = h.run(0);
  assert.equal(h.calls[1].options.body.values.version, '2');
  assert.equal(h.calls[1].options.body.values['ability.dex.score'], '20');
  h.calls[1].resolve(h.response(3, '5', '9'));
  await second;
  assert.equal(h.fields['initiative.total'].value, '9');
  assert.equal(h.status.textContent, 'All changes saved');
  assert.equal(h.unsaved(), false);
});

test('network retries reuse the payload and identifier before saving newer edits', async () => {
  const h = harness();
  h.change('18');
  const first = h.run(400);
  h.calls[0].reject(new Error('Lost response'));
  await first;
  assert.equal(h.unsaved(), true);
  assert.equal(h.retry.hidden, false);
  h.change('20');
  const repeated = h.run(400);
  assert.equal(h.calls[1].options.headers['X-Sheet-Save-Id'], h.calls[0].options.headers['X-Sheet-Save-Id']);
  assert.equal(h.calls[1].options.body.values['ability.dex.score'], '18');
  h.calls[1].resolve(h.response(2, '4', '8'));
  await repeated;
  const next = h.run(0);
  assert.notEqual(h.calls[2].options.headers['X-Sheet-Save-Id'], h.calls[0].options.headers['X-Sheet-Save-Id']);
  assert.equal(h.calls[2].options.body.values.version, '2');
  assert.equal(h.calls[2].options.body.values['ability.dex.score'], '20');
  h.calls[2].resolve(h.response(3, '5', '9'));
  await next;
  assert.equal(h.unsaved(), false);
});

test('conflicts keep edits on the page and stop further automatic writes', async () => {
  const h = harness();
  h.change('18');
  const first = h.run(400);
  h.calls[0].resolve({ ok: false, status: 409, redirected: false, headers: { get: () => 'text/html' } });
  await first;
  assert.equal(h.fields['ability.dex.score'].value, '18');
  assert.equal(h.unsaved(), true);
  assert.equal(h.errors.hidden, false);
  h.change('20');
  assert.equal(h.calls.length, 1);
  assert.match(h.status.textContent, /changed elsewhere/);
});

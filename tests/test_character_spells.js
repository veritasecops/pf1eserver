const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() { this.children = []; this.listeners = {}; this.value = ''; this.hidden = false; this.dataset = {}; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  click() { return this.listeners.click?.(); }
  focus() {}
  setAttribute() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  insertRow() { const row = new Element(); this.append(row); return row; }
  insertCell() { const cell = new Element(); this.append(cell); return cell; }
  querySelectorAll() { return this.children.flatMap(row => row.children.filter(node => node.type === 'button')); }
}

function harness() {
  const controls = Object.fromEntries(['search', 'class', 'results', 'status', 'error', 'more', 'custom', 'level', 'add-custom'].map(key => [key, new Element()]));
  const fields = Array.from({length: 10}, () => Object.assign(new Element(), {maxLength: 10000, changes: 0,
    dispatchEvent() { this.changes++; }}));
  fields[1].value = 'Shield\nMagic Missile';
  const lists = fields.map(() => new Element());
  const launchers = fields.map((_, level) => Object.assign(new Element(), {dataset: {addSpells: String(level)}}));
  const close = new Element();
  const sheet = {
    elements: {namedItem: name => fields[Number(name.split('.')[1])]},
    querySelector: selector => selector.includes('data-spell-entries') ? lists[Number(selector.match(/"(\d+)"/)[1])] : launchers[Number(selector.match(/"(\d+)"/)[1])],
    querySelectorAll: selector => selector === '[data-spell-entries] a'
      ? [{textContent: 'Shield', href: 'https://example.test/shield'}] : launchers,
  };
  const dialog = {
    dataset: {endpoint: '/characters/1/spells'}, showModal() {}, close() {},
    querySelector: selector => controls[selector.slice(12, -1)], querySelectorAll: () => [close],
  };
  let calls = 0;
  vm.runInNewContext(fs.readFileSync('static/character-spells.js', 'utf8'), {
    document: {getElementById: id => id === 'deluxe-form' ? sheet : dialog, createElement: () => new Element()},
    Event: class {}, Option: class extends Element { constructor(label, value) { super(); this.textContent = label; this.value = value; } },
    window: {}, fetch: async () => { calls++; return {ok: true, json: async () => ({class_name: 'Wizard', spells: [
      {name: 'Shield', url: 'https://example.test/shield', levels: {Wizard: [1]}},
      {name: 'Sleep', url: 'https://example.test/sleep', levels: {Wizard: [1]}},
      {name: 'Light', url: 'https://example.test/light', levels: {Wizard: [0]}},
      {name: 'Cure Light Wounds', url: 'https://example.test/cure', levels: {Bard: [1]}},
    ]})}; },
  });
  return {controls, fields, lists, launchers, get calls() { return calls; }};
}

test('sheet removes individual spells and emits an autosave event', () => {
  const h = harness();
  h.lists[1].children[0].children[1].click();
  assert.equal(h.fields[1].value, 'Magic Missile');
  assert.equal(h.fields[1].changes, 1);
  h.lists[1].children[0].children[1].click();
  assert.equal(h.fields[1].value, '');
  assert.equal(h.lists[1].children[0].textContent, 'No spells added.');
});

test('picker filters class and level, adds catalog spells, and prevents duplicates', async () => {
  const h = harness();
  await h.launchers[1].click();
  assert.equal(h.controls.results.children.length, 2);
  assert.equal(h.controls.results.children[0].children[2].children[0].disabled, true);
  h.controls.results.children[1].children[2].children[0].click();
  assert.equal(h.fields[1].value, 'Shield\nMagic Missile\nSleep');
  assert.equal(h.lists[1].children[2].children[0].href, 'https://example.test/sleep');
  assert.equal(h.fields[1].changes, 1);
  h.controls.custom.value = 'sHiElD';
  h.controls['add-custom'].click();
  assert.equal(h.fields[1].changes, 1);
  assert.match(h.controls.error.textContent, /already/);
  await h.launchers[0].click();
  assert.equal(h.controls.results.children.length, 1);
  h.controls.results.children[0].children[2].children[0].click();
  assert.equal(h.fields[0].value, 'Light');
  assert.equal(h.calls, 1);
});

test('saved spell links survive initialization and removing another spell', () => {
  const h = harness();
  assert.equal(h.lists[1].children[0].children[0].href, 'https://example.test/shield');
  assert.equal(h.lists[1].children[1].children[0].href, undefined);
  h.lists[1].children[1].children[1].click();
  const link = h.lists[1].children[0].children[0];
  assert.equal(link.href, 'https://example.test/shield');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(h.calls, 0);
});

test('custom spells respect list capacity', async () => {
  const h = harness();
  await h.launchers[2].click();
  h.controls.custom.value = 'A custom formula';
  h.controls['add-custom'].click();
  assert.equal(h.fields[2].value, 'A custom formula');
  h.fields[2].maxLength = 16;
  h.controls.custom.value = 'Another';
  h.controls['add-custom'].click();
  assert.equal(h.fields[2].value, 'A custom formula');
  assert.match(h.controls.error.textContent, /full/);
});

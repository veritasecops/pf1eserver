const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('dropping a PDF anywhere in the upload dialog populates the form file input', () => {
  const events = {};
  const classes = new Set();
  const zone = { classList: { add: name => classes.add(name), remove: name => classes.delete(name) } };
  const status = { textContent: '' };
  const input = { files: [], addEventListener: (name, fn) => { events[name] = fn; },
    set value(value) { if (!value) this.files = []; } };
  const dialog = { addEventListener: (name, fn) => { events[name] = fn; } };
  const role = { checked: true, setCustomValidity() {}, addEventListener() {} };
  const form = {
    elements: { namedItem: () => input },
    closest: () => dialog,
    querySelector: selector => ({ '[data-rulebook-drop]': zone, '[data-rulebook-file-status]': status })[selector],
    querySelectorAll: () => [role],
  };
  vm.runInNewContext(fs.readFileSync('static/rulebook-upload.js', 'utf8'), {
    document: { querySelectorAll: () => [form] },
  });
  const event = {
    dataTransfer: { types: ['Files'], files: [{ name: 'Rules.PDF', size: 500 }] },
    preventDefault() { this.prevented = true; },
  };
  events.dragover(event);
  assert.ok(classes.has('is-dragging'));
  events.drop(event);
  assert.ok(event.prevented);
  assert.equal(input.files, event.dataTransfer.files);
  assert.equal(status.textContent, 'Selected: Rules.PDF');
  assert.ok(!classes.has('is-dragging'));

  event.dataTransfer.files = [{ name: 'Rules.txt', size: 500 }];
  events.drop(event);
  assert.equal(input.files.length, 0);
  assert.equal(status.textContent, 'Choose one PDF file.');

  input.files = [{ name: 'Browsed.pdf', size: 500 }];
  events.change();
  assert.equal(status.textContent, 'Selected: Browsed.pdf');

  event.dataTransfer.files = [{ name: 'Large.pdf', size: 200 * 1024 * 1024 }];
  events.drop(event);
  assert.equal(status.textContent, 'Selected: Large.pdf');
  event.dataTransfer.files = [{ name: 'Too large.pdf', size: 250 * 1024 * 1024 + 1 }];
  events.drop(event);
  assert.equal(input.files.length, 0);
  assert.equal(status.textContent, 'Choose a PDF of 250 MB or smaller.');
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness(count = 1, active = true) {
  const nodes = Array.from({length: count}, (_, i) => ({
    dataset: {rulebookIndex: String(i).padStart(32, '0'), indexActive: String(active)},
    textContent: 'Search index · Queued', hidden: !active,
  }));
  const timers = [], calls = [], responses = [];
  const document = {hidden: false, querySelectorAll: () => nodes};
  vm.runInNewContext(fs.readFileSync('static/rulebook-index-status.js', 'utf8'), {
    document, URLSearchParams,
    setTimeout: (fn, delay) => { assert.equal(delay, 5000); timers.push(fn); },
    fetch: async url => {
      calls.push(url);
      const data = responses.shift();
      if (data instanceof Error) throw data;
      return {ok: true, status: 200, headers: {get: () => 'application/json'}, json: async () => data, ...data?.response};
    },
  });
  async function poll(data) {
    responses.push(data);
    assert.ok(timers.length, 'Expected a pending status refresh');
    await timers.shift()();
    await new Promise(setImmediate);
  }
  return {nodes, timers, calls, document, poll};
}

test('progress refreshes automatically, then disappears and stops polling when ready', async () => {
  const h = harness();
  const key = h.nodes[0].dataset.rulebookIndex;
  await h.poll({[key]: {status: 'indexing', text: 'Search index · Indexing · 25 / 100 pages'}});
  assert.equal(h.nodes[0].textContent, 'Search index · Indexing · 25 / 100 pages');
  assert.equal(h.nodes[0].hidden, false);
  await h.poll({[key]: {status: 'ready', text: 'Search index · Ready'}});
  assert.equal(h.nodes[0].hidden, true);
  assert.equal(h.nodes[0].textContent, '');
  assert.equal(h.timers.length, 0);
  assert.equal(harness(1, false).timers.length, 0);
});

test('network failures retain progress; failed indexing stays visible without continuous polling', async () => {
  const h = harness();
  const key = h.nodes[0].dataset.rulebookIndex;
  await h.poll(new Error('offline'));
  assert.equal(h.nodes[0].textContent, 'Search index · Queued');
  assert.equal(h.timers.length, 1);
  await h.poll({[key]: {status: 'failed', text: 'Search index · Failed'}});
  assert.equal(h.nodes[0].textContent, 'Search index · Failed');
  assert.equal(h.nodes[0].hidden, false);
  assert.equal(h.timers.length, 0);
});

test('deleted or newly inaccessible documents lose their status', async () => {
  const h = harness();
  await h.poll({});
  assert.equal(h.nodes[0].hidden, true);
  assert.equal(h.timers.length, 0);
});

test('status requests are batched and hidden tabs make no requests', async () => {
  const h = harness(60);
  h.document.hidden = true;
  await h.poll({});
  assert.equal(h.calls.length, 0);
  h.document.hidden = false;
  // The unused response from the hidden poll and the next response both hide
  // their batch, as every requested document has been removed.
  await h.poll({});
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls.map(url => new URL(url, 'https://app.test').searchParams.getAll('book').length), [50, 10]);
  assert.ok(h.nodes.every(node => node.hidden));
  assert.equal(h.timers.length, 0);
});

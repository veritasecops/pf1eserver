const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const links = [], frames = [], calls = [];
  let mutation;
  function node(href = '') {
    return {
      href, isConnected: true, hidden: false, nextSibling: null, textContent: '',
      closest() { return this.picker || null; },
      get nextElementSibling() { return this.nextSibling; },
      matches() { return this.citation === true; },
      setAttribute() { this.citation = true; },
      after(child) { this.nextSibling = child; child.owner = this; },
      remove() { if (this.owner?.nextSibling === this) this.owner.nextSibling = null; },
    };
  }
  vm.runInNewContext(fs.readFileSync('static/aon-sources.js', 'utf8'), {
    URL, URLSearchParams,
    document: {body: {}, querySelectorAll: () => links, createElement: () => node()},
    MutationObserver: class { constructor(fn) { mutation = fn; } observe() {} },
    requestAnimationFrame: fn => frames.push(fn),
    fetch: async url => {
      calls.push(url);
      const urls = new URL(url, 'https://app.test').searchParams.getAll('url');
      return {ok: true, headers: {get: () => 'application/json'},
        json: async () => Object.fromEntries(urls.map(url => [url, url.includes('Second') ? 'Book Two pg. 2' : 'Book One pg. 1']))};
    },
  });
  async function settle() {
    for (let count = 0; count < 5; count++) {
      frames.splice(0).forEach(fn => fn());
      await new Promise(setImmediate);
    }
  }
  return {links, node, calls, settle, mutate: () => mutation()};
}

test('dynamic links update sources, reuse server citations, and clear removed references', async () => {
  const h = harness();
  const link = h.node('https://www.aonprd.com/Test.aspx?ItemName=First');
  const existing = h.node(); existing.citation = true;
  link.after(existing);
  h.links.push(link);
  await h.settle();
  assert.equal(link.nextSibling, existing);
  assert.equal(existing.textContent, 'Source: Book One pg. 1');
  assert.equal(h.calls.length, 1);
  link.href = 'https://www.aonprd.com/Test.aspx?ItemName=Second';
  h.mutate(); await h.settle();
  assert.equal(link.nextSibling.textContent, 'Source: Book Two pg. 2');
  h.mutate(); await h.settle();
  assert.equal(h.calls.length, 2);
  link.hidden = true;
  h.mutate(); await h.settle();
  assert.equal(link.nextSibling, null);
  link.hidden = false;
  link.href = 'https://example.com/custom';
  h.mutate(); await h.settle();
  assert.equal(link.nextSibling, null);
});

test('dropdown sources sit outside the picker and requests stay bounded', async () => {
  const h = harness();
  for (let i = 0; i < 42; i++) {
    const link = h.node(`https://www.aonprd.com/Test.aspx?ItemName=${i}`);
    link.picker = h.node();
    h.links.push(link);
  }
  await h.settle();
  assert.equal(h.calls.length, 3);
  assert.ok(h.calls.every(url => new URL(url, 'https://app.test').searchParams.getAll('url').length <= 20));
  assert.ok(h.links.every(link => link.picker.nextSibling.textContent === 'Source: Book One pg. 1'));
  assert.ok(h.links.every(link => link.nextSibling === null));
});

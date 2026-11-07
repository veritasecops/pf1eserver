(() => {
  // Citations also follow links inserted or changed by the sheet's pickers.
  const cache = new Map();
  const citations = new Map();
  let scheduled = false;

  function isAoN(value) {
    try {
      const url = new URL(value);
      return ['aonprd.com', 'www.aonprd.com'].includes(url.hostname);
    } catch { return false; }
  }

  function display(link, source) {
    const target = link.closest('.dropdown-picker') || link;
    let citation = citations.get(link);
    if (!citation && target.nextElementSibling?.matches('small[data-reference-source]')) {
      citation = target.nextElementSibling;
      citations.set(link, citation);
    }
    if (!source || !link.isConnected || link.hidden) {
      citation?.remove();
      citations.delete(link);
      return;
    }
    if (!citation) {
      citation = document.createElement('small');
      citation.className = 'aon-source secondary-text';
      citation.setAttribute('data-reference-source', '');
      citations.set(link, citation);
    }
    const text = `Source: ${source}`;
    if (citation.textContent !== text) citation.textContent = text;
    if (target.nextSibling !== citation) target.after(citation);
  }

  async function retrieve(urls) {
    try {
      const params = new URLSearchParams();
      urls.forEach(url => params.append('url', url));
      const response = await fetch(`/api/reference-sources?${params}`, {headers: {Accept: 'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
      const sources = await response.json();
      for (const url of urls) cache.set(url, typeof sources[url] === 'string' ? sources[url] : '');
      schedule();
    } catch { /* A citation lookup must not interrupt character editing. */ }
  }

  function refresh() {
    scheduled = false;
    for (const link of citations.keys()) {
      if (!link.isConnected || !isAoN(link.href)) display(link, '');
    }
    const pending = new Set();
    document.querySelectorAll('a[href]').forEach(link => {
      const url = link.href;
      if (!isAoN(url)) return;
      if (cache.has(url)) {
        if (cache.get(url) !== null) display(link, cache.get(url));
      }
      else {
        cache.set(url, null);
        pending.add(url);
      }
    });
    const urls = [...pending];
    // Keep query strings below proxy request-line limits.
    for (let start = 0; start < urls.length; start += 20) retrieve(urls.slice(start, start + 20));
  }

  function schedule() {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(refresh);
    }
  }
  new MutationObserver(schedule).observe(document.body, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['href', 'hidden'],
  });
  schedule();
})();

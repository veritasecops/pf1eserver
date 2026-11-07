(() => {
  const nodes = [...document.querySelectorAll('[data-rulebook-index]')];
  async function refresh() {
    const active = nodes.filter(node => node.dataset.indexActive === 'true');
    if (!active.length) return;
    if (!document.hidden) {
      try {
        for (let start = 0; start < active.length; start += 50) {
          const batch = active.slice(start, start + 50);
          const params = new URLSearchParams();
          batch.forEach(node => params.append('book', node.dataset.rulebookIndex));
          const response = await fetch(`/rulebooks/index-status?${params}`, {
            headers: {Accept: 'application/json'},
          });
          if (response.redirected || response.status === 401 || response.status === 403) return;
          if (!response.ok) break;
          if (!response.headers.get('content-type')?.includes('application/json')) return;
          const statuses = await response.json();
          for (const node of batch) {
            const status = statuses[node.dataset.rulebookIndex];
            const complete = !status || status.status === 'ready';
            node.hidden = complete;
            const text = complete ? '' : status.text;
            if (node.textContent !== text) node.textContent = text;
            node.dataset.indexActive = status && ['queued', 'indexing'].includes(status.status) ? 'true' : 'false';
          }
        }
      } catch { /* Retain the last progress value and retry on the next poll. */ }
    }
    if (nodes.some(node => node.dataset.indexActive === 'true')) setTimeout(refresh, 5000);
  }
  if (nodes.some(node => node.dataset.indexActive === 'true')) setTimeout(refresh, 5000);
})();

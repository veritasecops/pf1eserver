(() => {
  const factors={cp:1,sp:10,gp:100,pp:1000};
  function balance(amounts) {
    let copper=0;
    for (const [coin,factor] of Object.entries(factors)) {
      const value=String(amounts[coin] ?? '').trim();
      const amount=value===''?0:Number(value);
      if (!Number.isFinite(amount)||amount<0||amount>1000000000) return {error:'Enter nonnegative coin amounts up to 1,000,000,000.'};
      copper+=amount*factor;
    }
    if (Math.abs(copper-Math.round(copper))>0.000001) return {error:'Treasure must total a whole number of copper pieces.'};
    return {copper:Math.round(copper),gp:Math.round(copper)/100};
  }
  if (typeof module!=='undefined'&&module.exports) module.exports={balance};
  if (typeof document==='undefined') return;
  const form=document.getElementById('deluxe-form');
  const treasure=document.getElementById('character-treasure');
  const dialog=document.getElementById('add-treasure-dialog');
  if (!form||!treasure||!dialog) return;
  const inputs=Object.fromEntries(Object.keys(factors).map(coin=>[coin,form.elements.namedItem('money.'+coin)]));
  const triggers=document.querySelectorAll('[data-open-treasure]');
  let opener=document.getElementById('open-treasure');
  for (const trigger of triggers) trigger.addEventListener('click',()=>{opener=trigger;treasure.showModal();});
  document.getElementById('close-treasure').addEventListener('click',()=>{if(!busy)treasure.close();});
  treasure.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  treasure.addEventListener('close',()=>opener.focus());
  const add=document.getElementById('add-treasure');
  const addForm=document.getElementById('add-treasure-form');
  const error=document.getElementById('add-treasure-error');
  const submit=addForm.querySelector('[type="submit"]');
  let busy=false;
  let pending=null;
  const amounts=()=>Object.fromEntries(Object.entries(inputs).map(([coin,input])=>[coin,input.value]));
  function refresh() {
    const result=balance(amounts());
    document.getElementById('open-treasure').setAttribute('aria-label',result.error?'Open Treasure, Check Coin Amounts':'Open Treasure, '+result.gp.toLocaleString(undefined,{maximumFractionDigits:2})+' gp On Hand');
    document.getElementById('treasure-total').textContent=result.error?'Check coin amounts':result.gp.toLocaleString(undefined,{maximumFractionDigits:2})+' gp';
    const validation=document.getElementById('treasure-validation');
    validation.textContent=result.error||'';
    validation.hidden=!result.error;
    for (const button of treasure.querySelectorAll('[data-remove-coins]')) button.disabled=!Number(inputs[button.dataset.removeCoins].value);
    for (const cell of document.querySelectorAll('[data-print-coin]')) cell.textContent=inputs[cell.dataset.printCoin].value||'0';
  }
  async function changeCoins(action, coin, amount, message) {
    if (busy) return;
    const signature = JSON.stringify([action, coin, amount]);
    if (pending?.signature !== signature) {
      const body = new FormData();
      for (const [key, value] of Object.entries({action, coin, amount})) body.set(key, value);
      pending = {signature, body};
      body.set('request_id', Array.from(crypto.getRandomValues(new Uint8Array(16)),
        byte => byte.toString(16).padStart(2, '0')).join(''));
    }
    busy = true;
    add.disabled = true;
    submit.disabled = true;
    message.hidden = true;
    const controller = new AbortController();
    let timeout;
    try {
      await window.PathkeeperSheet.flush();
      const {body} = pending;
      if (!body.has('version')) body.set('version', form.elements.namedItem('version').value);
      body.set('csrf', form.elements.namedItem('csrf').value);
      timeout = setTimeout(() => controller.abort(), 15000);
      const response = await fetch(form.action.replace(/\/play-sheet$/, '') + '/treasure',
        {method: 'POST', body, signal: controller.signal, headers: {Accept: 'application/json'}});
      if (response.redirected) throw new Error('Sign in again before changing treasure.');
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 422) pending = null;
        throw new Error(result.detail || 'The coin operation could not be saved.');
      }
      window.PathkeeperSheet.applyPurchase(result);
      pending = null;
      if (dialog.open) dialog.close();
    } catch (failure) {
      message.textContent = failure.name === 'AbortError' || failure instanceof TypeError
        ? 'The response was lost. Retry the same operation or reload the sheet.' : failure.message;
      message.hidden = false;
    } finally {
      clearTimeout(timeout);
      busy = false;
      add.disabled = false;
      submit.disabled = false;
    }
  }

  treasure.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-coins]');
    if (!button || busy || !window.confirm(button.getAttribute('aria-label') + '?')) return;
    changeCoins('remove', button.dataset.removeCoins, '', document.getElementById('treasure-validation'));
  });
  form.addEventListener('sheetpurchase', refresh);
  add.addEventListener('click', () => {
    addForm.reset();
    error.hidden = true;
    dialog.showModal();
    addForm.elements.namedItem('amount').focus();
  });
  document.getElementById('cancel-add-treasure').addEventListener('click', () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => add.focus());
  addForm.addEventListener('submit', event => {
    event.preventDefault();
    changeCoins('add', addForm.elements.namedItem('coin').value, addForm.elements.namedItem('amount').value, error);
  });
  const dock=document.querySelector('.character-sheet-dock');
  if (dock && typeof ResizeObserver!=='undefined') {
    const observer=new ResizeObserver(()=>{
      document.documentElement.style.setProperty('--sheet-dock-height',Math.ceil(dock.getBoundingClientRect().height+16)+'px');
    });
    observer.observe(dock);
  }
  refresh();
})();

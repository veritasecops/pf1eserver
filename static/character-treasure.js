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
  document.getElementById('close-treasure').addEventListener('click',()=>treasure.close());
  treasure.addEventListener('close',()=>opener.focus());
  const add=document.getElementById('add-treasure');
  const undo=document.getElementById('undo-treasure');
  const addForm=document.getElementById('add-treasure-form');
  const error=document.getElementById('add-treasure-error');
  let previous=null;
  let changing=false;
  const amounts=()=>Object.fromEntries(Object.entries(inputs).map(([coin,input])=>[coin,input.value]));
  function refresh() {
    const result=balance(amounts());
    document.getElementById('open-treasure').setAttribute('aria-label',result.error?'Open treasure, check coin amounts':'Open treasure, '+result.gp.toLocaleString(undefined,{maximumFractionDigits:2})+' gp on hand');
    document.getElementById('treasure-total').textContent=result.error?'Check coin amounts':result.gp.toLocaleString(undefined,{maximumFractionDigits:2})+' gp';
    const validation=document.getElementById('treasure-validation');
    validation.textContent=result.error||'';
    validation.hidden=!result.error;
    for (const input of Object.values(inputs)) input.setCustomValidity(result.error||'');
    for (const button of treasure.querySelectorAll('[data-remove-coins]')) button.disabled=!Number(inputs[button.dataset.removeCoins].value);
    for (const cell of document.querySelectorAll('[data-print-coin]')) cell.textContent=inputs[cell.dataset.printCoin].value||'0';
    undo.hidden=!previous;
  }
  function write(values,remember=true) {
    const before=amounts();
    for (const [coin,value] of Object.entries(values)) inputs[coin].value=value;
    previous=remember?before:null;
    changing=true;
    refresh();
    // One regular sheet autosave records the complete coin operation.
    inputs[Object.keys(values)[0]].dispatchEvent(new Event('input',{bubbles:true}));
    changing=false;
  }
  treasure.addEventListener('click',event=>{
    const button=event.target.closest('[data-remove-coins]');
    if (button) write({[button.dataset.removeCoins]:'0'});
  });
  form.addEventListener('input',event=>{
    if (!/^money\.(cp|sp|gp|pp)$/.test(event.target.name||'')) return;
    if (!changing) previous=null;
    refresh();
  });
  form.addEventListener('sheetpurchase',()=>{previous=null;refresh();});
  undo.addEventListener('click',()=>{if(previous)write(previous,false);});
  add.addEventListener('click',()=>{
    addForm.reset();
    error.hidden=true;
    dialog.showModal();
    addForm.elements.namedItem('amount').focus();
  });
  document.getElementById('cancel-add-treasure').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>add.focus());
  addForm.addEventListener('submit',event=>{
    event.preventDefault();
    const coin=addForm.elements.namedItem('coin').value;
    const amount=Number(addForm.elements.namedItem('amount').value);
    const current=Number(inputs[coin]?.value||0);
    if (!Object.hasOwn(factors,coin)||!Number.isInteger(amount)||amount<1||!Number.isFinite(current)||current<0||current+amount>1000000000) {
      error.textContent='Enter a positive whole number that keeps this balance within 1,000,000,000 coins.';
      error.hidden=false;
      return;
    }
    write({[coin]:String(current+amount)});
    dialog.close();
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

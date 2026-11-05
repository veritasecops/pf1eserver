(() => {
  const factors={pp:1000,gp:100,sp:10,cp:1};
  function proceeds(values) {
    const coins={};let copper=0;
    for(const [coin,factor] of Object.entries(factors)) {
      const raw=String(values[coin]??'').trim();
      if(!/^\d+$/.test(raw)) throw new Error('Enter nonnegative whole coin amounts.');
      const amount=Number(raw);
      if(!Number.isSafeInteger(amount)||amount>1000000000) throw new Error('Enter up to 1,000,000,000 of each coin.');
      coins[coin]=amount;copper+=amount*factor;
    }
    return {coins,copper};
  }
  if(typeof module!=='undefined'&&module.exports) module.exports={proceeds};
  if(typeof document==='undefined')return;
  const sheet=document.getElementById('deluxe-form'),dialog=document.getElementById('equipment-disposal-dialog');
  if(!sheet||!dialog)return;
  const form=document.getElementById('equipment-disposal-form'),fieldset=document.getElementById('equipment-sale-coins');
  const submit=document.getElementById('confirm-equipment-disposal'),error=document.getElementById('equipment-disposal-error');
  const coinInputs=Object.fromEntries([...form.querySelectorAll('[data-sale-coin]')].map(input=>[input.dataset.saleCoin,input]));
  let opener=null,selection=null,job=null,busy=false,uncertain=false;
  const coins=()=>Object.fromEntries(Object.entries(coinInputs).map(([coin,input])=>[coin,input.value]));
  function refresh() {
    for(const button of sheet.querySelectorAll('[data-dispose-equipment]')) {
      const name=sheet.elements.namedItem(`${button.dataset.kind}.${button.dataset.row}.name`).value.trim();
      button.hidden=!name;
      button.setAttribute('aria-label',`${button.dataset.disposeEquipment==='sell'?'Sell':'Remove'} ${name||button.dataset.kind}`);
    }
  }
  form.addEventListener('input',()=>{
    try{document.getElementById('equipment-sale-total').textContent=`Total: ${(proceeds(coins()).copper/100).toLocaleString(undefined,{maximumFractionDigits:2})} gp`;}
    catch(e){document.getElementById('equipment-sale-total').textContent=e.message;}
  });
  sheet.addEventListener('click',async event=>{
    const button=event.target.closest('[data-dispose-equipment]');
    if(!button||busy)return;
    busy=true;button.disabled=true;
    try {
      await window.PathkeeperSheet.flush();
      const {kind,row,disposeEquipment:action}=button.dataset;
      const name=sheet.elements.namedItem(`${kind}.${row}.name`).value.trim();
      if(!name)throw new Error('This entry is empty.');
      selection={kind,row,action,version:sheet.elements.namedItem('version').value};
      const quantity=sheet.elements.namedItem(`${kind}.${row}.quantity`).value||'1';
      opener=button;job=null;uncertain=false;error.hidden=true;
      for(const input of Object.values(coinInputs)){input.value='0';input.disabled=false;}
      fieldset.hidden=action!=='sell';fieldset.disabled=action!=='sell';
      document.getElementById('equipment-sale-total').textContent='Total: 0 gp';
      document.getElementById('equipment-disposal-title').textContent=action==='sell'?'Sell item':'Remove item';
      document.getElementById('equipment-disposal-summary').textContent=`${name} × ${quantity}. This removes the entire entry and its linked gear row.${action==='remove'?' Treasure stays unchanged.':' Enter the total agreed sale price below.'}`;
      submit.textContent=action==='sell'?'Sell item':'Remove item';submit.disabled=false;
      sheet.inert=true;dialog.showModal();
    } catch(e) {
      const panel=document.getElementById('sheet-autosave-errors');panel.textContent=e.message;panel.hidden=false;sheet.inert=false;
    } finally {busy=false;button.disabled=false;}
  });
  async function dispose(event) {
    event.preventDefault();if(busy)return;
    error.hidden=true;
    if(!job) {
      try {
        const amounts=selection.action==='sell'?proceeds(coins()):{coins:{},copper:0};
        if(selection.action==='sell'&&!amounts.copper)throw new Error('Enter sale proceeds, or use Remove without payment.');
        const body=new FormData();body.set('csrf',sheet.elements.namedItem('csrf').value);
        for(const [key,value] of Object.entries(selection))body.set(key,value);
        body.set('request_id',Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''));
        body.set('coins',JSON.stringify(amounts.coins));job=body;
      } catch(e){error.textContent=e.message;error.hidden=false;return;}
    }
    busy=true;submit.disabled=true;fieldset.disabled=true;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch(sheet.action.replace(/\/play-sheet$/,'')+'/equipment/dispose',{method:'POST',body:job,credentials:'same-origin',signal:controller.signal,headers:{Accept:'application/json'}});
      if(response.redirected||!response.headers.get('content-type')?.includes('application/json')){uncertain=true;throw new Error('Reload the sheet to check inventory and access.');}
      const result=await response.json();
      if(!response.ok) {
        uncertain=response.status!==422;
        if(!uncertain)job=null;
        throw new Error(result.detail||'The item action could not be saved.');
      }
      window.PathkeeperSheet.applyPurchase(result);uncertain=false;dialog.close();
    } catch(e) {
      if(e.name==='AbortError'||e instanceof TypeError){uncertain=true;error.textContent='The response was lost. Retry to check the same action safely, or close to reload inventory.';}
      else error.textContent=e.message;
      error.hidden=false;submit.textContent=uncertain?'Retry same action':selection.action==='sell'?'Sell item':'Remove item';
    } finally {clearTimeout(timeout);busy=false;submit.disabled=false;fieldset.disabled=uncertain||selection.action!=='sell';}
  }
  form.addEventListener('submit',dispose);
  for(const id of ['close-equipment-disposal','cancel-equipment-disposal'])document.getElementById(id).addEventListener('click',()=>{if(!busy)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{
    sheet.inert=false;
    if(uncertain){location.reload();return;}
    (opener&&!opener.hidden?opener:document.getElementById('add-sheet-weapons')).focus();
  });
  for(const event of ['input','change','sheetpurchase'])sheet.addEventListener(event,refresh);
  refresh();
})();

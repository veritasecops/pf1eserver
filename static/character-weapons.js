(() => {
  const form=document.getElementById('deluxe-form');
  const button=document.getElementById('add-sheet-weapons');
  const dialog=document.getElementById('sheet-weapon-picker');
  if (!form || !button || !dialog) return;
  const endpoint=form.action.replace(/\/play-sheet$/,'')+'/equipment';
  const picker=new PathkeeperWeaponPicker(dialog);
  const showError=message=>{
    const panel=document.getElementById('sheet-autosave-errors');
    panel.textContent=message;
    panel.hidden=false;
  };
  async function request(options={}) {
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch(endpoint,{...options,signal:controller.signal,credentials:'same-origin',headers:{Accept:'application/json'}});
      if (response.redirected) throw new Error('Sign in again before purchasing.');
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The server did not return a purchase response. Reload to check inventory.');
      const data=await response.json();
      if (!response.ok) throw new Error(data.detail || 'The purchase could not be saved.');
      return data;
    } catch(error) {
      if (error.name==='AbortError' || error instanceof TypeError) throw new Error('The purchase response was lost. Retry the same selection, or reload to check inventory.');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  button.addEventListener('click',async()=>{
    button.disabled=true;
    try {
      await PathkeeperSheet.flush();
      const state=await request();
      if (PathkeeperSheet.hasPending || String(state.version)!==form.elements.namedItem('version').value) throw new Error('The sheet changed. Wait for edits to save, or reload, before opening the picker.');
      let job=null;
      picker.open({...state,returnFocus:()=>button.focus(),onSubmit:async payload=>{
        const serialized=JSON.stringify(payload);
        if (!job || job.payload!==serialized) job={payload:serialized,version:state.version,request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('')};
        const body=new FormData();
        body.set('csrf',form.elements.namedItem('csrf').value);
        body.set('catalog_version',state.catalog_version);
        for (const [name,value] of Object.entries(job)) body.set(name,value);
        const result=await request({method:'POST',body});
        PathkeeperSheet.applyPurchase(result);
        document.getElementById('character-backpack')?.dispatchEvent(
          new CustomEvent('backpackchange', {detail: result.backpack}));

      }});
    } catch(error) { showError(error.message); }
    finally { button.disabled=false; }
  });
})();

(() => {
  const dialog=document.getElementById('character-dice-dialog');
  const open=document.getElementById('open-character-dice');
  if(!dialog||!open)return;
  const find=id=>dialog.querySelector('#'+id);
  const roll=find('floating-roll'),count=find('floating-dice-count'),modifier=find('floating-dice-modifier');
  const result=find('floating-dice-result');
  let dice=null,sides=20,busy=false;
  const history=[];
  const label=record=>{const r=record.result;return `${r.dice.length}d${r.sides}${r.modifier?(r.modifier>0?'+':'')+r.modifier:''}: ${r.dice.join(' + ')}${r.modifier?' '+(r.modifier>0?'+':'−')+' '+Math.abs(r.modifier):''} = ${r.total}`;};
  function message(title,detail){const strong=document.createElement('strong'),span=document.createElement('span');strong.textContent=title;span.className='secondary-text';span.textContent=detail;result.replaceChildren(strong,span);}
  function update(){roll.textContent=`Roll ${count.value||1}d${sides}`;}
  open.addEventListener('click',()=>{dialog.showModal();if(!dice)dice=new PathkeeperDice(find('floating-dice-canvas'));roll.focus();});
  find('close-character-dice').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{dice?.stop();open.focus();});
  for(const button of dialog.querySelectorAll('[data-die]'))button.addEventListener('click',()=>{
    sides=Number(button.dataset.die);
    for(const item of dialog.querySelectorAll('[data-die]'))item.setAttribute('aria-pressed',String(item===button));
    update();
  });
  count.addEventListener('input',update);
  async function doRoll(){
    if(busy||!count.reportValidity()||!modifier.reportValidity())return;
    busy=true;
    const controls=dialog.querySelectorAll('[data-die],#floating-roll,#floating-dice-count,#floating-dice-modifier');
    for(const control of controls)control.disabled=true;
    dice.spin(sides,Number(count.value));message('Rolling…','Gathering your dice.');
    const body=new FormData();body.set('csrf',dialog.dataset.csrf);body.set('sides',sides);body.set('count',count.value);body.set('modifier',modifier.value);
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch(dialog.dataset.endpoint,{method:'POST',body,credentials:'same-origin',headers:{Accept:'application/json'},signal:controller.signal});
      if(response.redirected)throw new Error('Sign in again before rolling.');
      if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('The roll could not be completed. Try again when connected.');
      const record=await response.json();
      if(!response.ok)throw new Error(record.detail||'The roll could not be completed.');
      if (dialog.open) dice.settle(record);
      message(record.result.total,label(record));
      history.unshift(record);history.splice(12);
      const items=history.map(item=>{const li=document.createElement('li');li.textContent=label(item);return li;});
      find('character-roll-history').replaceChildren(...items);find('character-roll-count').textContent=history.length;
    }catch(error){dice.stop();message('Roll unavailable',error.name==='AbortError'?'The request timed out. Try again.':error.message);}
    finally{clearTimeout(timeout);busy=false;for(const control of controls)control.disabled=false;}
  }
  roll.addEventListener('click',doRoll);
  for(const input of [count,modifier])input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();doRoll();}});
})();

(() => {
  const form=document.getElementById('deluxe-form');
  if (!form) return;
  const tooltip=document.createElement('div');
  tooltip.id='sheet-formula-tooltip';
  tooltip.className='sheet-formula-tooltip';
  tooltip.setAttribute('role','tooltip');
  tooltip.setAttribute('popover','manual');
  tooltip.hidden=true;
  document.body.append(tooltip);
  let active=null;
  function describe(input,enabled) {
    const ids=new Set((input.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean));
    if(enabled)ids.add(tooltip.id);else ids.delete(tooltip.id);
    if(ids.size)input.setAttribute('aria-describedby',[...ids].join(' '));else input.removeAttribute('aria-describedby');
  }
  function hide() {
    if(active)describe(active,false);
    active=null;
    if(tooltip.matches(':popover-open'))tooltip.hidePopover();
    tooltip.hidden=true;
  }
  function position() {
    if(!active)return;
    const rect=active.getBoundingClientRect();
    const width=tooltip.getBoundingClientRect().width;
    const height=tooltip.getBoundingClientRect().height;
    const left=Math.max(8,Math.min(rect.left,innerWidth-width-8));
    const top=rect.bottom+8+height<=innerHeight-8?rect.bottom+8:Math.max(8,rect.top-height-8);
    tooltip.style.left=left+'px';tooltip.style.top=top+'px';
  }
  function show(input) {
    if(!input?.dataset.sheetFormula)return;
    if(active && active!==input)describe(active,false);
    active=input;
    tooltip.textContent=input.dataset.sheetFormula;
    tooltip.hidden=false;
    if(typeof tooltip.showPopover==='function') {
      if(!tooltip.matches(':popover-open'))tooltip.showPopover();
    } else (input.closest('dialog')||document.body).append(tooltip);
    describe(input,true);
    position();
  }
  function update(input,text) {
    input.removeAttribute('title');
    if(text)input.dataset.sheetFormula=text;else delete input.dataset.sheetFormula;
    if(active===input) {if(text)show(input);else hide();}
  }
  for(const input of form.querySelectorAll('[data-sheet-formula]'))update(input,input.dataset.sheetFormula);
  window.PathkeeperFormulas={update};
  form.addEventListener('pointerover',event=>show(event.target.closest('[data-sheet-formula]')));
  form.addEventListener('pointerout',event=>{
    if(event.target!==active || tooltip.contains(event.relatedTarget))return;
    hide();
  });
  form.addEventListener('focusin',event=>{hide();show(event.target.closest('[data-sheet-formula]'));});
  form.addEventListener('focusout',hide);
  tooltip.addEventListener('pointerleave',hide);
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && active) {hide();event.preventDefault();event.stopPropagation();}
  },true);
  document.addEventListener('scroll',event=>{if(!tooltip.contains(event.target))hide();},true);
  window.addEventListener('resize',hide);
})();

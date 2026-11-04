(() => {
  function update(select){
    const label=select.closest('label');
    const link=label?.querySelector('[data-deity-reference]');
    if(!link)return;
    const url=select.selectedOptions[0]?.dataset.descriptionUrl||'';
    let safe=false;
    try{safe=['http:','https:'].includes(new URL(url).protocol);}catch{}
    link.hidden=!safe;
    if(safe){link.href=url;link.setAttribute('aria-label','Description of '+select.selectedOptions[0].textContent);}
    else link.removeAttribute('href');
  }
  document.addEventListener('change',event=>{if(event.target.matches('[data-deity-select]'))update(event.target);});
  function refresh(){for(const select of document.querySelectorAll('[data-deity-select]'))update(select);}
  refresh();
  const stage=document.getElementById('pw-stage');
  if(stage)new MutationObserver(refresh).observe(stage,{childList:true,subtree:true});
})();

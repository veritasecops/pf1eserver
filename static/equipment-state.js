(() => {
  const form=document.getElementById('deluxe-form');
  const boot=document.getElementById('sheet-equipment-groups');
  if(!form||!boot)return;
  let groups=JSON.parse(boot.textContent);
  const input=key=>form.elements.namedItem(key);
  function refresh(){
    for(const checkbox of form.querySelectorAll('[data-equipment-equipped]')){
      const name=input(checkbox.name.replace(/\.equipped$/,'.name'));
      checkbox.disabled=!name?.value.trim();
      if(checkbox.disabled)checkbox.checked=false;
    }
  }
  function valid(group){
    return group.fields.every(key=>input(key.replace(/\.equipped$/,'.name'))?.value===group.labels[key]);
  }
  form.addEventListener('input',event=>{
    const checkbox=event.target;
    if(checkbox.matches('[data-equipment-equipped]')){
      for(const group of groups)if(group.fields.includes(checkbox.name)&&valid(group)){
        for(const key of group.fields)if(input(key))input(key).checked=checkbox.checked;
      }
    }
    if(/^(weapon|armor|gear)\.\d+\.name$/.test(checkbox.name||''))refresh();
  });
  window.PathkeeperEquipment={update(state,nextGroups){
    if(Array.isArray(nextGroups))groups=nextGroups;
    for(const [key,value] of Object.entries(state||{}))if(input(key))input(key).checked=value==='1';
    refresh();
  }};
  refresh();
})();

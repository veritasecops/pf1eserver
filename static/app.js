const toast = message => {const el=document.querySelector('#toast');el.textContent=message;el.hidden=false;setTimeout(()=>el.hidden=true,4500);};
document.querySelectorAll('[data-origin-path]').forEach(el=>{el.value=location.origin+el.dataset.originPath;});
document.addEventListener('click',async event=>{
 const opener=event.target.closest('[data-open-dialog]');
 if(opener){document.getElementById(opener.dataset.openDialog)?.showModal();return;}
 const toggle=event.target.closest('[data-toggle-menu]');if(toggle){document.querySelector('#sidebar')?.classList.toggle('open');return;}
 const sidebar=document.querySelector('#sidebar.open');if(sidebar&&!event.target.closest('#sidebar'))sidebar.classList.remove('open');
 const copy=event.target.closest('[data-copy]');if(copy){const field=document.getElementById(copy.dataset.copy);try{if(navigator.clipboard){await navigator.clipboard.writeText(field.value);toast('Invitation copied.');}else{field.focus();field.select();toast('Link selected. Press Ctrl+C or Command+C to copy.');}}catch{field.focus();field.select();toast('Link selected. Copy it with your keyboard.');}}
 const reveal=event.target.closest('.reveal-password');if(reveal){const input=reveal.parentElement.querySelector('input[type=password],input[type=text]');input.type=input.type==='password'?'text':'password';reveal.textContent=input.type==='password'?'Show password':'Hide password';}
 if(event.target.closest('[data-print]'))window.print();
 if(event.target.closest('[data-download-recovery]')){const values=[...document.querySelectorAll('#recovery-codes code')].map(el=>el.textContent);const text='Pathkeeper recovery codes\nEach code works once. Store privately.\n\n'+values.join('\n')+'\n';const url=URL.createObjectURL(new Blob([text],{type:'text/plain'}));const link=document.createElement('a');link.href=url;link.download='pathkeeper-recovery-codes.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
});
function roleOptions(){const role=document.querySelector('#role-select'),required=document.querySelector('#totp-required');if(!role||!required)return;required.disabled=role.value==='admin';if(required.disabled)required.checked=true;}
document.querySelector('#role-select')?.addEventListener('change',roleOptions);roleOptions();
function emailProviderOptions(){const provider=document.querySelector('#email-provider');if(!provider)return;document.querySelectorAll('[data-email-provider]').forEach(panel=>{panel.hidden=panel.dataset.emailProvider!==provider.value;});}
document.querySelector('#email-provider')?.addEventListener('change',emailProviderOptions);emailProviderOptions();
document.addEventListener('submit',event=>{if(event.target.method?.toLowerCase()!=='post')return;event.target.querySelectorAll('button[type=submit],button:not([type])').forEach(button=>{button.disabled=true;});});
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelector('#sidebar')?.classList.remove('open');if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){const search=document.querySelector('#help-search');if(search){event.preventDefault();search.focus();}}});

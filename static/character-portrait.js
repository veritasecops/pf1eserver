(() => {
  const editor = document.querySelector('[data-portrait-editor]');
  if (!editor) return;
  const input = editor.querySelector('input[type="file"]');
  const remove = editor.querySelector('[data-portrait-remove]');
  const status = document.getElementById('portrait-status');
  let busy = false;
  const message = text => { status.hidden = !text; status.textContent = text; };
  const resized = async file => {
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) throw new Error('Choose a JPG, PNG, or WebP image.');
    if (file.size > 10 * 1024 * 1024) throw new Error('Choose an image smaller than 10 MB.');
    const image = await createImageBitmap(file);
    try {
      const scale = Math.min(1,768 / Math.max(image.width,image.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1,Math.round(image.width*scale));
      canvas.height = Math.max(1,Math.round(image.height*scale));
      const context = canvas.getContext('2d');
      context.fillStyle = '#fff8e9';
      context.fillRect(0,0,canvas.width,canvas.height);
      context.drawImage(image,0,0,canvas.width,canvas.height);
      for (const quality of [0.9,0.8,0.65,0.5,0.35]) {
        const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/jpeg',quality));
        if (blob && blob.size <= 200 * 1024) return blob;
      }
      throw new Error('This image is too detailed. Try a smaller image.');
    } finally { image.close(); }
  };
  const upload = async file => {
    if (busy) return;
    busy = true;
    input.disabled = true;
    remove.disabled = true;
    message(file ? 'Saving character image…' : 'Removing character image…');
    try {
      const form = new FormData();
      form.set('csrf',editor.dataset.csrf);
      if (file) form.set('portrait',await resized(file),'portrait.jpg');
      const response = await fetch(editor.dataset.endpoint + (file ? '' : '/remove'), {
        method:'POST',body:form,credentials:'same-origin',headers:{Accept:'application/json'}
      });
      if (response.redirected) throw new Error('Sign in again before changing the image.');
      let result;
      try { result = await response.json(); } catch { throw new Error('The image could not be saved. Try again.'); }
      if (!response.ok) throw new Error(result.detail || 'The image could not be saved.');
      for (const image of document.querySelectorAll('[data-character-portrait]')) {
        image.hidden = !result.url;
        if (result.url) image.src = result.url;
        else image.removeAttribute('src');
      }
      for (const placeholder of document.querySelectorAll('[data-character-portrait-placeholder]')) placeholder.hidden = Boolean(result.url);
      remove.hidden = !result.url;
      document.dispatchEvent(new CustomEvent('characterportraitchange',{detail:{url:result.url}}));
      message(file ? 'Character image saved.' : 'Character image removed.');
    } catch (error) { message(error.message || 'Choose a valid character image.'); }
    finally { busy = false; input.disabled = false; remove.disabled = false; input.value = ''; }
  };
  input.addEventListener('change',() => { if (input.files[0]) upload(input.files[0]); });
  remove.addEventListener('click',() => upload(null));
  window.addEventListener('beforeunload',event => { if (busy) { event.preventDefault(); event.returnValue = ''; } });
})();

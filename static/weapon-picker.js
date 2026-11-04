(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const money = cp => (cp / 100).toLocaleString(undefined, {maximumFractionDigits:2}) + ' gp';
  const categories = {'unarmed':'Unarmed','light':'Light melee','one-handed':'One-handed melee','two-handed':'Two-handed melee','ranged':'Ranged','ammunition':'Ammunition'};
  const armorCategories = {light:'Light armor',medium:'Medium armor',heavy:'Heavy armor',shield:'Shields',extra:'Armor extras'};
  const isArmor = item => ['armor','shield'].includes(item.kind) || item.category === 'extra';
  const isWeapon = item => item.kind === 'weapon' || item.category === 'ammunition';
  function copper(value) {
    const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(String(value).trim());
    if (!match) return null;
    const amount = Number(match[1]) * 100 + Number((match[2] || '').padEnd(2,'0'));
    return Number.isSafeInteger(amount) && amount <= 100000000 ? amount : null;
  }
  function summarize({equipment, quantities, prices, owned, budget, maxNewWeapons, maxNewArmor}) {
    let units = 0, total = 0;
    const errors = [], selected = {}, agreed = {};
    for (const [id,raw] of Object.entries(quantities)) {
      if (raw === '' || Number(raw) === 0) continue;
      const item = equipment[id], quantity = Number(raw);
      if (!item || !(isWeapon(item) || isArmor(item)) || item.enabled === false || !Number.isInteger(quantity) || quantity < 1 || quantity + (owned[id] || 0) > 100) {
        errors.push('Use whole quantities within the 100-unit inventory limit.');
        continue;
      }
      units += quantity;
      selected[id] = quantity;
      const price = item.cost === null ? copper(prices[id] ?? '') : item.cost;
      if (price === null || price === undefined) errors.push(`Enter the agreed unit price for ${item.name} (up to two decimal places).`);
      else {
        total += quantity * price;
        if (item.cost === null) agreed[id] = price;
      }
    }
    const newWeapons=Object.keys(selected).filter(id=>equipment[id].kind==='weapon'&&!(owned[id]>0)).length;
    if (maxNewWeapons !== undefined && newWeapons > maxNewWeapons) errors.push(`Choose at most ${maxNewWeapons} new weapon types; the sheet has six weapon rows.`);
    const newArmor=Object.keys(selected).filter(id=>['armor','shield'].includes(equipment[id].kind)&&!(owned[id]>0)).length;
    if (maxNewArmor !== undefined && newArmor > maxNewArmor) errors.push(`Choose at most ${maxNewArmor} new armor types; the sheet has six armor rows.`);
    if (total > budget) errors.push('This selection exceeds the available treasure. Reduce the quantities.');
    return {units,total,remaining:budget-total,errors,quantities:selected,prices:agreed};
  }
  class WeaponPicker {
    constructor(dialog) {
      this.dialog = dialog;
      this.busy = false;
      dialog.addEventListener('cancel', event => { if (this.busy) event.preventDefault(); });
      dialog.addEventListener('close', () => this.options?.returnFocus?.());
      dialog.addEventListener('input', event => {
        const input = event.target;
        if (input.dataset.weaponQuantity) this.quantities[input.dataset.weaponQuantity] = input.value;
        if (input.dataset.weaponPrice) this.prices[input.dataset.weaponPrice] = input.value;
        if (input.name === 'weapon-search') this.renderResults();
        this.update();
      });
      dialog.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target.name === 'weapon-search') event.preventDefault();
        if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key) && event.target.hasAttribute('data-equipment-tab')) {
          event.preventDefault();
          const next=event.key==='Home'?'weapons':event.key==='End'?'armor':this.tab==='weapons'?'armor':'weapons';
          if (!this.busy) {this.selectTab(next);this.dialog.querySelector(`[data-equipment-tab="${next}"]`).focus();}
        }
        if (event.key === 'Escape') { event.preventDefault(); if (!this.busy) dialog.close(); }
      });
      dialog.addEventListener('change', event => {
        if (['weapon-group','weapon-type','selected-only'].includes(event.target.name)) this.renderResults();
      });
      dialog.addEventListener('click', event => {
        const tab=event.target.closest('[data-equipment-tab]');
        if (tab && !this.busy) this.selectTab(tab.dataset.equipmentTab);
        if (event.target.closest('[data-cancel-weapons]') && !this.busy) dialog.close();
      });
      dialog.addEventListener('submit', async event => {
        event.preventDefault();
        if (this.busy) return;
        const cart = this.summary();
        if (!cart.units || cart.errors.length) return;
        this.busy = true;
        this.update();
        this.error.textContent = '';
        try {
          await this.options.onSubmit({quantities:cart.quantities,prices:cart.prices});
          dialog.close();
        } catch (error) {
          this.error.textContent = error.message || 'The purchase could not be saved. Check your connection and try again.';
          this.error.hidden = false;
        } finally {
          this.busy = false;
          this.update();
        }
      });
    }
    open(options) {
      if (this.dialog.open) return;
      this.options = options;
      this.quantities = {};
      this.prices = Object.fromEntries(Object.entries(options.prices || {}).map(([id,cp]) => [id,(cp / 100).toFixed(2)]));
      this.busy = false;
      this.dialog.innerHTML = `<form class="pw-weapon-picker-form"><header class="pw-weapon-picker-heading"><div><h2 id="pw-weapon-picker-title">Add Equipment</h2><p id="pw-weapon-picker-description">Choose quantities, then add the selection to your inventory.</p></div><button class="icon-button" type="button" data-cancel-weapons aria-label="Close equipment selection">×</button></header><div class="pw-equipment-tabs" role="tablist" aria-label="Equipment catalogs"><button type="button" id="equipment-weapons-tab" role="tab" data-equipment-tab="weapons" aria-controls="equipment-results" aria-selected="true">Weapons</button><button type="button" id="equipment-armor-tab" role="tab" data-equipment-tab="armor" aria-controls="equipment-results" aria-selected="false" tabindex="-1">Armor</button></div><div id="equipment-results" role="tabpanel" aria-labelledby="equipment-weapons-tab"><div class="pw-weapon-filters"><label>Search equipment by name<input type="search" name="weapon-search" placeholder="Longsword, crossbow…" autocomplete="off"></label><label data-weapon-proficiency>Proficiency<select name="weapon-group"><option value="">All proficiencies</option><option value="simple">Simple</option><option value="martial">Martial</option><option value="exotic">Exotic</option></select></label><label><span data-equipment-type-label>Weapon type</span><select name="weapon-type"><option value="">All types</option>${Object.entries(categories).map(([id,label]) => `<option value="${id}">${label}</option>`).join('')}</select></label><label class="pw-weapon-selected-only"><input type="checkbox" name="selected-only">Selected only</label></div><p class="pw-weapon-result-count" role="status"></p><div class="pw-weapon-results" tabindex="0" role="region" aria-label="Available weapons"><table><thead><tr><th scope="col" data-equipment-name-heading>Weapon</th><th scope="col">Unit price</th><th scope="col">Add quantity</th><th scope="col">Line total</th></tr></thead><tbody></tbody></table></div></div><footer class="pw-weapon-picker-footer"><div class="pw-weapon-totals" aria-live="polite"></div><p class="pw-weapon-validation" role="status"></p><p class="pw-weapon-submit-error" role="alert" hidden></p><div class="pw-weapon-picker-actions"><button class="button" type="button" data-cancel-weapons>Cancel</button><button class="button primary" type="submit">Add selected equipment</button></div></footer></form>`;
      this.error = this.dialog.querySelector('.pw-weapon-submit-error');
      this.selectTab('weapons');
      this.update();
      this.dialog.showModal();
      this.dialog.querySelector('[name="weapon-search"]').focus({preventScroll:true});
    }
    summary() {
      return summarize({equipment:this.options.equipment,quantities:this.quantities,prices:this.prices,owned:this.options.owned,budget:this.options.budget,maxNewWeapons:this.options.maxNewWeapons,maxNewArmor:this.options.maxNewArmor});
    }
    selectTab(tab) {
      this.tab=tab;
      const armor=tab==='armor';
      for(const button of this.dialog.querySelectorAll('[data-equipment-tab]')) {
        const selected=button.dataset.equipmentTab===tab;
        button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;
      }
      this.dialog.querySelector('#equipment-results').setAttribute('aria-labelledby',`equipment-${tab}-tab`);
      this.dialog.querySelector('[data-weapon-proficiency]').hidden=armor;
      this.dialog.querySelector('[name="weapon-group"]').value='';
      this.dialog.querySelector('[name="weapon-search"]').value='';
      this.dialog.querySelector('[name="weapon-search"]').placeholder=armor?'Chain shirt, shield…':'Longsword, crossbow…';
      this.dialog.querySelector('[data-equipment-type-label]').textContent=armor?'Armor type':'Weapon type';
      this.dialog.querySelector('[data-equipment-name-heading]').textContent=armor?'Armor / shield':'Weapon';
      this.dialog.querySelector('.pw-weapon-results').setAttribute('aria-label',armor?'Available armor':'Available weapons');
      this.dialog.querySelector('[name="weapon-type"]').innerHTML='<option value="">All types</option>'+Object.entries(armor?armorCategories:categories).map(([id,label])=>`<option value="${id}">${label}</option>`).join('');
      this.renderResults();
    }
    renderResults() {
      const query = this.dialog.querySelector('[name="weapon-search"]').value.trim().toLocaleLowerCase();
      const group = this.dialog.querySelector('[name="weapon-group"]').value;
      const type = this.dialog.querySelector('[name="weapon-type"]').value;
      const selected = this.dialog.querySelector('[name="selected-only"]').checked;
      const items = Object.entries(this.options.equipment).filter(([id,item]) => (this.tab==='armor'?isArmor(item):isWeapon(item)) && item.enabled !== false && (!group || item.group === group) && (!type || item.category === type) && (!selected || Number(this.quantities[id]) > 0) && [item.name,...(item.aliases || [])].some(name => name.toLocaleLowerCase().includes(query))).sort((a,b) => a[1].name.localeCompare(b[1].name));
      this.dialog.querySelector('tbody').innerHTML = items.map(([id,item]) => {
        const available = 100 - (this.options.owned[id] || 0);
        const fixedPrice = item.cost === null && (this.options.owned[id] || 0) > 0 && this.options.prices?.[id] !== undefined;
        const price = item.cost === null && !fixedPrice ? `<label class="pw-weapon-price-label">Agreed unit price (gp)<input type="number" data-weapon-price="${escape(id)}" min="0" max="1000000" step="0.01" value="${escape(this.prices[id] ?? '')}" aria-label="Agreed unit price for ${escape(item.name)}"></label><span class="secondary-text">Published: ${escape(item.cost_text || 'Special price')}</span>` : money(item.cost === null ? this.options.prices[id] : item.cost);
        const armor=isArmor(item);
        const details=armor?`${armorCategories[item.category]} · Bonus ${item.bonus_text || (item.kind==='shield'?item.shield:item.armor) || '—'} · Max Dex ${item.max_dex===100?'—':item.max_dex} · Check ${item.acp} · Spell failure ${item.spell_failure_text || '—'} · Speed ${item.speed_30_text || '—'}/${item.speed_20_text || '—'} · ${item.weight_text || (item.weight ?? '—')+' lb.'}`:`${item.group || ''} · ${categories[item.category] || 'Weapon'} · ${item.damage || '—'}`;
        return `<tr data-weapon-row="${escape(id)}"><th scope="row"><strong>${escape(item.name)}</strong><span class="secondary-text">${escape(details)}</span>${item.url ? `<a href="${escape(item.url)}" target="_blank" rel="noopener noreferrer">${armor?'Armor':'Weapon'} reference ↗</a>` : ''}${this.options.owned[id] ? `<span class="secondary-text">Already in inventory: ${this.options.owned[id]}</span>` : ''}</th><td>${price}</td><td><input type="number" data-weapon-quantity="${escape(id)}" min="0" max="${available}" step="1" value="${escape(this.quantities[id] || 0)}" aria-label="Add quantity of ${escape(item.name)}" ${available ? '' : 'disabled'}></td><td data-weapon-line="${escape(id)}">${money(0)}</td></tr>`;
      }).join('') || '<tr><td colspan="4">No matching equipment. Try another name or type.</td></tr>';
      this.dialog.querySelector('.pw-weapon-result-count').textContent = `${items.length} matching ${items.length === 1 ? 'entry' : 'entries'}`;
      this.update();
    }
    update() {
      if (!this.options) return;
      const cart = this.summary();
      for (const cell of this.dialog.querySelectorAll('[data-weapon-line]')) {
        const id = cell.dataset.weaponLine, item = this.options.equipment[id];
        const price = item.cost === null ? copper(this.prices[id] ?? '') : item.cost;
        const quantity = Number(this.quantities[id] || 0);
        cell.textContent = price === null && quantity ? 'Price required' : money((price || 0) * (Number.isInteger(quantity) && quantity > 0 ? quantity : 0));
      }
      this.dialog.querySelector('.pw-weapon-totals').innerHTML = [['Available treasure',money(this.options.budget)],['Selected quantity',cart.units],['Purchase total',money(cart.total)],['Treasure after purchase',money(cart.remaining)]].map(([label,value]) => `<div><span>${label}</span><strong>${escape(value)}</strong></div>`).join('');
      this.dialog.querySelector('.pw-weapon-validation').textContent = cart.errors[0] || '';
      const submit = this.dialog.querySelector('[type="submit"]');
      submit.disabled = this.busy || !cart.units || cart.errors.length > 0;
      submit.textContent = this.busy ? 'Adding equipment…' : 'Add selected equipment';
      for (const input of this.dialog.querySelectorAll('input,select,button[data-cancel-weapons],button[data-equipment-tab]')) {
        input.disabled = this.busy || input.hasAttribute('data-weapon-quantity') && Number(input.max) === 0;
      }
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {copper,summarize};
  if (typeof window !== 'undefined') window.PathkeeperWeaponPicker = WeaponPicker;
})();

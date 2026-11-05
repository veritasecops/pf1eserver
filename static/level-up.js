(() => {
  const form = document.getElementById('level-up-form');
  if (!form) return;

  const steps = [...form.querySelectorAll('[data-level-step]')];
  const back = form.querySelector('[data-level-back]');
  const next = form.querySelector('[data-level-next]');
  const finish = form.querySelector('[data-level-submit]');
  const position = form.querySelector('[data-level-position]');
  const budget = form.querySelector('[data-rank-budget]');
  const ranks = [...form.querySelectorAll('[name^="rank_"]')];
  let step = 0;

  const show = (index, focus = true) => {
    step = index;
    steps.forEach((section, i) => { section.hidden = i !== step; });
    position.textContent = `Step ${step + 1} of ${steps.length}`;
    position.hidden = false;
    back.hidden = step === 0;
    next.hidden = step === steps.length - 1;
    finish.hidden = !next.hidden;
    if (focus) {
      const heading = steps[step].querySelector('h2');
      heading.tabIndex = -1;
      heading.focus();
    }
  };

  const countRanks = () => {
    const base = Number(form.dataset.ranks);
    const score = Number(form.dataset.int);
    const before = Math.max(1, base + Math.floor((score - 10) / 2));
    const after = Math.max(1, base + Math.floor((score - 10 + (form.elements.ability?.value === 'int' ? 1 : 0)) / 2));
    const favored = Number(form.elements.favored.value === 'skill');
    const total = after + (after - before) * (Number(form.dataset.target) - 1) + Number(form.dataset.human) + favored;
    const assigned = ranks.reduce((sum, input) => sum + Number(input.value), 0);
    budget.textContent = `${assigned} of ${total} skill ranks allocated.`;
    return assigned === total;
  };

  const forward = () => {
    const invalid = [...steps[step].querySelectorAll('input, select, textarea')].find(input => !input.checkValidity());
    if (invalid) return invalid.reportValidity();
    if (steps[step].contains(budget) && !countRanks()) {
      budget.tabIndex = -1;
      return budget.focus();
    }
    show(step + 1);
  };
  back.addEventListener('click', () => show(step - 1));
  next.addEventListener('click', forward);
  form.addEventListener('input', countRanks);
  form.addEventListener('invalid', event => {
    const invalidStep = steps.findIndex(section => section.contains(event.target));
    if (invalidStep !== -1 && steps[invalidStep].hidden) show(invalidStep, false);
  }, true);
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !next.hidden && event.target.matches('input:not([type="checkbox"])')) {
      event.preventDefault();
      forward();
    }
  });
  countRanks();
  show(0, false);
})();

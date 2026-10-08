(() => {
  const key = 'recipe-library-cart-v1';
  let entries = [];
  const message = document.querySelector('#cart-status');
  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(key));
      entries = Array.isArray(saved) ? saved.filter(e => typeof e.recipe_id === 'string' && typeof e.title === 'string' && Number.isFinite(e.servings) && e.servings > 0 && (e.variation === null || typeof e.variation === 'string')) : [];
      // Entries saved before customization existed have no amounts or swaps.
      for (const entry of entries) {
        entry.amounts = isPlain(entry.amounts) ? entry.amounts : {};
        entry.substitutions = isPlain(entry.substitutions) ? entry.substitutions : {};
      }
    } catch { entries = []; message.textContent = 'Saved recipe cart could not be loaded.'; }
  }
  function isPlain(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function signature(entry) {
    const sorted = obj => JSON.stringify(Object.keys(obj).sort().map(k => [k, obj[k]]));
    return [entry.recipe_id, entry.variation, sorted(entry.amounts), sorted(entry.substitutions)].join('|');
  }
  function render() {
    document.querySelector('#cart-count').textContent = entries.length;
    const list = document.querySelector('#cart-entries'); list.replaceChildren();
    document.querySelector('#cart-empty').hidden = entries.length > 0;
    for (const entry of entries) {
      const row = document.createElement('div'); row.className = 'cart-row';
      const link = document.createElement('a');
      link.href = typeof entry.href === 'string' && entry.href.startsWith('/recipe/') ? entry.href
        : '/recipe/' + encodeURIComponent(entry.recipe_id) + (entry.variation ? '?variation=' + encodeURIComponent(entry.variation) : '');
      link.textContent = entry.title; row.append(link);
      const label = document.createElement('label'); label.textContent = 'Servings';
      const input = document.createElement('input'); input.type = 'number'; input.min = '0.1'; input.step = 'any'; input.value = entry.servings;
      input.setAttribute('aria-label', `Servings for ${entry.title}`);
      input.addEventListener('change', () => {
        const value = Number(input.value);
        if (!Number.isFinite(value) || value <= 0) { input.value = entry.servings; message.textContent = 'Enter a positive number of servings.'; return; }
        entry.servings = value; persist();
      });
      label.append(input); row.append(label);
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove ${entry.title}`);
      remove.addEventListener('click', () => { entries = entries.filter(e => e !== entry); persist(); render(); });
      row.append(remove); list.append(row);
    }
  }
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(entries)); }
    catch { message.textContent = 'Browser storage is unavailable; this cart will not survive navigation.'; }
    document.dispatchEvent(new Event('cartchange'));
  }
  window.recipeCart = {
    selections: () => entries.map(({recipe_id, servings, variation, amounts, substitutions}) => ({recipe_id, servings, variation, amounts, substitutions})),
    recipes: () => entries.map(e => ({...e})),
    add: entry => {
      const existing = entries.find(e => signature(e) === signature(entry));
      if (existing) Object.assign(existing, {servings: entry.servings, title: entry.title, href: entry.href});
      else entries.push(entry);
      message.textContent = `${entry.title} ${existing ? 'updated in' : 'added to'} your recipe cart.`;
      persist(); render(); document.querySelector('#recipe-cart').open = true;
    }
  };
  load(); render();
  window.addEventListener('storage', event => { if (event.key === key || event.key === null) { load(); render(); document.dispatchEvent(new Event('cartchange')); } });
  document.querySelectorAll('.add-recipe-form').forEach(form => form.addEventListener('submit', event => {
    if (event.submitter && event.submitter.id === 'update-amounts') return;
    event.preventDefault();
    const servings = Number(form.querySelector('.cart-servings').value);
    if (!Number.isFinite(servings) || servings <= 0) return;
    const version = form.querySelector('.cart-version');
    const variation = version ? version.value || null : form.dataset.variation || null;
    const title = version && variation ? `${form.dataset.title} — ${version.selectedOptions[0].textContent}` : form.dataset.title;
    let amounts = {}, substitutions = {};
    try { amounts = JSON.parse(form.dataset.amounts || '{}'); substitutions = JSON.parse(form.dataset.substitutions || '{}'); } catch {}
    window.recipeCart.add({recipe_id: form.dataset.recipe, title, servings, variation, amounts, substitutions, href: form.dataset.href || null});
  }));
})();

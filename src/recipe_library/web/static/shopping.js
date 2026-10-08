const storageKey = 'recipe-library-shopping-v1';
let state = null;
const status = document.querySelector('#status');
function save() {
  try { localStorage.setItem(storageKey, JSON.stringify(state)); }
  catch { status.textContent = 'Browser storage is unavailable. Download the list to keep it.'; }
}
function render() {
  document.querySelector('#list-section').hidden = !state;
  if (!state) return;
  const warnings = document.querySelector('#warnings');
  warnings.replaceChildren();
  for (const warning of state.warnings) {
    const p = document.createElement('p'); p.className = 'warning'; p.textContent = warning; warnings.append(p);
  }
  const list = document.querySelector('#items'); list.replaceChildren();
  for (const item of state.items) {
    const row = document.createElement('article'); row.className = 'shopping-item';
    const title = document.createElement('strong'); title.textContent = item.text; row.append(title);
    const source = document.createElement('p'); source.className = 'muted'; source.textContent = item.sources.join(' · '); row.append(source);
    const controls = document.createElement('div'); controls.className = 'item-controls';
    for (const [field, text] of [['have', 'Already have'], ['checked', 'Got it']]) {
      const label = document.createElement('label'); label.className = 'pick';
      const check = document.createElement('input'); check.type = 'checkbox'; check.checked = Boolean(item[field]);
      check.setAttribute('aria-label', `${text}: ${item.ingredient}`);
      check.addEventListener('change', () => { item[field] = check.checked; save(); });
      label.append(check, document.createTextNode(text)); controls.append(label);
    }
    row.append(controls); list.append(row);
  }
}
try {
  const saved = JSON.parse(localStorage.getItem(storageKey));
  if (saved && Array.isArray(saved.items) && Array.isArray(saved.warnings) && saved.items.every(i => typeof i.text === 'string' && Array.isArray(i.sources))) state = saved;
} catch { status.textContent = 'The previous saved list could not be loaded. Generate a new list to continue.'; }
render();
document.querySelector('#selection-form').addEventListener('submit', async event => {
  event.preventDefault();
  const selections = window.recipeCart.selections();
  const signature = currentSignature();
  const stagedRecipes = window.recipeCart.recipes();
  if (!selections.length) { status.textContent = 'Choose at least one recipe.'; return; }
  const button = document.querySelector('#generate'); button.disabled = true; status.textContent = 'Building your list…';
  try {
    const response = await fetch('/shopping/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({selections, include_optional: document.querySelector('#optional').checked})});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check your servings and recipe selections.');
    state = {...data, signature, stagedRecipes}; status.textContent = `${state.items.length} items ready. Review any quantities marked as needed.`;
    save(); render(); updateStaleness();
  } catch (error) { status.textContent = `Could not generate the list: ${error.message}. Your previous list is preserved.`; }
  finally { button.disabled = false; }
});
document.querySelector('#export').addEventListener('click', () => {
  if (!state || state.signature !== currentSignature()) return;
  const lines = ['Shopping list', '', 'Recipes:', ...state.stagedRecipes.map(r => `${r.title} — ${r.servings} servings`), '', ...state.warnings, '', ...state.items.filter(item => !item.have).map(item => `${item.checked ? '[x]' : '[ ]'} ${item.text}`)];
  const url = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = 'shopping-list.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function currentSignature() {
  return JSON.stringify({selections: window.recipeCart.selections(), optional: document.querySelector('#optional').checked});
}
function updateStaleness() {
  const stale = Boolean(state && state.signature !== currentSignature());
  document.querySelector('#stale-warning').hidden = !stale;
  document.querySelector('#export').disabled = stale;
}
document.addEventListener('cartchange', updateStaleness);
document.querySelector('#optional').addEventListener('change', updateStaleness);
updateStaleness();

(() => {
  // Live result count on the filter form; submitting still works without JavaScript.
  const form = document.querySelector('#recipe-filters');
  if (!form) return;
  const button = form.querySelector('.show-results');
  let timer = null;
  let request = 0;
  async function updateCount() {
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of [...params]) if (!value) params.delete(key);
    params.set('limit', '1');
    const current = ++request;
    try {
      const response = await fetch('/recipes?' + params);
      if (current !== request) return;
      if (!response.ok) { button.textContent = 'Check Filters'; return; }
      const { total } = await response.json();
      button.textContent = `Show ${total} Recipe${total === 1 ? '' : 's'}`;
    } catch { if (current === request) button.textContent = 'Show Recipes'; }
  }
  form.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(updateCount, 250); });
  form.addEventListener('change', event => {
    if (event.target.name === 'category') form.requestSubmit();
  });
  form.addEventListener('submit', () => {
    // Keep URLs short: drop empty fields.
    for (const field of form.querySelectorAll('input, select')) if (!field.value) field.disabled = true;
    setTimeout(() => form.querySelectorAll(':disabled').forEach(field => { field.disabled = false; }));
  });
})();

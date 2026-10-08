(() => {
  // Choosing a swap or product applies it right away; amount edits wait for Update Amounts.
  const form = document.querySelector('#customize');
  const update = document.querySelector('#update-amounts');
  if (!form || !update) return;
  document.querySelectorAll('.swap-select, .product-select').forEach(select =>
    select.addEventListener('change', () => form.requestSubmit(update)));
  // Type to narrow a long product list; the list stays scrollable.
  document.querySelectorAll('.product-filter').forEach(input => {
    const select = document.getElementById(input.getAttribute('aria-controls'));
    input.addEventListener('input', () => {
      const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      for (const option of select.options) {
        option.hidden = Boolean(option.value) && !words.every(w => option.textContent.toLowerCase().includes(w));
      }
    });
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      const match = [...select.options].find(o => o.value && !o.hidden);
      if (match) { select.value = match.value; select.dispatchEvent(new Event('change')); }
    });
  });
})();

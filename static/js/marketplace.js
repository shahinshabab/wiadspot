// Location picker and cost estimate for the ad submission form.
(function () {
  var dataEl = document.getElementById('spotData');
  if (!dataEl) return;
  var spots = JSON.parse(dataEl.textContent);
  var selected = new Set(JSON.parse(document.getElementById('selectedSpots').textContent));
  var list = document.getElementById('spotList');
  var inputs = document.getElementById('spotInputs');
  var search = document.getElementById('spotSearch');
  var count = document.getElementById('spotCount');
  var estimate = document.getElementById('estimate');
  var total = document.getElementById('id_total_budget');
  var SHOW_LIMIT = 150;

  function money(v) { return '₹' + Number(v).toFixed(2).replace(/\.00$/, ''); }

  function matches(spot, q) {
    return !q || (spot.name + ' ' + spot.town).toLowerCase().indexOf(q) !== -1;
  }

  function syncInputs() {
    inputs.textContent = '';
    selected.forEach(function (id) {
      var input = document.createElement('input');
      input.type = 'hidden'; input.name = 'spots'; input.value = id;
      inputs.appendChild(input);
    });
    updateEstimate();
  }

  function render() {
    var q = search.value.trim().toLowerCase();
    var shown = spots.filter(function (s) { return matches(s, q); });
    list.textContent = '';
    shown.slice(0, SHOW_LIMIT).forEach(function (spot) {
      var label = document.createElement('label');
      label.className = 'mp-spot';
      var box = document.createElement('input');
      box.type = 'checkbox'; box.className = 'form-check-input'; box.checked = selected.has(spot.id);
      box.addEventListener('change', function () {
        if (box.checked) selected.add(spot.id); else selected.delete(spot.id);
        syncInputs(); updateCount(shown.length);
      });
      var text = document.createElement('span');
      text.className = 'mp-spot-text';
      var name = document.createElement('strong'); name.textContent = spot.name;
      var meta = document.createElement('small');
      meta.textContent = (spot.town || 'Kerala') + ' · ' + spot.kind;
      text.appendChild(name); text.appendChild(meta);
      var rate = document.createElement('span');
      rate.className = 'mp-rate';
      rate.textContent = spot.free ? 'Free' : money(spot.rate) + ' / user';
      label.appendChild(box); label.appendChild(text); label.appendChild(rate);
      list.appendChild(label);
    });
    if (!shown.length) {
      var empty = document.createElement('p');
      empty.className = 'text-muted'; empty.textContent = 'No matching towns or locations.';
      list.appendChild(empty);
    }
    updateCount(shown.length, shown);
  }

  var lastShown = spots;
  function updateCount(n, shown) {
    if (shown) lastShown = shown;
    count.textContent = selected.size + ' selected · ' + n + ' match' + (n === 1 ? '' : 'es') +
      (n > SHOW_LIMIT ? ' (showing ' + SHOW_LIMIT + ', refine your search)' : '');
  }

  function updateEstimate() {
    var paid = spots.filter(function (s) { return selected.has(s.id) && !s.free; });
    var budget = parseFloat(total && total.value);
    if (!selected.size) { estimate.textContent = ''; return; }
    if (!paid.length) { estimate.textContent = 'All chosen locations are yours: no per-user charge.'; return; }
    var rates = paid.map(function (s) { return parseFloat(s.rate); });
    var lo = Math.min.apply(null, rates), hi = Math.max.apply(null, rates);
    var text = 'Cost per user: ' + (lo === hi ? money(lo) : money(lo) + ' – ' + money(hi)) + '.';
    if (budget > 0 && hi > 0) {
      text += ' Your budget reaches roughly ' + Math.floor(budget / hi).toLocaleString() +
        (lo !== hi ? '–' + Math.floor(budget / lo).toLocaleString() : '') + ' users.';
    }
    estimate.textContent = text;
  }

  search.addEventListener('input', render);
  document.getElementById('selectShown').addEventListener('click', function () {
    var q = search.value.trim().toLowerCase();
    spots.filter(function (s) { return matches(s, q); }).slice(0, SHOW_LIMIT).forEach(function (s) { selected.add(s.id); });
    render(); syncInputs();
  });
  document.getElementById('clearAll').addEventListener('click', function () {
    selected.clear(); render(); syncInputs();
  });
  if (total) total.addEventListener('input', updateEstimate);
  // Keep Enter in the search box from submitting the whole form.
  search.addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });
  render(); syncInputs();
})();

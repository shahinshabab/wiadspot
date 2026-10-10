document.querySelectorAll("[data-table-search]").forEach((input) => {
  const table = document.getElementById(input.dataset.tableSearch);
  if (!table) return;
  input.addEventListener("input", () => {
    const query = input.value.trim().toLocaleLowerCase();
    const rows = [...table.querySelectorAll("[data-search-row]")];
    rows.forEach((row) => {
      row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
    });
    const empty = document.querySelector(
      `[data-search-empty="${input.dataset.tableSearch}"]`,
    );
    if (empty)
      empty.classList.toggle(
        "d-none",
        !rows.length || rows.some((row) => !row.hidden),
      );
  });
});

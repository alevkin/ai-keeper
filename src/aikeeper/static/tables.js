document.querySelectorAll("table[data-sortable] th").forEach((header, index) => {
  header.addEventListener("click", () => {
    const table = header.closest("table");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    const numeric = header.classList.contains("num");
    const direction = header.dataset.direction === "desc" ? "asc" : "desc";
    header.dataset.direction = direction;
    rows.sort((a, b) => {
      const leftCell = a.children[index];
      const rightCell = b.children[index];
      const left = numeric ? Number(leftCell.dataset.sortValue || 0) : leftCell.textContent.trim();
      const right = numeric ? Number(rightCell.dataset.sortValue || 0) : rightCell.textContent.trim();
      const result = numeric ? left - right : left.localeCompare(right);
      return direction === "asc" ? result : -result;
    });
    rows.forEach(row => table.tBodies[0].appendChild(row));
  });
});

// Shared helpers for both dashboard pages — results table, pagination, and
// the Today's Report modal are identical on index.html and domain-browser.html.

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Request failed: ${resp.status}`);
  }
  return resp.json();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "NA";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function renderResultsTable(container, results) {
  if (!results.length) {
    container.innerHTML = '<div class="empty-state">No items found.</div>';
    return;
  }

  const rows = results
    .map((item) => {
      const preview = escapeHtml(item.extractedContent || "NA");
      return `
        <tr>
          <td><a href="${escapeHtml(item.sourceURL)}" target="_blank" rel="noopener">${escapeHtml(item.internalRefid || "NA")}</a></td>
          <td><span class="badge">${escapeHtml(item.domainLabel || item.domain || "NA")}</span></td>
          <td class="content-cell">
            <div class="content-preview">${preview}</div>
            <span class="toggle-link" onclick="toggleContent(this)">Show more</span>
          </td>
          <td>${formatDate(item.createdAt)}</td>
          <td>${formatDate(item.updatedAt)}</td>
        </tr>`;
    })
    .join("");

  container.innerHTML = `
    <table class="results">
      <thead>
        <tr><th>Item ID</th><th>Domain</th><th>Extracted Content</th><th>Created At</th><th>Updated At</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function toggleContent(link) {
  const preview = link.previousElementSibling;
  const expanded = preview.classList.toggle("expanded");
  link.textContent = expanded ? "Show less" : "Show more";
}

function renderPagination(paginationEl, prevBtn, nextBtn, pageLabel, page, size, total, onChange) {
  const totalPages = Math.max(1, Math.ceil(total / size));
  paginationEl.style.display = total > 0 ? "flex" : "none";
  pageLabel.textContent = `Page ${page} of ${totalPages} (${total} total)`;
  prevBtn.disabled = page <= 1;
  nextBtn.disabled = page >= totalPages;
  prevBtn.onclick = () => onChange(page - 1);
  nextBtn.onclick = () => onChange(page + 1);
}

function wireReportModal() {
  const overlay = document.getElementById("report-overlay");
  const openBtn = document.getElementById("report-btn");
  const closeBtn = document.getElementById("report-close");
  const summaryEl = document.getElementById("report-summary");
  const rowsEl = document.getElementById("report-rows");
  const dateTitleEl = document.getElementById("report-date-title");

  async function open() {
    overlay.classList.add("open");
    summaryEl.innerHTML = "<p>Loading...</p>";
    rowsEl.innerHTML = "";
    try {
      const report = await fetchJSON("/api/dashboard/report/today");
      dateTitleEl.textContent = `Today's Report — ${report.reportDate}`;
      summaryEl.innerHTML = `
        <div class="stat"><div class="value">${report.totalItems}</div><div class="label">Total Items</div></div>
        <div class="stat"><div class="value">${report.totalNewToday}</div><div class="label">New Today</div></div>
        <div class="stat"><div class="value">${report.totalIngestedToday}</div><div class="label">Ingested Today</div></div>`;
      rowsEl.innerHTML = report.rows.length
        ? report.rows
            .map(
              (r) =>
                `<tr><td>${escapeHtml(r.displayName)}</td><td>${r.newToday}</td><td>${r.ingestedToday}</td><td>${r.totalItems}</td></tr>`
            )
            .join("")
        : '<tr><td colspan="4">No items indexed yet.</td></tr>';
    } catch (err) {
      summaryEl.innerHTML = `<p class="error-text">Failed to load report: ${escapeHtml(err.message)}</p>`;
    }
  }

  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", () => overlay.classList.remove("open"));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("open");
  });
}

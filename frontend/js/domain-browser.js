// Browse Domains: card grid with per-domain counts, click through to that domain's items.

const state = { page: 1, size: 10, domain: null };

const els = {
  gridView: document.getElementById("grid-view"),
  domainGrid: document.getElementById("domain-grid"),
  jobsView: document.getElementById("jobs-view"),
  jobsHeading: document.getElementById("jobs-heading"),
  backLink: document.getElementById("back-link"),
  statusLine: document.getElementById("status-line"),
  results: document.getElementById("results-container"),
  pagination: document.getElementById("pagination"),
  prevBtn: document.getElementById("prev-btn"),
  nextBtn: document.getElementById("next-btn"),
  pageLabel: document.getElementById("page-label"),
};

async function loadGrid() {
  els.domainGrid.innerHTML = "<p>Loading domains...</p>";
  try {
    const domains = await fetchJSON("/api/dashboard/domains");
    // Domains with items float to the top; empty ones are greyed out and disabled.
    domains.sort((a, b) => b.totalItems - a.totalItems);

    els.domainGrid.innerHTML = domains
      .map((d) => {
        const empty = d.totalItems === 0;
        return `
          <div class="domain-card ${empty ? "empty" : ""}" data-key="${escapeHtml(d.key)}" data-empty="${empty}">
            <h3>${escapeHtml(d.label)}</h3>
            <div class="domain-key">${escapeHtml(d.key)}</div>
            <div class="domain-count">${d.totalItems}</div>
            <div class="domain-count-label">Items indexed</div>
          </div>`;
      })
      .join("");

    els.domainGrid.querySelectorAll(".domain-card").forEach((card) => {
      if (card.dataset.empty === "true") return;
      card.addEventListener("click", () => openDomain(card.dataset.key, card.querySelector("h3").textContent));
    });
  } catch (err) {
    els.domainGrid.innerHTML = `<p>Failed to load domains: ${escapeHtml(err.message)}</p>`;
  }
}

function openDomain(key, label) {
  state.domain = key;
  state.page = 1;
  els.jobsHeading.textContent = label;
  els.gridView.style.display = "none";
  els.jobsView.classList.add("open");
  loadJobs();
}

function closeDomain() {
  state.domain = null;
  els.gridView.style.display = "block";
  els.jobsView.classList.remove("open");
}

async function loadJobs() {
  els.statusLine.classList.remove("error-text");
  els.statusLine.textContent = "Loading...";
  const params = new URLSearchParams({ page: state.page, size: state.size, domain: state.domain });
  try {
    const data = await fetchJSON(`/api/dashboard/search?${params}`);
    els.statusLine.textContent = `${data.total} item(s)`;
    renderResultsTable(els.results, data.results);
    renderPagination(els.pagination, els.prevBtn, els.nextBtn, els.pageLabel, data.page, data.size, data.total, (p) => {
      state.page = p;
      loadJobs();
    });
  } catch (err) {
    els.statusLine.classList.add("error-text");
    els.statusLine.textContent = `Failed to load: ${err.message}`;
    els.results.innerHTML = "";
    els.pagination.style.display = "none";
  }
}

els.backLink.addEventListener("click", closeDomain);

loadGrid();
wireReportModal();

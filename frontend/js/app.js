// Search Dashboard: keyword search, pagination, Today's Report.
// Domain-based browsing lives on domain-browser.html instead — this page is
// keyword-only.

const state = { page: 1, size: 10 };

const els = {
  q: document.getElementById("q"),
  searchBtn: document.getElementById("search-btn"),
  statusLine: document.getElementById("status-line"),
  results: document.getElementById("results-container"),
  pagination: document.getElementById("pagination"),
  prevBtn: document.getElementById("prev-btn"),
  nextBtn: document.getElementById("next-btn"),
  pageLabel: document.getElementById("page-label"),
  clearBtn: document.getElementById("clear-btn"),
};

function showIdleState() {
  els.statusLine.classList.remove("error-text");
  els.statusLine.textContent = "";
  els.results.innerHTML = "";
  els.pagination.style.display = "none";
}

async function runSearch() {
  els.statusLine.classList.remove("error-text");
  els.statusLine.textContent = "Searching...";
  const params = new URLSearchParams({ page: state.page, size: state.size, q: els.q.value.trim() });

  try {
    const data = await fetchJSON(`/api/dashboard/search?${params}`);
    els.statusLine.textContent = `${data.total} result(s)`;
    renderResultsTable(els.results, data.results);
    renderPagination(els.pagination, els.prevBtn, els.nextBtn, els.pageLabel, data.page, data.size, data.total, (p) => {
      state.page = p;
      runSearch();
    });
  } catch (err) {
    console.error("Search request failed", err);
    els.statusLine.classList.add("error-text");
    els.statusLine.textContent = `Search failed: ${err.message}`;
    els.results.innerHTML = "";
    els.pagination.style.display = "none";
  }
}

function requestSearch() {
  if (!els.q.value.trim()) {
    els.statusLine.classList.remove("error-text");
    els.statusLine.textContent = "Please enter a keyword.";
    els.results.innerHTML = "";
    els.pagination.style.display = "none";
    return;
  }
  state.page = 1;
  runSearch();
}

els.searchBtn.addEventListener("click", requestSearch);
els.q.addEventListener("keydown", (e) => {
  if (e.key === "Enter") requestSearch();
});
els.clearBtn.addEventListener("click", () => {
  els.q.value = "";
  state.page = 1;
  showIdleState();
});

showIdleState();
wireReportModal();

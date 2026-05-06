const state = {
  windowHours: 24,
  freshOnly: true,
  aiOnly: true,
  search: "",
  source: "all",
  type: "all",
  data: null
};

const els = {
  updated: document.querySelector("#last-updated"),
  sources: document.querySelector("#sources"),
  sourceCount: document.querySelector("#source-count"),
  sourceFilter: document.querySelector("#source-filter"),
  typeFilter: document.querySelector("#type-filter"),
  search: document.querySelector("#search"),
  freshOnly: document.querySelector("#fresh-only"),
  aiOnly: document.querySelector("#ai-only"),
  items: document.querySelector("#items"),
  resultCount: document.querySelector("#result-count"),
  signals: document.querySelector("#metric-signals"),
  priority: document.querySelector("#metric-priority"),
  stale: document.querySelector("#metric-stale")
};

function parseDate(value) {
  return new Date(value.replace(" ", "T") + "+08:00");
}

function formatDay(date) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

function formatTime(date) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function latestItemLabel(items) {
  if (!items.length) return "无更新";
  const latest = items
    .map((item) => parseDate(item.published_at))
    .sort((a, b) => b - a)[0];
  return `更新于 ${formatDay(latest)} ${formatTime(latest)}`;
}

function sourceStatusLabel(source, items) {
  if (items.length) return latestItemLabel(items);
  if (source.last_accessible) return `最新可访问 ${source.last_accessible.slice(5)}`;
  return "无更新";
}

function isFresh(item, now) {
  const published = parseDate(item.published_at);
  const ageHours = (now - published) / 36e5;
  return ageHours <= state.windowHours;
}

function isWindowVisible(item, now) {
  if (isFresh(item, now)) return true;
  return item.backfill && state.windowHours === 168;
}

function renderSources() {
  const now = parseDate(state.data.generated_at);
  const sources = state.data.sources;
  const itemsBySource = state.data.items
    .filter((item) => isWindowVisible(item, now))
    .reduce((groups, item) => {
      groups[item.source_id] = groups[item.source_id] || [];
      groups[item.source_id].push(item);
      return groups;
    }, {});
  const activeCount = sources.filter((source) => (itemsBySource[source.id] || []).length).length;
  els.sourceCount.textContent = `${activeCount}/${sources.length}`;
  els.sources.innerHTML = sources.map((source) => `
    <div class="source-row">
      <span class="status-dot ${(itemsBySource[source.id] || []).length ? "" : "warn"}"></span>
      <span>
        <span class="source-name">${source.name}</span>
        <span class="source-meta">${sourceStatusLabel(source, itemsBySource[source.id] || [])}</span>
      </span>
      <span class="source-score">${(itemsBySource[source.id] || []).length} 条</span>
    </div>
  `).join("");

  if (els.sourceFilter.options.length === 1) {
    const options = sources.map((source) => (
      `<option value="${source.id}">${source.name}</option>`
    )).join("");
    els.sourceFilter.insertAdjacentHTML("beforeend", options);
  }
}

function filterItems() {
  const now = parseDate(state.data.generated_at);
  const query = state.search.trim().toLowerCase();
  return state.data.items.filter((item) => {
    if (state.freshOnly && !isWindowVisible(item, now)) return false;
    if (state.aiOnly && item.ai_relevance !== "strong") return false;
    if (state.source !== "all" && item.source_id !== state.source) return false;
    if (state.type !== "all" && item.type !== state.type) return false;
    if (!query) return true;
    return [
      item.title,
      item.summary,
      item.source,
      item.tags.join(" ")
    ].join(" ").toLowerCase().includes(query);
  }).sort((a, b) => {
    if (b.priority !== a.priority) return b.priority - a.priority;
    return parseDate(b.published_at) - parseDate(a.published_at);
  });
}

function renderMetrics(filtered) {
  const now = parseDate(state.data.generated_at);
  const stale = state.data.items.filter((item) => !isFresh(item, now)).length;
  els.signals.textContent = filtered.length;
  els.priority.textContent = filtered.filter((item) => item.priority >= 90).length;
  els.stale.textContent = stale;
}

function renderItems() {
  const filtered = filterItems();
  renderMetrics(filtered);
  els.resultCount.textContent = `${filtered.length} 条`;

  if (!filtered.length) {
    els.items.innerHTML = '<div class="empty">当前过滤条件下没有内容。</div>';
    return;
  }

  els.items.innerHTML = filtered.map((item) => {
    const date = parseDate(item.published_at);
    const tags = item.tags.map((tag) => `<span class="tag">${tag}</span>`).join("");
    return `
      <article class="news-item">
        <div class="time-block">
          <strong>${formatTime(date)}</strong>
          <span>${formatDay(date)}</span>
        </div>
        <div>
          <a class="item-title" href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a>
          <p class="item-summary">${item.summary}</p>
          <div class="tag-row">
            <span class="tag">${item.source}</span>
            ${item.backfill ? '<span class="tag tag-watch">来源监控</span>' : ''}
            ${tags}
          </div>
        </div>
        <div class="priority ${item.priority >= 90 ? "hot" : ""}" title="信号分：单条内容的阅读优先级，综合时效性、AI 相关度、来源质量和新颖度，不代表事实正确性">
          <span>信号分</span>
          <strong>${item.priority}</strong>
        </div>
      </article>
    `;
  }).join("");
}

function bindEvents() {
  document.querySelectorAll("[data-window]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-window]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.windowHours = Number(button.dataset.window);
      renderSources();
      renderItems();
    });
  });

  els.search.addEventListener("input", (event) => {
    state.search = event.target.value;
    renderItems();
  });
  els.sourceFilter.addEventListener("change", (event) => {
    state.source = event.target.value;
    renderItems();
  });
  els.typeFilter.addEventListener("change", (event) => {
    state.type = event.target.value;
    renderItems();
  });
  els.freshOnly.addEventListener("change", (event) => {
    state.freshOnly = event.target.checked;
    renderItems();
  });
  els.aiOnly.addEventListener("change", (event) => {
    state.aiOnly = event.target.checked;
    renderItems();
  });
}

async function main() {
  const response = await fetch(`data/news.json?v=${Date.now()}`);
  state.data = await response.json();
  const generated = parseDate(state.data.generated_at);
  els.updated.textContent = `本地预览 · 生成于 ${formatDay(generated)} ${formatTime(generated)}`;
  renderSources();
  bindEvents();
  renderItems();
}

main().catch((error) => {
  els.items.innerHTML = `<div class="empty">读取数据失败：${error.message}</div>`;
});

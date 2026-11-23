"use strict";

const element = (id) => document.getElementById(id);
const form = element("query-form");
const input = element("item-input");
const body = element("result-body");
const count = element("result-count");
const exampleList = element("example-list");
const matches = element("search-matches");
const searchStatus = element("search-status");
const announcement = element("announcement");
const scenarioOptions = element("scenario-options");
const scenarioButtons = [...scenarioOptions.querySelectorAll("button[data-scenario]")];
const numericFormat = new Intl.NumberFormat("zh-TW");
const sourceLabels = {
  cooccurrence: "共同瀏覽",
  coadd: "共同加購",
  cobuy: "共同購買",
  popular: "熱門補位",
  popularity: "熱門補位",
};
const popularSources = new Set(["popular", "popularity"]);
let selectedScenario = "browse";
let activeRequest;
let lastQuery;
let searchTimer;
let searchRequest;

function make(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function showSnapshot(asOf) {
  const stamp = new Date(asOf);
  if (!asOf || Number.isNaN(stamp.valueOf())) return;
  const date = element("as-of");
  date.dateTime = asOf;
  date.textContent = stamp.toISOString().slice(0, 10) + " UTC";
  element("snapshot").hidden = false;
}

function setState(message, isError = false) {
  body.replaceChildren(make("p", isError ? "state error" : "state", message));
  count.hidden = true;
  announcement.textContent = message;
}

function updateExamples(itemId) {
  for (const button of exampleList.children) {
    button.setAttribute("aria-pressed", String(button.dataset.itemId === itemId));
  }
}

function selectScenario(scenario) {
  selectedScenario = scenario;
  for (const button of scenarioButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.scenario === scenario));
  }
  element("scenario-note").hidden = scenario === "browse";
}

function renderResults(data, scenario) {
  const rows = data.recommendations;
  const itemId = String(data.item_id);
  const label = scenarioButtons.find((button) => button.dataset.scenario === scenario).textContent;
  showSnapshot(data.as_of);
  updateExamples(itemId);
  element("results-caption").textContent = "商品 #" + itemId;
  if (!rows.length) {
    setState("這件商品目前沒有推薦結果，請改查其他商品。");
    return;
  }
  const table = make("table", "ranking");
  table.append(make("caption", "sr-only", "商品 #" + itemId + " · " + label));
  const headerRow = table.createTHead().insertRow();
  for (const name of ["排名", "商品編號", "推薦依據"]) {
    const heading = make("th", "", name);
    heading.scope = "col";
    headerRow.append(heading);
  }
  const tableBody = table.createTBody();
  const fallbackCount = rows.filter((row) => popularSources.has(row.source)).length;
  for (const item of rows) {
    const row = tableBody.insertRow();
    row.insertCell().append(make("span", "rank", String(item.rank).padStart(2, "0")));
    const itemButton = make("button", "item-link", String(item.item_id));
    itemButton.type = "button";
    itemButton.dataset.itemId = String(item.item_id);
    itemButton.setAttribute("aria-label", "查看商品 " + item.item_id + " 的推薦");
    row.insertCell().append(itemButton);
    const basis = row.insertCell();
    const cssClass = popularSources.has(item.source) ? "basis popularity" : "basis";
    basis.append(make("span", cssClass, sourceLabels[item.source] ?? "來源未提供"));
    if (item.source === "cooccurrence" && Number.isSafeInteger(item.co_sessions) && item.co_sessions > 0) {
      basis.append(make("span", "support", numericFormat.format(item.co_sessions) + " 次"));
    }
  }
  let note;
  if (scenario === "browse") {
    note = fallbackCount
      ? "共現商品不足時，依歷史熱門排行補足。"
      : "共同瀏覽次數是兩件商品同時出現在同一次瀏覽紀錄中的次數。";
  } else {
    const event = scenario === "cart" ? "加購" : "購買";
    if (fallbackCount === rows.length) {
      note = "這件商品的共同" + event + "榜為空，依訓練期熱門" + event + "排行補位。";
    } else if (fallbackCount) {
      note = "共同" + event + "保留原名次，其餘依訓練期熱門" + event + "排行補位。";
    } else {
      note = "共同" + event + "依支持訪客數排序。";
    }
  }
  body.replaceChildren(table, make("p", "table-note", note + "點選商品編號可繼續探索。"));
  count.textContent = rows.length + " 件商品";
  count.hidden = false;
  announcement.textContent = "商品 " + itemId + " 的「" + label + "」已載入 " + rows.length + " 件。";
}

function syncAddress(itemId, scenario) {
  const url = new URL(window.location.href);
  url.searchParams.set("item_id", itemId);
  if (scenario === "browse") url.searchParams.delete("scenario");
  else url.searchParams.set("scenario", scenario);
  window.history.replaceState(null, "", url);
}

function clearSearch() {
  clearTimeout(searchTimer);
  searchRequest?.abort();
  matches.replaceChildren();
  matches.hidden = true;
  searchStatus.textContent = "";
}

async function findItems(prefix, signal) {
  try {
    const params = new URLSearchParams({ prefix, scope: "product" });
    const response = await fetch("/api/catalog?" + params, { signal });
    if (!response.ok) throw new Error("catalog");
    const data = await response.json();
    if (signal.aborted) return;
    const items = data.items.slice(0, 8);
    for (const item of items) {
      const id = String(item.item_id);
      const button = make("button", "search-match", "#" + id);
      button.type = "button";
      button.dataset.itemId = id;
      button.setAttribute("aria-label", "查看符合編號的商品 " + id + " 的推薦");
      matches.append(button);
    }
    matches.hidden = items.length === 0;
    searchStatus.textContent = items.length
      ? "顯示 " + items.length + " 件符合的商品"
      : "找不到以 " + prefix + " 開頭的商品。";
  } catch {
    if (!signal.aborted) searchStatus.textContent = "暫時無法搜尋，可輸入完整編號查看推薦。";
  }
}

function scheduleSearch() {
  input.setCustomValidity("");
  clearSearch();
  const prefix = input.value.trim();
  if (!/^[0-9]{2,20}$/.test(prefix)) return;
  searchRequest = new AbortController();
  const { signal } = searchRequest;
  searchStatus.textContent = "正在搜尋商品…";
  searchTimer = setTimeout(() => findItems(prefix, signal), 180);
}

async function loadItem(rawId, preserveInput = false) {
  const itemId = String(rawId).trim();
  if (!/^[0-9]{1,20}$/.test(itemId)) {
    input.setCustomValidity("請輸入由數字組成的商品編號。");
    input.reportValidity();
    return;
  }
  clearSearch();
  input.setCustomValidity("");
  if (!preserveInput) input.value = itemId;
  lastQuery = itemId;
  const scenario = selectedScenario;
  syncAddress(itemId, scenario);
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  updateExamples(itemId);
  element("results-caption").textContent = "商品 #" + itemId;
  body.setAttribute("aria-busy", "true");
  setState("正在查詢商品 #" + itemId + " 的推薦…");
  try {
    const params = new URLSearchParams({ item_id: itemId, scenario });
    const response = await fetch("/api/recommendations?" + params, { signal: controller.signal });
    const data = await response.json();
    if (activeRequest !== controller) return;
    if (!response.ok) {
      setState(data.error ?? "推薦資料暫時無法載入，請稍後重新查詢。", true);
      return;
    }
    renderResults(data, scenario);
  } catch (error) {
    if (error.name !== "AbortError" && activeRequest === controller) {
      setState("無法讀取推薦資料，請確認服務已啟動後重試。", true);
    }
  } finally {
    if (activeRequest === controller) body.setAttribute("aria-busy", "false");
  }
}

function renderExamples(items) {
  for (const item of items.slice(0, 6)) {
    const id = String(item.item_id);
    const button = make("button", "example", "#" + id);
    button.type = "button";
    button.dataset.itemId = id;
    button.setAttribute("aria-label", "查詢範例商品 " + id);
    exampleList.append(button);
  }
  element("examples").hidden = exampleList.childElementCount === 0;
  updateExamples(lastQuery);
}

function onItemClick(event) {
  const button = event.target.closest("button[data-item-id]");
  if (button) loadItem(button.dataset.itemId);
}

async function initialize() {
  setState("正在載入商品資料…");
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("item_id");
  const mode = scenarioButtons.find((button) => button.dataset.scenario === params.get("scenario"));
  if (mode) selectScenario(mode.dataset.scenario);
  if (requested && /^[0-9]{1,20}$/.test(requested)) loadItem(requested);
  try {
    const response = await fetch("/api/catalog?scope=product");
    if (!response.ok) throw new Error("catalog");
    const catalog = await response.json();
    showSnapshot(catalog.as_of);
    renderExamples(catalog.items);
    if (!lastQuery && input.value.trim()) {
      body.setAttribute("aria-busy", "false");
      setState("選擇商品或輸入完整編號以查看推薦。");
    } else if (!lastQuery && catalog.items.length) {
      loadItem(catalog.items[0].item_id);
    } else if (!lastQuery) {
      body.setAttribute("aria-busy", "false");
      setState("目前沒有可供查詢的範例商品。");
    }
  } catch {
    const note = element("catalog-note");
    note.textContent = "範例商品暫時無法載入，仍可輸入已知商品編號。";
    note.hidden = false;
    if (!lastQuery) {
      body.setAttribute("aria-busy", "false");
      setState("請輸入商品編號以查詢推薦。");
    }
  }
}

input.addEventListener("input", scheduleSearch);
input.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" && matches.firstElementChild) {
    event.preventDefault();
    matches.firstElementChild.focus();
  }
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  loadItem(input.value);
});
scenarioOptions.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-scenario]");
  if (!button || button.dataset.scenario === selectedScenario) return;
  selectScenario(button.dataset.scenario);
  if (lastQuery) loadItem(lastQuery, true);
});
exampleList.addEventListener("click", onItemClick);
matches.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-item-id]");
  if (!button) return;
  input.focus();
  loadItem(button.dataset.itemId);
});
body.addEventListener("click", onItemClick);
initialize();

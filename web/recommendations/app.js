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
const numericFormat = new Intl.NumberFormat("zh-TW");
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

function renderResults(data) {
  const rows = data.recommendations;
  const itemId = String(data.item_id);
  showSnapshot(data.as_of);
  updateExamples(itemId);
  element("results-caption").textContent = "商品 #" + itemId;
  if (!rows.length) {
    setState("這件商品目前沒有推薦結果，請改查其他商品。");
    return;
  }
  const table = make("table", "ranking");
  table.append(make("caption", "sr-only", "商品 #" + itemId + " 的推薦結果"));
  const headerRow = table.createTHead().insertRow();
  for (const name of ["排名", "商品編號", "推薦依據"]) {
    const heading = make("th", "", name);
    heading.scope = "col";
    headerRow.append(heading);
  }
  const tableBody = table.createTBody();
  const hasFallback = rows.some((row) => row.source === "popularity");
  for (const item of rows) {
    const row = tableBody.insertRow();
    row.insertCell().append(make("span", "rank", String(item.rank).padStart(2, "0")));
    const itemButton = make("button", "item-link", String(item.item_id));
    itemButton.type = "button";
    itemButton.dataset.itemId = String(item.item_id);
    itemButton.setAttribute("aria-label", "查看商品 " + item.item_id + " 的推薦");
    row.insertCell().append(itemButton);
    const basis = row.insertCell();
    if (item.source === "cooccurrence") {
      basis.append(make("span", "basis", "共同瀏覽"));
      if (Number.isSafeInteger(item.co_sessions) && item.co_sessions > 0) {
        basis.append(make("span", "support", numericFormat.format(item.co_sessions) + " 次"));
      }
    } else if (item.source === "popularity") {
      basis.append(make("span", "basis popularity", "熱門補位"));
    } else {
      basis.textContent = "來源未提供";
    }
  }
  const note = hasFallback
    ? "共現商品不足時，依歷史熱門排行補足。點選商品編號可繼續探索。"
    : "共同瀏覽次數是兩件商品同時出現在同一次瀏覽紀錄中的次數。點選商品編號可繼續探索。";
  body.replaceChildren(table, make("p", "table-note", note));
  count.textContent = rows.length + " 件商品";
  count.hidden = false;
  announcement.textContent = "商品 " + itemId + " 的 " + rows.length + " 件推薦已載入。";
}

function syncAddress(itemId) {
  const url = new URL(window.location.href);
  url.searchParams.set("item_id", itemId);
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
    const params = new URLSearchParams({ prefix });
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

async function loadItem(rawId) {
  const itemId = String(rawId).trim();
  if (!/^[0-9]{1,20}$/.test(itemId)) {
    input.setCustomValidity("請輸入由數字組成的商品編號。");
    input.reportValidity();
    return;
  }
  clearSearch();
  input.setCustomValidity("");
  input.value = itemId;
  lastQuery = itemId;
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  updateExamples(itemId);
  element("results-caption").textContent = "商品 #" + itemId;
  body.setAttribute("aria-busy", "true");
  setState("正在查詢商品 #" + itemId + " 的推薦…");
  try {
    const params = new URLSearchParams({ item_id: itemId });
    const response = await fetch("/api/recommendations?" + params, { signal: controller.signal });
    if (activeRequest !== controller) return;
    if (!response.ok) {
      const error = response.status === 404 || response.status === 400 || response.status === 422
        ? "找不到這個歷史商品編號，請檢查後重試，或選一件範例商品。"
        : "推薦資料暫時無法載入，請稍後重新查詢。";
      setState(error, true);
      return;
    }
    const data = await response.json();
    if (activeRequest !== controller) return;
    renderResults(data);
    syncAddress(String(data.item_id));
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
  const requested = new URLSearchParams(window.location.search).get("item_id");
  if (requested && /^[0-9]{1,20}$/.test(requested)) loadItem(requested);
  try {
    const response = await fetch("/api/catalog");
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
exampleList.addEventListener("click", onItemClick);
matches.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-item-id]");
  if (!button) return;
  input.focus();
  loadItem(button.dataset.itemId);
});
body.addEventListener("click", onItemClick);
initialize();

"use strict";

const element = (id) => document.getElementById(id);
const modeInfo = {
  browse: {
    title: "其他人也看了", shared: "共同瀏覽", popular: "熱門瀏覽榜",
    method: "兩件商品在越多次造訪中一起被瀏覽，這組配對的排名就越前面。",
  },
  cart: {
    title: "其他人也加入購物車", shared: "共同加購", popular: "熱門加購榜",
    method: "至少兩位訪客曾在各自的一次造訪中將這兩件商品加入購物車，才會列入共同加購榜。",
  },
  purchase: {
    title: "其他人也買了", shared: "共同購買", popular: "熱門購買榜",
    method: "至少兩位訪客曾在各自的一筆交易中買下這兩件商品，才會列入共同購買榜。",
  },
};
const sourceLabels = {
  cooccurrence: "共同瀏覽",
  coadd: "共同加購",
  cobuy: "共同購買",
  popular: "熱門補位",
};
const caseButtons = [...element("case-buttons").querySelectorAll("button")];
const modeButtons = [...element("mode-buttons").querySelectorAll("button")];
const params = new URLSearchParams(window.location.search);
const isProduct = params.has("item");
const from = params.get("from");
let selectedMode = [params.get("mode"), from, "browse"].find((mode) => Object.hasOwn(modeInfo, mode));
const originMode = Object.hasOwn(modeInfo, from) ? from : selectedMode;
let selectedKey = isProduct ? params.get("item") :
  caseButtons.find((button) => button.dataset.case === params.get("case"))?.dataset.case ?? "paired";
let entries;

if (isProduct) {
  element("demo").classList.add("product-detail");
  element("case-picker").hidden = true;
  element("examples-link").removeAttribute("aria-current");
  element("intro-label").hidden = true;
  element("title").textContent = "熱門商品推薦";
  element("intro-copy").textContent = "切換瀏覽、加購與購買，查看這件商品的相關推薦。";
  element("selected-product").hidden = true;
  element("back-to-ranking").href = "../?ranking=" + originMode;
  element("back-to-ranking").textContent = "回" + modeInfo[originMode].popular;
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

function render() {
  const mode = modeInfo[selectedMode];
  const { item, rankings } = entries[selectedKey];
  const rows = rankings[selectedMode];
  const fallbackCount = rows.filter(([, source]) => source === "popular").length;
  const product = "商品 " + item;

  for (const button of caseButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.case === selectedKey));
  }
  for (const button of modeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === selectedMode));
  }
  element("selected-product").textContent = product;
  if (isProduct) {
    element("title").textContent = product + " 的相關推薦";
    document.title = product + " 的相關推薦｜Retailrocket";
    element("method-copy").textContent = mode.method;
    element("product-method").hidden = false;
  }
  element("ranking-title").textContent = mode.title;
  element("ranking-caption").textContent = product + "的" + mode.title + "前十名";
  element("shared-count").textContent = mode.shared + " " + (rows.length - fallbackCount) + " 席";
  element("popular-count").textContent = "熱門補位 " + fallbackCount + " 席";

  const mix = document.createDocumentFragment();
  const body = document.createDocumentFragment();
  rows.forEach(([alias, source], index) => {
    const cssClass = source === "popular" ? "popular" : "shared";
    mix.append(make("span", cssClass, ""));
    const row = document.createElement("tr");
    row.insertCell().append(make("span", "rank-number", String(index + 1).padStart(2, "0")));
    row.insertCell().append(make("span", "rank-item", "商品 " + alias));
    row.insertCell().append(make("span", "source " + cssClass, sourceLabels[source]));
    body.append(row);
  });
  element("mix-track").replaceChildren(mix);
  element("ranking-rows").replaceChildren(body);

  let note = "前十名都有" + mode.shared + "支持。";
  if (fallbackCount === rows.length) {
    note = "這件商品的" + mode.shared + "榜為空，十席都依該情境的熱門榜補位。";
  } else if (fallbackCount > 0) {
    note = "先保留" + mode.shared + "的名次，再從該情境的熱門榜補滿十席。";
  }
  element("ranking-note").textContent = note;
  element("announcement").textContent = product + "的" + mode.title + "已顯示，" + note;
}

function syncAddress() {
  const url = new URL(window.location.href);
  if (isProduct) {
    url.searchParams.set("from", originMode);
  } else {
    url.searchParams.set("case", selectedKey);
  }
  url.searchParams.set("mode", selectedMode);
  window.history.replaceState(null, "", url);
}

for (const button of caseButtons) {
  button.addEventListener("click", () => {
    selectedKey = button.dataset.case;
    render();
    syncAddress();
  });
}
for (const button of modeButtons) {
  button.addEventListener("click", () => {
    selectedMode = button.dataset.mode;
    render();
    syncAddress();
  });
}

async function load() {
  try {
    const filename = isProduct ? "popular-products.json" : "cases.json";
    const response = await fetch("../recommendation-demo/" + filename);
    if (!response.ok) throw new Error("Could not load rankings");
    entries = await response.json();
    if (!Object.hasOwn(entries, selectedKey)) {
      element("message").textContent = "找不到這件商品的公開推薦。請回到熱門榜選擇商品。";
      element("results").querySelector(".results-header").hidden = true;
      return;
    }
    render();
    element("ranking-content").hidden = false;
    element("message").hidden = true;
    for (const button of [...caseButtons, ...modeButtons]) button.disabled = false;
  } catch {
    element("message").textContent = "暫時無法載入展示榜單。請重新整理，或點開八月成效對照圖。";
  } finally {
    element("results").setAttribute("aria-busy", "false");
  }
}

load();

"use strict";

const element = (id) => document.getElementById(id);
const modes = {
  browse: {
    heading: "熱門瀏覽前十名",
    unit: "瀏覽次數",
    method: "把重複的瀏覽紀錄去除後，依每件商品的瀏覽次數由多到少排列。",
  },
  cart: {
    heading: "熱門加購前十名",
    unit: "加購次數",
    method: "把重複的加購紀錄去除後，依每件商品被加入購物車的次數由多到少排列。",
  },
  purchase: {
    heading: "熱門購買前十名",
    unit: "含該商品的交易數",
    method: "依包含該商品的交易筆數由多到少排列。同一位訪客在同筆交易買了多件相同商品，只計一次。",
  },
};
const buttons = [...document.querySelectorAll("[data-popular-mode]")];
const numberFormat = new Intl.NumberFormat("zh-TW");
let rankings;

function showRanking(mode) {
  const { heading, unit, method } = modes[mode];
  const body = document.createDocumentFragment();
  rankings[mode].forEach(({ item, count }, index) => {
    const row = document.createElement("tr");
    const rank = row.insertCell();
    rank.className = "rank-number";
    rank.textContent = String(index + 1).padStart(2, "0");
    const product = row.insertCell();
    product.className = "rank-item";
    const link = document.createElement("a");
    link.className = "product-link";
    link.href = "./products/?" + new URLSearchParams({ item, mode, from: mode });
    link.textContent = "商品 " + item;
    link.setAttribute("aria-label", "查看商品 " + item + " 的推薦");
    product.append(link);
    const value = row.insertCell();
    value.className = "popular-count-value";
    value.textContent = numberFormat.format(count);
    body.append(row);
  });
  element("popular-rows").replaceChildren(body);
  element("popular-heading").textContent = heading;
  element("popular-unit").textContent = unit;
  element("popular-method").textContent = method;
  element("popular-case-link").href = "./products/?case=popular&mode=" + mode;
  element("popular-announcement").textContent = "已顯示" + heading + "，依" + unit + "排序。";
  for (const button of buttons) {
    button.setAttribute("aria-pressed", String(button.dataset.popularMode === mode));
  }
}

for (const button of buttons) {
  button.addEventListener("click", () => {
    const mode = button.dataset.popularMode;
    showRanking(mode);
    const url = new URL(location.href);
    url.searchParams.set("ranking", mode);
    history.replaceState(null, "", url);
  });
}

async function load() {
  try {
    const response = await fetch("./recommendation-demo/popularity.json");
    if (!response.ok) throw new Error("Could not load popular products");
    const data = await response.json();
    rankings = data.rankings;
    const { start, end_exclusive } = data.training_window_utc;
    const lastDay = new Date(Date.parse(end_exclusive) - 1).toISOString().slice(0, 10);
    element("popular-dates").textContent = start.slice(0, 10) + " 至 " + lastDay;
    const requested = new URLSearchParams(location.search).get("ranking");
    showRanking(buttons.some((button) => button.dataset.popularMode === requested) ? requested : "browse");
    element("popular-table").hidden = false;
    element("popular-message").hidden = true;
    for (const button of buttons) button.disabled = false;
  } catch {
    element("popular-message").textContent = "暫時無法載入熱門榜單，請重新整理頁面再試一次。";
  } finally {
    element("popular-results").setAttribute("aria-busy", "false");
  }
}

load();

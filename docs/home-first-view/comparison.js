"use strict";

const element = (id) => document.getElementById(id);
const format = new Intl.NumberFormat("zh-TW");
const filter = element("only-changes");
const rows = element("ranking-rows");

function appendProduct(row, entry, arm) {
  const cell = row.insertCell();
  const item = document.createElement("a");
  item.className = "item product-link";
  item.id = arm + "-" + entry.item;
  item.href = "../products/?" + new URLSearchParams({
    item: entry.item, mode: "browse", from: "home-first-view", arm,
  });
  item.textContent = "商品 " + entry.item;
  const detail = document.createElement("span");
  detail.className = "detail";
  if (entry.other_rank === null) {
    const candidate = arm === "candidate";
    cell.className = candidate ? "gain" : "loss";
    detail.textContent = (candidate ? "新增 " : "失去 ") + format.format(entry.exclusive_hits) + " 人";
  } else {
    detail.textContent = entry.other_rank === entry.rank ? "兩榜同名次" :
      (arm === "candidate" ? "原榜" : "首看榜") + "第 " + entry.other_rank + " 名";
  }
  cell.append(item, detail);
}

function display(data) {
  const fragment = document.createDocumentFragment();
  data.baseline.forEach((base, i) => {
    const candidate = data.candidate[i];
    const row = document.createElement("tr");
    row.dataset.changed = String(base.exclusive_hits > 0 || candidate.exclusive_hits > 0);
    const rank = document.createElement("th");
    rank.scope = "row";
    rank.className = "rank-number";
    rank.textContent = String(base.rank).padStart(2, "0");
    row.append(rank);
    appendProduct(row, base, "baseline");
    appendProduct(row, candidate, "candidate");
    fragment.append(row);
  });
  rows.replaceChildren(fragment);
  element("net").textContent = (data.net_hits > 0 ? "+" : "") + format.format(data.net_hits);
  element("gained").textContent = format.format(data.gained) + " 人";
  element("lost").textContent = format.format(data.lost) + " 人";
  element("sample").textContent = format.format(data.scored_visitors) + " 位新訪客，各以首次瀏覽計一次。";
  element("baseline-hits").textContent = "命中 " + format.format(data.baseline_hits) + " 人";
  element("candidate-hits").textContent = "命中 " + format.format(data.candidate_hits) + " 人";
  element("impact-values").hidden = false;
  element("ranking-content").hidden = false;
  element("message").hidden = true;
  filter.disabled = false;
  restoreView();
}

function setChanges(url) {
  if (filter.checked) url.searchParams.set("changes", "1");
  else url.searchParams.delete("changes");
}

function applyFilter() {
  let visible = 0;
  for (const row of rows.rows) {
    row.hidden = filter.checked && row.dataset.changed === "false";
    if (!row.hidden) visible++;
  }
  for (const link of rows.querySelectorAll("a")) {
    const url = new URL(link.href);
    setChanges(url);
    link.href = url.href;
  }
  element("announcement").textContent = filter.checked
    ? "目前顯示 " + visible + " 個有增減的名次。"
    : "已顯示兩榜完整前十名。";
}

function restoreView() {
  filter.checked = new URLSearchParams(location.search).get("changes") === "1";
  applyFilter();
  const origin = element(location.hash.slice(1));
  if (origin?.matches("a.product-link") && rows.contains(origin) && !origin.closest("tr").hidden) {
    origin.focus({ preventScroll: true });
    origin.scrollIntoView({ block: "nearest" });
  }
}

filter.addEventListener("change", () => {
  const url = new URL(location.href);
  setChanges(url);
  if (rows.contains(element(url.hash.slice(1)))) url.hash = "";
  history.replaceState(history.state, "", url);
  applyFilter();
});

rows.addEventListener("click", (event) => {
  const link = event.target.closest("a");
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
  // Browser Back should restore the same column even when a product is in both lists.
  const url = new URL(location.href);
  url.hash = link.id;
  history.replaceState(history.state, "", url);
});

window.addEventListener("pageshow", (event) => {
  if (event.persisted && !filter.disabled) restoreView();
});

async function load() {
  try {
    const response = await fetch("../recommendation-demo/home-first-view.json");
    if (!response.ok) throw new Error("Could not load the rankings");
    display(await response.json());
  } catch {
    element("message").textContent = "無法載入兩張榜單，請重新整理，或查看八月成效對照圖。";
  } finally {
    element("rankings").setAttribute("aria-busy", "false");
  }
}

load();

"use strict";

const element = (id) => document.getElementById(id);
const format = new Intl.NumberFormat("zh-TW");
const filter = element("only-changes");

function appendProduct(row, entry, arm) {
  const cell = row.insertCell();
  const item = document.createElement("span");
  item.className = "item";
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
  element("ranking-rows").replaceChildren(fragment);
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
  applyFilter();
}

function applyFilter() {
  let visible = 0;
  for (const row of element("ranking-rows").rows) {
    row.hidden = filter.checked && row.dataset.changed === "false";
    if (!row.hidden) visible++;
  }
  element("announcement").textContent = filter.checked
    ? "目前顯示 " + visible + " 個有增減的名次。"
    : "已顯示兩榜完整前十名。";
}

filter.addEventListener("change", applyFilter);

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

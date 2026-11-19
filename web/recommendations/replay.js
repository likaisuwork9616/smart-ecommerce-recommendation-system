"use strict";

const byId = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("zh-TW");
const percent = new Intl.NumberFormat("zh-TW", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const comparisons = {
  baseline: {
    prefix: "",
    labels: { c1_only: "僅共現模型命中", p0_only: "僅熱門榜命中", neither: "兩者皆未命中", both: "兩者皆命中" },
    netLabel: "共現模型比熱門榜淨",
    unavailable: "目前沒有可回放的歷史案例。",
  },
  recency: {
    prefix: "recency_",
    labels: { gained: "新增命中", lost: "擠掉原有命中" },
    netLabel: "留一席比原共現榜淨",
    unavailable: "目前無法載入最近商品的回放案例。請確認本機回放資料齊全後重新啟動服務。",
  },
  k1: {
    prefix: "k1_vs_c1_",
    labels: { k1_only: "只有 K1 命中", c1_only: "只有 C1 命中" },
    netLabel: "K1 比 C1 淨",
    unavailable: "目前無法載入 K1 回放案例。請確認本機有已驗收的八月 K1 開發查詢與報告，再重新啟動服務。",
  },
};
const requestedCase = new URLSearchParams(window.location.search).get("case");
const mode = Object.keys(comparisons).find((key) => {
  const { prefix, labels } = comparisons[key];
  return requestedCase?.startsWith(prefix) && Object.hasOwn(labels, requestedCase.slice(prefix.length));
}) || "baseline";
const comparison = comparisons[mode];

function itemIds(ids) {
  return ids.map((id) => {
    const item = document.createElement("span");
    item.textContent = "#" + id;
    return item;
  });
}

function setOutcome(element, arm) {
  const ranks = arm.hit_ranks;
  element.textContent = ranks.length ? "第 " + ranks.join("、") + " 名命中" : "前十名未命中";
  element.classList.toggle("has-hit", ranks.length > 0);
}

function badge(cell, label, className) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = label;
  cell.append(span);
}

function addPrediction(row, arm, index) {
  const cell = row.insertCell();
  badge(cell, "#" + arm.items[index], "replay-id");
  if (arm.hit_ranks.includes(index + 1)) {
    cell.classList.add("is-hit");
    badge(cell, "命中", "rank-label hit-label");
  }
  if (index >= arm.items.length - (arm.zero_fill_slots ?? 0)) {
    badge(cell, "熱門補位", "rank-label");
  }
}

function renderRanking(entry) {
  const left = mode === "k1" ? entry.k1 : entry.p0;
  byId("target-items").replaceChildren(...itemIds(entry.targets));
  setOutcome(byId("left-outcome"), left);
  setOutcome(byId("c1-outcome"), entry.c1);
  const tbody = byId("ranked-items");
  tbody.replaceChildren();
  for (let index = 0; index < left.items.length; index++) {
    const row = tbody.insertRow();
    const rank = document.createElement("th");
    rank.scope = "row";
    rank.textContent = String(index + 1).padStart(2, "0");
    row.append(rank);
    addPrediction(row, left, index);
    addPrediction(row, entry.c1, index);
  }
}

function setTime(element, timestamp) {
  element.dateTime = timestamp;
  element.textContent = timestamp.replace("T", " ").replace("Z", " UTC");
}

function renderCase(entry) {
  setTime(byId("query-time"), entry.query_time);
  byId("history-context").hidden = !entry.history.length;
  byId("history-items").replaceChildren(...itemIds(entry.history));
  if (mode === "recency") {
    setTime(byId("recent-time"), entry.recent_time);
    byId("original-tenth").textContent = "#" + entry.c1.items[9];
    byId("revised-tenth").textContent = "#" + entry.recency.items[9];
    setOutcome(byId("original-result"), entry.c1);
    setOutcome(byId("revised-result"), entry.recency);
    byId("slot-targets").replaceChildren(...itemIds(entry.targets));
  } else {
    renderRanking(entry);
  }
  byId("announcement").textContent = comparison.labels[entry.id] + "，排名與實際瀏覽已更新。";
}

function showCases(data) {
  const group = mode === "baseline" ? data : data[mode];
  if (!group || !group.cases.length) {
    byId("load-message").textContent = comparison.unavailable;
    byId("retry").hidden = false;
    return;
  }
  const entries = group.cases;
  const total = group.total_queries;
  const hasCounts = Number.isSafeInteger(total) && total > 0
    && Number.isSafeInteger(group.net_additional_hits) && entries.every((entry) => Number.isSafeInteger(entry.count));
  byId("validation-period").textContent = hasCounts
    ? "2015 年 8 月開發驗證共 " + number.format(total) + " 次查詢。選一種結果，可回放該類的第一筆紀錄。"
    : "選一種結果可回放該類的第一筆紀錄。重新啟動本機服務後可查看全體次數與占比。";
  const selected = entries.find((entry) => comparison.prefix + entry.id === requestedCase) || entries[0];
  const choices = byId("case-options");
  byId("slot-comparison").hidden = mode !== "recency";
  byId("baseline-comparison").hidden = mode === "recency";
  byId("recent-context").hidden = mode !== "recency";
  choices.classList.toggle("two-options", mode !== "baseline");
  if (mode === "recency") {
    byId("case-legend").textContent = "選擇命中變化";
    byId("report-link").href = "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/598900c/docs/PROJECT_PROGRESS.md#recency-slot-validation";
  } else if (mode === "k1") {
    byId("left-model").textContent = "近鄰模型 K1";
    byId("right-model").textContent = "共現模型 C1";
    byId("report-link").href = "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/0d53e4f/docs/STAGE12_K1_AUGUST_READBACK_20261119.md";
  }
  choices.replaceChildren();
  for (const entry of entries) {
    const caseId = comparison.prefix + entry.id;
    const label = document.createElement("label");
    label.className = "case-option";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "replay-case";
    radio.value = caseId;
    radio.checked = entry.id === selected.id;
    radio.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("case", caseId);
      window.history.replaceState(null, "", url);
      renderCase(entry);
    });
    const card = document.createElement("span");
    card.className = "case-card";
    const title = document.createElement("span");
    title.className = "case-title";
    title.id = "case-title-" + caseId;
    title.textContent = comparison.labels[entry.id];
    radio.setAttribute("aria-labelledby", title.id);
    card.append(title);
    if (hasCounts) {
      const stats = document.createElement("span");
      stats.className = "case-stats";
      stats.id = "case-stats-" + caseId;
      badge(stats, percent.format(entry.count / total), "case-percent");
      badge(stats, number.format(entry.count) + " 次", "case-count");
      radio.setAttribute("aria-describedby", stats.id);
      card.append(stats);
    }
    label.append(radio, card);
    choices.append(label);
  }
  if (hasCounts) {
    const summary = byId("case-summary");
    if (mode === "recency") {
      summary.textContent = "前九名沿用原共現榜，最近看過且可推薦的商品若未上榜，就換入第十名。";
    } else if (mode === "k1") {
      summary.textContent = "K1 找出看過相似商品的歷史瀏覽紀錄，依相似程度替商品投票。C1 依商品的共同瀏覽紀錄推薦。";
    } else {
      const counts = new Map(entries.map((entry) => [entry.id, entry.count]));
      const both = counts.get("both") || 0;
      const popular = (counts.get("p0_only") || 0) + both;
      const cooccurrence = (counts.get("c1_only") || 0) + both;
      summary.textContent = "前十名命中率為熱門榜 " + percent.format(popular / total)
        + "、共現模型 " + percent.format(cooccurrence / total) + "。";
    }
    const net = group.net_additional_hits;
    const difference = document.createElement("strong");
    difference.textContent = net === 0 ? "兩種方法的總命中次數相同。"
      : comparison.netLabel + (net > 0 ? "多" : "少") + "命中 " + number.format(Math.abs(net)) + " 次。";
    summary.append(difference);
    summary.hidden = false;
  }
  renderCase(selected);
  byId("load-state").hidden = true;
  byId("replay").hidden = false;
}

async function loadReplay() {
  byId("retry").hidden = true;
  byId("load-message").textContent = "正在讀取已驗證的歷史瀏覽紀錄…";
  try {
    const response = await fetch("/api/replay");
    if (response.status === 503) {
      byId("load-message").textContent = "本機缺少可核對的 Stage 10 回放資料。請還原保存包並重新啟動服務。";
      byId("retry").hidden = false;
      return;
    }
    if (!response.ok) throw new Error("replay unavailable");
    const data = await response.json();
    showCases(data);
  } catch {
    byId("load-message").textContent = "無法載入回放。請確認本機服務與 Stage 10 驗證紀錄可用後重試。";
    byId("retry").hidden = false;
  }
}

byId(mode + "-link").setAttribute("aria-current", "page");
byId("retry").addEventListener("click", loadReplay);
loadReplay();

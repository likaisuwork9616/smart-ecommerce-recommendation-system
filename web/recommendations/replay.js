"use strict";

const byId = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("zh-TW");
const percent = new Intl.NumberFormat("zh-TW", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const caseLabels = {
  c1_only: "僅共現模型命中",
  p0_only: "僅熱門榜命中",
  neither: "兩者皆未命中",
  both: "兩者皆命中",
};

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

function addPrediction(row, arm, index, isFallback) {
  const cell = row.insertCell();
  badge(cell, "#" + arm.items[index], "replay-id");
  if (arm.hit_ranks.includes(index + 1)) {
    cell.classList.add("is-hit");
    badge(cell, "命中", "rank-label hit-label");
  }
  if (isFallback) badge(cell, "熱門補位", "rank-label");
}

function renderCase(entry) {
  const time = byId("query-time");
  time.dateTime = entry.query_time;
  time.textContent = entry.query_time.replace("T", " ").replace("Z", " UTC");
  byId("history-context").hidden = !entry.history.length;
  byId("history-items").replaceChildren(...itemIds(entry.history));
  byId("target-items").replaceChildren(...itemIds(entry.targets));

  setOutcome(byId("p0-outcome"), entry.p0);
  setOutcome(byId("c1-outcome"), entry.c1);
  const tbody = byId("ranked-items");
  tbody.replaceChildren();
  const positiveSlots = entry.c1.items.length - entry.c1.zero_fill_slots;
  for (let index = 0; index < entry.p0.items.length; index++) {
    const row = tbody.insertRow();
    const rank = document.createElement("th");
    rank.scope = "row";
    rank.textContent = String(index + 1).padStart(2, "0");
    row.append(rank);
    addPrediction(row, entry.p0, index, false);
    addPrediction(row, entry.c1, index, index >= positiveSlots);
  }
  byId("announcement").textContent = caseLabels[entry.id] + "，排名與實際瀏覽已更新。";
}

function showCases(data) {
  const entries = data.cases;
  const total = data.total_queries;
  const hasCounts = Number.isSafeInteger(total) && total > 0
    && Number.isSafeInteger(data.net_additional_hits) && entries.every((entry) => Number.isSafeInteger(entry.count));
  byId("validation-period").textContent = hasCounts
    ? "2015 年 8 月開發驗證共 " + number.format(total) + " 次查詢。選一種結果，可回放該類的第一筆紀錄。"
    : "選一種結果可回放該類的第一筆紀錄。重新啟動本機服務後可查看全體次數與占比。";
  const params = new URLSearchParams(window.location.search);
  const selected = entries.find((entry) => entry.id === params.get("case")) || entries[0];
  const choices = byId("case-options");
  choices.replaceChildren();
  for (const entry of entries) {
    const label = document.createElement("label");
    label.className = "case-option";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "replay-case";
    radio.value = entry.id;
    radio.checked = entry.id === selected.id;
    radio.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("case", entry.id);
      window.history.replaceState(null, "", url);
      renderCase(entry);
    });
    const card = document.createElement("span");
    card.className = "case-card";
    const title = document.createElement("span");
    title.className = "case-title";
    title.id = "case-title-" + entry.id;
    title.textContent = caseLabels[entry.id];
    radio.setAttribute("aria-labelledby", title.id);
    card.append(title);
    if (hasCounts) {
      const stats = document.createElement("span");
      stats.className = "case-stats";
      stats.id = "case-stats-" + entry.id;
      badge(stats, percent.format(entry.count / total), "case-percent");
      badge(stats, number.format(entry.count) + " 次", "case-count");
      radio.setAttribute("aria-describedby", stats.id);
      card.append(stats);
    }
    label.append(radio, card);
    choices.append(label);
  }
  if (hasCounts) {
    const counts = new Map(entries.map((entry) => [entry.id, entry.count]));
    const both = counts.get("both") || 0;
    const popular = (counts.get("p0_only") || 0) + both;
    const cooccurrence = (counts.get("c1_only") || 0) + both;
    const net = data.net_additional_hits;
    const summary = byId("case-summary");
    summary.textContent = "前十名命中率為熱門榜 " + percent.format(popular / total)
      + "、共現模型 " + percent.format(cooccurrence / total) + "。";
    const difference = document.createElement("strong");
    difference.textContent = net === 0 ? "兩種方法的總命中次數相同。"
      : "共現模型比熱門榜淨" + (net > 0 ? "多" : "少") + "命中 " + number.format(Math.abs(net)) + " 次。";
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
    if (!data.cases.length) {
      byId("load-message").textContent = "目前沒有可回放的歷史案例。";
      return;
    }
    showCases(data);
  } catch {
    byId("load-message").textContent = "無法載入回放。請確認本機服務與 Stage 10 驗證紀錄可用後重試。";
    byId("retry").hidden = false;
  }
}

byId("retry").addEventListener("click", loadReplay);
loadReplay();

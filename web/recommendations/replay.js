"use strict";

const byId = (id) => document.getElementById(id);
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

function showCases(entries) {
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
    const caption = document.createElement("span");
    caption.textContent = caseLabels[entry.id];
    label.append(radio, caption);
    choices.append(label);
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
    showCases(data.cases);
  } catch {
    byId("load-message").textContent = "無法載入回放。請確認本機服務與 Stage 10 驗證紀錄可用後重試。";
    byId("retry").hidden = false;
  }
}

byId("retry").addEventListener("click", loadReplay);
loadReplay();

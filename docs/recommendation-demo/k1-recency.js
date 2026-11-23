"use strict";

const element = (id) => document.getElementById(id);
const product = (alias) => `商品 ${alias}`;
const caseButtons = [...element("case-buttons").querySelectorAll("button")];

function outcome(items, next) {
  const rank = items.indexOf(next) + 1;
  return rank ? `第 ${rank} 名命中` : "前十名未命中";
}

function addProduct(row, alias, actual) {
  const cell = row.insertCell();
  const item = document.createElement("span");
  item.className = "rank-item";
  item.textContent = product(alias);
  cell.append(item);
  if (alias === actual) {
    cell.className = "recency-hit";
    const badge = document.createElement("span");
    badge.className = "hit-badge";
    badge.textContent = "命中";
    cell.append(badge);
  }
}

function render(button, { before, after, next }) {
  for (const choice of caseButtons) {
    choice.setAttribute("aria-pressed", String(choice === button));
  }
  const title = button.querySelector("strong").textContent;
  const beforeOutcome = outcome(before, next);
  const afterOutcome = outcome(after, next);
  element("case-label").textContent = title;
  element("original-tenth").textContent = product(before[9]);
  element("replacement").textContent = product(after[9]);
  element("actual-next").textContent = product(next);
  element("before-outcome").textContent = beforeOutcome;
  element("after-outcome").textContent = afterOutcome;

  const rows = document.createDocumentFragment();
  before.forEach((alias, index) => {
    const row = document.createElement("tr");
    if (index === 9) row.className = "recency-swap";
    const rank = row.insertCell();
    rank.className = "rank-number";
    rank.textContent = String(index + 1).padStart(2, "0");
    addProduct(row, alias, next);
    addProduct(row, after[index], next);
    rows.append(row);
  });
  element("ranking-rows").replaceChildren(rows);
  element("announcement").textContent = `${title}。實際下一件是${product(next)}。原 K1 ${beforeOutcome}，留一席後${afterOutcome}。`;
}

async function load() {
  try {
    const response = await fetch("../recommendation-demo/k1-recency-cases.json");
    if (!response.ok) throw new Error("Could not load K1 replay");
    const cases = await response.json();
    const url = new URL(window.location.href);
    const selected = caseButtons.find((button) => button.dataset.case === url.searchParams.get("case")) ?? caseButtons[0];
    render(selected, cases[selected.dataset.case]);

    for (const button of caseButtons) {
      const caseId = button.dataset.case;
      button.querySelector("[data-count]").textContent = `八月共 ${cases[caseId].count.toLocaleString("zh-TW")} 筆`;
      button.addEventListener("click", () => {
        render(button, cases[caseId]);
        url.searchParams.set("case", caseId);
        window.history.replaceState(null, "", url);
      });
      button.disabled = false;
    }
    element("ranking-content").hidden = false;
    element("message").hidden = true;
  } catch {
    element("message").textContent = "暫時無法載入回放。請重新整理，或查看八月結果與案例圖。";
  } finally {
    element("results").setAttribute("aria-busy", "false");
  }
}

load();

"use strict";

const element = (id) => document.getElementById(id);
const product = (alias) => `商品 ${alias}`;
const choices = [...element("case-buttons").querySelectorAll("button[data-case]")];

function outcome(ranking, actual) {
  const firstRank = ranking.findIndex((alias) => actual.includes(alias)) + 1;
  return firstRank ? `第 ${firstRank} 名命中` : "前十名未命中";
}

function productCell(row, alias, { actual, previous }) {
  const cell = row.insertCell();
  const label = document.createElement("span");
  label.className = "rank-item";
  label.textContent = product(alias);
  cell.append(label);
  if (actual.includes(alias)) {
    cell.className = "recency-hit";
    const badge = document.createElement("span");
    badge.className = "hit-badge";
    badge.textContent = "命中";
    cell.append(badge);
  }
  if (alias === previous) {
    const note = document.createElement("small");
    note.className = "previous-item";
    note.textContent = "上次看過";
    cell.append(note);
  }
}

function render(button, example) {
  const { previous, actual, baseline, candidate } = example;
  const title = button.querySelector("strong").textContent;
  const actualProducts = actual.map(product).join("、");
  const baselineOutcome = outcome(baseline, actual);
  const candidateOutcome = outcome(candidate, actual);
  element("case-label").textContent = title;
  element("previous").textContent = product(previous);
  element("actual").textContent = actualProducts;
  element("baseline-outcome").textContent = baselineOutcome;
  element("candidate-outcome").textContent = candidateOutcome;

  const rows = document.createDocumentFragment();
  baseline.forEach((alias, index) => {
    const row = document.createElement("tr");
    const rank = document.createElement("th");
    rank.scope = "row";
    rank.className = "rank-number";
    rank.textContent = String(index + 1).padStart(2, "0");
    row.append(rank);
    productCell(row, alias, example);
    productCell(row, candidate[index], example);
    rows.append(row);
  });
  element("ranking-rows").replaceChildren(rows);
  for (const choice of choices) choice.setAttribute("aria-pressed", String(choice === button));
  element("announcement").textContent = `${title}。上次看的是${product(previous)}，回訪第一眼看的是${actualProducts}。純熱門留席榜${baselineOutcome}，共同瀏覽留席榜${candidateOutcome}。`;
}

async function load() {
  try {
    const response = await fetch("../recommendation-demo/returning-home-cases.json");
    if (!response.ok) throw new Error("Could not load returning visitor cases");
    const cases = await response.json();
    const url = new URL(window.location.href);
    const selected = choices.find((button) => button.dataset.case === url.searchParams.get("case")) ?? choices[0];
    render(selected, cases[selected.dataset.case]);
    for (const button of choices) {
      const caseId = button.dataset.case;
      button.querySelector("[data-count]").textContent = `八月共 ${cases[caseId].count.toLocaleString("zh-TW")} 人`;
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
    element("message").textContent = "暫時無法載入回放。請重新整理，或查看七、八月成效對照圖。";
  } finally {
    element("rankings").setAttribute("aria-busy", "false");
  }
}

load();

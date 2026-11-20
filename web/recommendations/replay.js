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
    arms: ["p0", "c1"],
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
    arms: ["k1", "c1"],
    labels: { k1_only: "只有 K1 命中", c1_only: "只有 C1 命中" },
    netLabel: "K1 比 C1 淨",
    unavailable: "目前無法載入 K1 回放案例。請確認本機有已驗收的八月 K1 開發查詢與報告，再重新啟動服務。",
  },
  cart: {
    prefix: "cart_",
    arms: ["coadd", "popular"],
    titlePrefix: "共同加購榜",
    labels: { hit: "命中", miss: "未命中" },
    unavailable: "目前無法載入八月加購案例。請確認本機有已核對的加購回放檔，再重新啟動服務。",
  },
  cart_fill: {
    prefix: "cart_fill_",
    arms: ["coadd", "popular_fill"],
    labels: { empty: "空榜補位命中", short: "短榜補位命中" },
    unavailable: "目前無法載入熱門補位案例。請建立本機補位回放檔，再重新啟動服務。",
  },
  purchase_fill: {
    prefix: "purchase_fill_",
    arms: ["cobuy", "popular", "popular_fill"],
    labels: { short_gain: "短榜補位新增命中", popular_later: "原熱門榜命中後移" },
    unavailable: "目前無法載入購買補位案例。請建立本機購買回放檔，再重新啟動服務。",
  },
};
const requestedCase = new URLSearchParams(window.location.search).get("case");
const mode = Object.keys(comparisons).find((key) => {
  const { prefix, labels } = comparisons[key];
  return requestedCase?.startsWith(prefix) && Object.hasOwn(labels, requestedCase.slice(prefix.length));
}) || "baseline";
const comparison = comparisons[mode];
const cartMode = mode === "cart" || mode === "cart_fill";
const purchaseMode = mode === "purchase_fill";
const transactionMode = cartMode || purchaseMode;
const sourceLabels = { coadd: "共同加購", cobuy: "共同購買", popular: "熱門補位" };

function itemIds(ids) {
  return ids.map((id) => {
    const item = document.createElement("span");
    item.textContent = "#" + id;
    return item;
  });
}

function setOutcome(element, arm) {
  const ranks = arm.hit_ranks;
  const miss = transactionMode ? "未命中" : "前十名未命中";
  const length = transactionMode ? (arm.items.length ? "共 " + arm.items.length + " 件 · " : "空榜 · ") : "";
  const hit = purchaseMode ? "第 " + ranks[0] + " 名首次命中" : "第 " + ranks.join("、") + " 名命中";
  element.textContent = length + (ranks.length ? hit : miss);
  element.classList.toggle("has-hit", ranks.length > 0);
}

function badge(cell, label, className) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = label;
  cell.append(span);
}

function addPrediction(row, arm, index, armName) {
  const cell = row.insertCell();
  if (index >= arm.items.length) {
    cell.className = "empty-rank";
    cell.textContent = "—";
    cell.setAttribute("aria-label", "此名次沒有推薦商品");
    return;
  }
  badge(cell, "#" + arm.items[index], "replay-id");
  if (arm.hit_ranks.includes(index + 1)) {
    cell.classList.add("is-hit");
    const first = purchaseMode && index + 1 === arm.hit_ranks[0];
    badge(cell, first ? "首次命中" : "命中", "rank-label hit-label");
  }
  const source = arm.sources?.[index];
  if (source) {
    const label = purchaseMode && armName === "popular" ? "熱門購買" : sourceLabels[source];
    badge(cell, label, "rank-label rank-source");
  } else if (index >= arm.items.length - (arm.zero_fill_slots ?? 0)) {
    badge(cell, "熱門補位", "rank-label");
  }
}

function renderRanking(entry) {
  const rankings = comparison.arms.map((arm) => entry[arm]);
  const outcomes = ["left-outcome", "c1-outcome", "filled-outcome"];
  byId("target-items").replaceChildren(...itemIds(entry.targets));
  rankings.forEach((ranking, i) => setOutcome(byId(outcomes[i]), ranking));
  const tbody = byId("ranked-items");
  tbody.replaceChildren();
  const length = Math.max(...rankings.map((ranking) => ranking.items.length));
  for (let index = 0; index < length; index++) {
    const row = tbody.insertRow();
    const rank = document.createElement("th");
    rank.scope = "row";
    rank.textContent = String(index + 1).padStart(2, "0");
    row.append(rank);
    rankings.forEach((ranking, i) => addPrediction(row, ranking, index, comparison.arms[i]));
  }
}

function setTime(element, timestamp) {
  element.dateTime = timestamp;
  element.textContent = timestamp.replace("T", " ").replace("Z", " UTC");
}

function renderCase(entry) {
  if (!purchaseMode) setTime(byId("query-time"), entry.query_time);
  const history = entry.history ?? [];
  byId("history-context").hidden = !history.length;
  byId("history-items").replaceChildren(...itemIds(history));
  if (transactionMode) byId("seed-item").replaceChildren(...itemIds([entry.seed]));
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
  const activity = purchaseMode ? "同筆交易商品" : cartMode ? "實際加購" : "實際瀏覽";
  byId("announcement").textContent = (comparison.titlePrefix ?? "") + comparison.labels[entry.id]
    + "，排名與" + activity + "已更新。";
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
  const hasCounts = (purchaseMode || (Number.isSafeInteger(total) && total > 0
    && Number.isSafeInteger(group.net_additional_hits))) && entries.every((entry) => Number.isSafeInteger(entry.count));
  const period = byId("validation-period");
  if (purchaseMode && hasCounts) {
    period.textContent = "2015 年 8 月共 " + number.format(group.scorable_queries) + " 次同筆交易查詢。其中 "
      + number.format(group.overlap_queries) + " 次同時發生短榜新增命中與熱門榜命中後移。以下展示兩筆不同查詢。";
  } else if (mode === "cart_fill" && hasCounts) {
    period.textContent = "2015 年 8 月的 " + number.format(group.scorable_queries) + " 次可評分查詢中，共新增 "
      + number.format(total) + " 次命中。兩個按鈕的占比以新增命中為分母，各回放該類的第一筆。";
  } else if (hasCounts) {
    period.textContent = mode === "cart"
      ? "2015 年 8 月開發驗證中，有 " + number.format(total) + " 次能核對下一步加購，兩榜也都有推薦。"
        + "依驗證查詢順序，各回放共同加購榜命中與未命中的第一筆。"
      : "2015 年 8 月開發驗證共 " + number.format(total) + " 次查詢。選一種結果，可回放該類的第一筆紀錄。";
  } else {
    period.textContent = "選一種結果可回放該類的第一筆紀錄。重新啟動本機服務後可查看全體次數與占比。";
  }
  const selected = entries.find((entry) => comparison.prefix + entry.id === requestedCase) || entries[0];
  const choices = byId("case-options");
  byId("slot-comparison").hidden = mode !== "recency";
  byId("baseline-comparison").hidden = mode === "recency";
  byId("baseline-comparison").classList.toggle("purchase-replay", purchaseMode);
  byId("query-context").hidden = purchaseMode;
  byId("third-header").hidden = !purchaseMode;
  byId("recent-context").hidden = mode !== "recency";
  byId("cart-seed").hidden = !transactionMode;
  choices.classList.toggle("two-options", mode !== "baseline");
  choices.classList.toggle("cart-fill-options", mode === "cart_fill");
  choices.classList.toggle("purchase-case-options", purchaseMode);
  if (mode === "recency") {
    byId("case-legend").textContent = "選擇命中變化";
    byId("report-link").href = "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/598900c/docs/PROJECT_PROGRESS.md#recency-slot-validation";
  } else if (mode === "k1") {
    byId("left-model").textContent = "近鄰模型 K1";
    byId("right-model").textContent = "共現模型 C1";
    byId("report-link").href = "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/0d53e4f/docs/STAGE12_K1_AUGUST_READBACK_20261119.md";
  } else if (purchaseMode) {
    byId("left-model").textContent = "原共同購買";
    byId("right-model").textContent = "原熱門購買";
    byId("seed-heading").textContent = "查詢起點商品";
    byId("actual-heading").textContent = "同筆交易實際購買的其他商品";
    byId("actual-note").textContent = "每份榜單只要有一件同筆交易的其他商品，就算命中。";
    byId("ranking-caption").textContent = "同筆交易的三份推薦榜單";
    byId("report-link").href = "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/1654d7c/docs/PROJECT_PROGRESS.md#purchase-popular-fill";
  } else if (cartMode) {
    const filled = mode === "cart_fill";
    byId("left-model").textContent = filled ? "補位前" : "共同加購榜";
    byId("right-model").textContent = filled ? "補位後" : "熱門加購榜";
    byId("actual-heading").textContent = "訪客接著加入購物車";
    byId("actual-note").textContent = "下一個加購時點的其他商品，只要有一件在榜上，這份推薦就算命中。";
    byId("ranking-caption").textContent = "同一次加購的兩種推薦排名，最多十名";
    byId("report-link").href = filled
      ? "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/3a1647a/docs/PROJECT_PROGRESS.md#cart-popular-fill"
      : "https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/blob/a3597dc/docs/PROJECT_PROGRESS.md#cart-august-validation";
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
    if (comparison.titlePrefix) {
      title.textContent = comparison.titlePrefix;
      badge(title, comparison.labels[entry.id], "cart-case-outcome");
    } else {
      title.textContent = comparison.labels[entry.id];
    }
    radio.setAttribute("aria-labelledby", title.id);
    card.append(title);
    if (hasCounts) {
      const stats = document.createElement("span");
      stats.className = "case-stats";
      stats.id = "case-stats-" + caseId;
      if (!purchaseMode) badge(stats, percent.format(entry.count / total), "case-percent");
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
    } else if (mode === "cart") {
      summary.textContent = "至少兩位不同訪客曾在各自的購物過程中一起加購這對商品，才會列入共同加購榜。"
        + "在這 " + number.format(total) + " 次裡，共同加購榜猜中 " + number.format(group.coadd_hit_queries)
        + " 次，熱門加購榜猜中 " + number.format(group.popular_hit_queries) + " 次。";
    } else if (mode === "cart_fill") {
      summary.textContent = "共同加購商品留在原位，再按熱門加購順序補入未上榜的商品。";
    } else if (purchaseMode) {
      summary.textContent = "短榜新增命中與只補空榜比較，命中後移與原熱門購買榜比較。";
    } else {
      const counts = new Map(entries.map((entry) => [entry.id, entry.count]));
      const both = counts.get("both") || 0;
      const popular = (counts.get("p0_only") || 0) + both;
      const cooccurrence = (counts.get("c1_only") || 0) + both;
      summary.textContent = "前十名命中率為熱門榜 " + percent.format(popular / total)
        + "、共現模型 " + percent.format(cooccurrence / total) + "。";
    }
    if (!transactionMode) {
      const net = group.net_additional_hits;
      const difference = document.createElement("strong");
      difference.textContent = net === 0 ? "兩種方法的總命中次數相同。"
        : comparison.netLabel + (net > 0 ? "多" : "少") + "命中 " + number.format(Math.abs(net)) + " 次。";
      summary.append(difference);
    }
    summary.hidden = false;
  }
  renderCase(selected);
  byId("load-state").hidden = true;
  byId("replay").hidden = false;
}

async function loadReplay() {
  byId("retry").hidden = true;
  byId("load-message").textContent = "正在讀取已驗證的歷史紀錄…";
  try {
    const response = await fetch("/api/replay");
    if (response.status === 503) {
      byId("load-message").textContent = transactionMode ? comparison.unavailable
        : "本機缺少可核對的 Stage 10 回放資料。請還原保存包並重新啟動服務。";
      byId("retry").hidden = false;
      return;
    }
    if (!response.ok) throw new Error("replay unavailable");
    const data = await response.json();
    showCases(data);
  } catch {
    byId("load-message").textContent = transactionMode ? comparison.unavailable
      : "無法載入回放。請確認本機服務與 Stage 10 驗證紀錄可用後重試。";
    byId("retry").hidden = false;
  }
}

byId(mode + "-link").setAttribute("aria-current", "page");
if (purchaseMode) {
  byId("intro-description").textContent = "並排對照共同購買、熱門購買與補位後的榜單，查看同筆交易實際買的其他商品。";
} else if (mode === "cart_fill") {
  byId("intro-description").textContent = "並排看原共同加購榜和補滿十席後的榜單，找出補位猜中的商品。";
} else if (mode === "cart") {
  byId("intro-description").textContent = "訪客剛把商品加入購物車，兩份推薦榜單猜中了他接著加的商品嗎？";
}
byId("retry").addEventListener("click", loadReplay);
loadReplay();

const pct = (x) => (x * 100).toFixed(2) + "%";
const usd = (x) => "$" + x.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
const sign = (x) => (x >= 0 ? "pos" : "neg");

async function load() {
  let data;
  try {
    const r = await fetch("/api/dashboard");
    if (!r.ok) throw new Error("unavailable");
    data = await r.json();
  } catch (e) {
    document.getElementById("errorState").classList.remove("hidden");
    document.querySelector("main").classList.add("hidden");
    return;
  }
  renderBadge(data);
  renderChart(data);
  renderCards(data.metrics);
  renderMethodology(data.metrics);
}

function renderBadge(d) {
  const b = document.getElementById("sourceBadge");
  if (d.source === "live") { b.textContent = "即時"; }
  else { b.textContent = "快取"; b.classList.add("cached"); }
  document.getElementById("asOf").textContent = "截至 " + d.as_of.replace("T", " ") + " UTC";
}

function renderChart(d) {
  new Chart(document.getElementById("equityChart"), {
    type: "line",
    data: {
      labels: d.days,
      datasets: [{
        label: "帳戶淨值 (USD)", data: d.equity,
        borderColor: "#2ea043", backgroundColor: "rgba(46,160,67,0.12)",
        fill: true, tension: 0.25, pointRadius: 2, borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } },
        y: { ticks: { color: "#8b949e", callback: (v) => "$" + v }, grid: { color: "#21262d" } },
      },
    },
  });
}

function card(label, value, cls, sub) {
  return `<div class="metric"><div class="label">${label}</div>` +
         `<div class="value ${cls || ""}">${value}</div>` +
         (sub ? `<div class="sub">${sub}</div>` : "") + `</div>`;
}

function renderCards(m) {
  const html = [
    card("總報酬", pct(m.total_return), sign(m.total_return)),
    card("CAGR（年化）", pct(m.cagr), sign(m.cagr)),
    card("年化波動", pct(m.ann_vol)),
    card("最大回撤", pct(m.max_drawdown), "neg"),
    card("Sharpe（年化）", m.sharpe.toFixed(2), "", "± " + m.sharpe_se.toFixed(2) + " (1 s.e.)"),
    card("Sortino（年化）", m.sortino.toFixed(2)),
    card("Calmar", m.calmar.toFixed(2)),
    card("日勝率", pct(m.daily_win_rate)),
    card("最佳 / 最差日", pct(m.best_day) + " / " + pct(m.worst_day)),
    card("起訖淨值", usd(m.start_equity) + " → " + usd(m.end_equity), "", m.start + " → " + m.end),
  ].join("");
  document.getElementById("cards").innerHTML = html;
}

function renderMethodology(m) {
  let txt = `本記錄以真實入金本金 ${usd(m.start_equity)} 起算（鏈上 deposit 可驗證），` +
    `涵蓋 ${m.n_days} 個交易日（${m.start} → ${m.end}）。` +
    `Sharpe 為 ${m.sharpe.toFixed(2)}，標準誤 ±${m.sharpe_se.toFixed(2)}（Lo 2002, iid 近似）。` +
    `指標以 365 日/年、無風險利率 0% 之加密慣例年化。`;
  if (m.n_days < 60) {
    txt += ` 樣本數偏小（N=${m.n_days}），故標準誤帶寬較寬——此為「早期實盤記錄」，` +
      `非定型化的招牌數字；我們選擇誠實揭露而非藏起，讓它隨時間複利累積。`;
  }
  if (m.suspected_cashflows) {
    txt += ` 偵測到 ${m.suspected_cashflows} 日出現 >50% 淨值跳動，可能為出入金；` +
      `若屬實將改用資金加權（時間加權）報酬重算。`;
  }
  document.getElementById("methodologyText").textContent = txt;
}

load();

/* ============ FreshQuant 交易体系课堂 · 交互脚本 ============ */
"use strict";

/* ---------- 工具函数 ---------- */
function fmt(n, digits) {
  if (n === null || n === undefined || isNaN(n)) return "--";
  return Number(n).toLocaleString("zh-CN", {
    minimumFractionDigits: digits === undefined ? 2 : digits,
    maximumFractionDigits: digits === undefined ? 2 : digits,
  });
}
function fmtInt(n) {
  if (n === null || n === undefined || isNaN(n)) return "--";
  return Number(n).toLocaleString("zh-CN");
}
function $(id) { return document.getElementById(id); }

/* ---------- 08 术语表 ---------- */
const GLOSSARY = [
  ["缠论", "一种技术分析理论，用「分型 → 笔 → 线段 → 中枢」描述走势结构，本系统的买卖信号大多由它衍生。"],
  ["CLX", "系统使用的缠论信号模型集合。日线选股一次运行 18 个模型，编号 S0000–S0017。"],
  ["中枢", "连续三段次级别走势重叠形成的区间，本质是「价格震荡整理」的区域。买点常常出现在中枢附近。"],
  ["V 反", "V 型反转：价格急跌后快速收复失地，是 5 分钟级别认可的重要买点类型。"],
  ["MACD 背驰", "价格创出新低，但下跌动能（MACD）明显减弱，说明跌势快到头了，是抄底型买点。"],
  ["回拉中枢", "价格离开中枢后回拉进入中枢区间，系统也会识别这类结构（当前事件链默认不自动交易它）。"],
  ["候选池", "日线 CLX 选股产生的全市场候选结果，供你挑出感兴趣的股票加入自选。"],
  ["must_pool", "核心自选池。5 分钟首开只认池内且未被禁用的股票。"],
  ["stock_pools", "盘中监控池。15/30 分钟 CLX 只监控这里未过期的股票，只看不买。"],
  ["首开", "第一次买入。由 5 分钟信号触发，是持仓周期的起点。"],
  ["做T", "在持仓周期内「跌了补、涨了卖」的循环操作，目的是把持仓成本越做越低。"],
  ["补仓", "价格下跌到计划价位时按计划加仓，摊低整体持仓成本。"],
  ["持仓成本（均价）", "所有仍在手的买入按数量加权的平均价格。补仓会降低它，止盈卖出不影响剩余成本。"],
  ["切片（slice）", "每一笔买入被打成的独立小份，系统按切片精确核算「哪一份该卖」。"],
  ["entry", "一次买入入口，可能由同一订单的多笔成交聚合成一笔。"],
  ["B1/B2/B3", "三个补仓价位（Buy-1/2/3）。价格每跌到一档，就执行该档的补仓计划。"],
  ["L1/L2/L3", "三个止盈价位（Take-Profit-1/2/3）。价格每涨到一档，就卖出一部分仓位。"],
  ["止盈", "达到目标价后卖出兑现利润，落袋为安。"],
  ["止损", "价格跌破设定的底线后卖出，把亏损控制在可接受范围。"],
  ["全仓止损", "整只股票统一设置一个止损价，跌破就卖出全部可卖持仓。"],
  ["单笔止损", "某一笔买入（entry）单独绑定的止损价，只影响这一笔。"],
  ["仓位上限", "单只股票最多占用多少资金。超过上限，系统会拒绝继续买入。"],
  ["冷却时间", "同一标的两笔操作之间的最短间隔，当前为 15 分钟；两次新开仓之间同样 15 分钟。"],
  ["门禁", "账户状态对买入的准入控制：允许开仓 / 仅可加仓 / 强制减仓三种状态。"],
  ["can_use_volume", "券商返回的「可卖数量」，受 T+1 等规则限制。所有卖出量都要先被它截断。"],
  ["Tick", "逐笔行情。止盈止损链路用 Tick 行情判断，价格一到就触发。"],
  ["盘后选股", "收盘后（15:05 之后）才运行的选股流程，用全天数据计算模型结果。"],
  ["信号时效", "信号从发现到被处理的有效窗口，当前为 30 分钟，过期信号会被忽略。"],
  ["委托 / 成交", "「委托」是下单指令；「成交」是券商回报的实际买卖结果，两者都会进账本。"],
  ["对账", "系统内部账本与券商数据的持续核对，发现差异会记录并处理。"],
  ["浮盈 / 浮亏", "按最新价格计算的未实现盈亏。卖出兑现后才变成「已实现盈亏」。"],
  ["T+1", "A 股规则：当天买入的股票当天不能卖出，只能次日及以后卖出。"],
];

/* ---------- 02 多周期漏斗 ---------- */
const PIPELINE = [
  {
    title: "日线 CLX 选股",
    body: "每天收盘后（15:05 之后），系统用冻结的 production_v1 参数运行 18 个缠论模型（S0000–S0017），在全市场股票与 ETF 中寻找形态符合条件的标的，结果进入「候选池」。这一层解决的是<b>「买什么」</b>，它只看日线收盘数据，不可能在这里下单。",
    points: [
      "候选对象：全市场股票 + ETF（融资标的，ETF 额外排除 LOF）",
      "输出：候选池 / 每日选股工作台（/daily-screening?tab=clx）",
      "你的动作：把感兴趣的候选股加入自选，等待盘中确认",
    ],
  },
  {
    title: "15/30 分钟盘中确认",
    body: "第二天盘中，15 分钟与 30 分钟级别的 CLX 模型持续「复查」候选股，确认日线选出来的方向没有走坏。这一层解决的是<b>「现在还能不能关注」</b>，它只记录、提醒、加入盘中观察分组，<b>不直接下单</b>。",
    points: [
      "监控范围：未过期的 stock_pools 盘中池",
      "行为：正信号写入 realtime_screen_multi_period、追加通达信 clx_15_30 分组、发钉钉提醒",
      "排除对象：当前已经持仓的股票（持仓由 1 分钟链管理）",
    ],
  },
  {
    title: "5 分钟首次开仓",
    body: "当候选股还<b>没有持仓</b>、且 5 分钟级别出现「V 反」或「MACD 看涨背驰」时，系统执行<b>第一次买入</b>。5 分钟是「方向已确认后，等一个更精确入场点」的折中周期。",
    points: [
      "前提：股票在 enabled must_pool、当前无持仓、仓位门禁放行",
      "信号：只接受 buy_v_reverse / macd_bullish_divergence 两类",
      "节奏：两次新开仓之间至少间隔 15 分钟",
    ],
  },
  {
    title: "1 分钟做T（持仓管理）",
    body: "一旦成为持仓，管理权就切到 1 分钟级别：出现缠论买点且价格跌出空间时<b>补仓摊低成本</b>；出现卖点且对应买入切片已盈利时<b>卖出部分</b>。循环往复，把持仓成本越做越低。",
    points: [
      "买入路径：1 分钟买点 + 动态下跌阈值 + B1/B2/B3 仓位阶段 + 容量检查",
      "卖出路径：1 分钟卖点 + 逐切片独立盈利阈值，只卖达标的切片",
      "辅助机制：信号时效 30 分钟、买卖冷却 15 分钟、活动买单检查",
    ],
  },
  {
    title: "Tick 止盈止损",
    body: "全程用 Tick（逐笔）行情盯盘。价格到 L1/L2/L3 止盈档就分批兑现；跌破全仓止损或单笔止损就离场。这一层负责<b>「计划内的退出」</b>，与做T的随机性不同，它有明确的价位纪律。",
    points: [
      "三档止盈：L1 卖 1/3、L2 卖剩余 1/2、L3 全部，按触发时总仓位计算",
      "两级止损：全仓止损优先，其次逐 entry 止损",
      "执行约束：卖出量受可卖数量与整手约束，触发后档位关闭防重复",
    ],
  },
];

/* ---------- 04 模拟器：场景数据 ---------- */
const BULL_BANDS = [
  { label: "B3", price: 9.55, kind: "band" },
  { label: "B2", price: 9.25, kind: "band" },
  { label: "B1", price: 8.95, kind: "band" },
  { label: "L1", price: 10.20, kind: "tp" },
  { label: "L2", price: 11.05, kind: "tp" },
  { label: "L3", price: 12.00, kind: "tp" },
];
const BEAR_BANDS = [
  { label: "B3", price: 9.55, kind: "band" },
  { label: "B2", price: 9.25, kind: "band" },
  { label: "B1", price: 8.95, kind: "band" },
  { label: "全仓止损", price: 8.60, kind: "sl" },
];

const BULL_WP = [
  [0, 10.00], [8, 10.05], [16, 9.85], [24, 9.62], [30, 9.45],
  [38, 9.05], [46, 9.75], [54, 9.35], [62, 10.20], [70, 10.75],
  [78, 11.30], [88, 12.25], [94, 12.40],
];
const BEAR_WP = [
  [0, 10.00], [8, 10.05], [16, 9.85], [24, 9.62], [30, 9.45],
  [36, 9.15], [42, 8.90], [48, 8.68], [54, 8.55], [60, 8.40], [66, 8.30],
];

function priceAt(wp, t) {
  if (t <= wp[0][0]) return wp[0][1];
  for (let i = 1; i < wp.length; i++) {
    if (t <= wp[i][0]) {
      const [t0, p0] = wp[i - 1];
      const [t1, p1] = wp[i];
      const k = (t - t0) / (t1 - t0);
      return +(p0 + (p1 - p0) * k).toFixed(2);
    }
  }
  return wp[wp.length - 1][1];
}

function genBars(wp, n) {
  const bars = [];
  let prev = priceAt(wp, 0);
  for (let i = 0; i < n; i++) {
    const c = priceAt(wp, i);
    const o = i === 0 ? c : bars[i - 1].c;
    const hi = +(Math.max(o, c) + Math.random() * 0.06).toFixed(2);
    const lo = +(Math.min(o, c) - Math.random() * 0.06).toFixed(2);
    bars.push({ o, h: hi, l: lo, c });
    prev = c;
  }
  return bars;
}

const EVENTS_BULL = [
  { bar: 5, type: "info", tag: "日线选股", text: "CLX 18 模型盘后扫描完成，该股进入候选池", explain: "收盘后系统在全市场海选，这只股票被 18 个缠论模型中的部分模型选中，进入「候选池」。此时还没有任何买卖动作。" },
  { bar: 12, type: "info", tag: "盘中确认", text: "15/30 分钟模型盘中确认，加入核心自选池", explain: "第二天盘中，15 分钟和 30 分钟级别的模型复查通过，股票进入「must_pool 核心自选池」，成为 5 分钟首开的候选对象。" },
  { bar: 20, type: "buy", tag: "5分钟首开", qty: 1000, text: "5 分钟 V 反信号 → 首次买入 1000 股", explain: "价格急跌后快速反转，5 分钟级别出现「V 反」买点。系统确认：股票在自选池、当前无持仓、仓位门禁放行 → 第一次买入 1000 股。" },
  { bar: 28, type: "buy", tag: "B3 补仓", qty: 500, text: "1 分钟买点 + 跌破 B3(9.55) → 补仓 500 股", explain: "价格继续下跌，跌破了第一档补仓价 B3。同时 1 分钟出现缠论买点、动态下跌阈值也满足 → 补仓 500 股，摊低整体成本。" },
  { bar: 36, type: "buy", tag: "B2 补仓", qty: 500, text: "1 分钟买点 + 跌破 B2(9.25) → 补仓 500 股", explain: "价格再下一城，跌破第二档补仓价 B2。系统再次按计划补仓 500 股。注意：补仓不是无限制的，每档都有仓位上限兜底。" },
  { bar: 45, type: "sell", tag: "做T卖出", qty: 500, targetLabel: "B3 补仓", text: "1 分钟卖点 + B3 切片已盈利 → 卖出 500 股", explain: "价格反弹后出现 1 分钟卖点。系统检查每个买入切片：B3 那一份（成本 9.51）已经盈利，于是只卖这一份 500 股，把约 75 元差价落袋（已实现收益）。至此，两次补仓已把持仓成本从 9.74 摊低到约 9.54，做T 的「低买高卖」循环完成一轮。" },
  { bar: 64, type: "tp", tag: "L1 止盈", ratio: 1 / 3, text: "价格到 L1(10.20) → 卖出当前仓位 1/3", explain: "上涨进入主升段，价格触及第一档止盈价 L1。系统按「触发时总仓位」卖出 1/3，先落袋一部分利润。触发后 L1 档位关闭，防止重复卖。" },
  { bar: 76, type: "tp", tag: "L2 止盈", ratio: 1 / 2, text: "价格到 L2(11.05) → 卖出剩余仓位 1/2", explain: "价格继续上涨，触及第二档止盈价 L2。系统卖出「当时剩余仓位」的一半。L1、L2 两档随之全部关闭。" },
  { bar: 88, type: "tp", tag: "L3 止盈", ratio: 1, text: "价格到 L3(12.00) → 全部清仓", explain: "价格到达第三档止盈价 L3，系统卖出全部剩余仓位，完成一轮完整周期：从日线选股到三次止盈分批离场。" },
  { bar: 92, type: "info", tag: "周期结算", text: "本轮操作完成：做T + 三档止盈全部兑现", explain: "总结这轮操作：5 分钟首开 → 两次补仓摊低成本 → 一次做T卖出 → 三档止盈分批离场。整轮的关键不是「一次买对」，而是「每一步都有纪律」。" },
];

const EVENTS_BEAR = [
  { bar: 5, type: "info", tag: "日线选股", text: "CLX 18 模型盘后扫描完成，该股进入候选池", explain: "同样从日线选股开始。这只股票同样被模型选中进入候选池——选股只解决「值得跟踪」，不保证「一定上涨」。" },
  { bar: 12, type: "info", tag: "盘中确认", text: "15/30 分钟模型盘中确认，加入核心自选池", explain: "盘中确认通过，进入核心自选池，等待 5 分钟首开信号。" },
  { bar: 20, type: "buy", tag: "5分钟首开", qty: 1000, text: "5 分钟 V 反信号 → 首次买入 1000 股", explain: "5 分钟出现 V 反买点，首次买入 1000 股。此刻看起来和乐观线一样——但接下来的走势完全不同。" },
  { bar: 28, type: "buy", tag: "B3 补仓", qty: 500, text: "1 分钟买点 + 跌破 B3(9.55) → 补仓 500 股", explain: "价格下跌触发第一档补仓。系统按计划补仓 500 股摊低成本。此时系统认为：下跌还在「计划内」。" },
  { bar: 36, type: "buy", tag: "B2 补仓", qty: 500, text: "1 分钟买点 + 跌破 B2(9.25) → 补仓 500 股", explain: "价格继续下跌，触发第二档补仓，再买 500 股。总持仓来到 2000 股。补仓带的三个价位已经用掉两个。" },
  { bar: 44, type: "buy", tag: "B1 补仓", qty: 500, text: "1 分钟买点 + 跌破 B1(8.95) → 补仓 500 股", explain: "价格跌破最后一档补仓价 B1，系统按计划补满三档，总持仓 2500 股。三档补仓全部用尽——接下来只能靠止损线兜底。" },
  { bar: 52, type: "sl", tag: "全仓止损", text: "买一价跌破全仓止损(8.60) → 全部清仓", explain: "价格跌破全仓止损价 8.60。这是系统的「最后防线」：不再幻想反弹，全部卖出，把亏损锁定在可控范围。止损之所以重要，是因为「越跌越买」必须有尽头。" },
  { bar: 58, type: "info", tag: "周期结算", text: "若没有止损：价格继续跌到 8.00 会多亏约 1500 元", explain: "对比一下：如果系统没有止损、继续死扛，价格从 8.60 一路跌到 8.00，还要再多亏约 1500 元。止损的意义不是「不亏」，而是「亏得有限」。" },
];

/* ---------- 模拟器状态 ---------- */
let scenario = null;   // {bars, events, snap, logEntries, bands}
let curIdx = 0;
let playing = false;
let timer = null;
let speed = 2;
let lastExplain = "";

function buildScenario(kind) {
  const wp = kind === "bull" ? BULL_WP : BEAR_WP;
  const evDefs = (kind === "bull" ? EVENTS_BULL : EVENTS_BEAR).slice().sort((a, b) => a.bar - b.bar);
  const bars = genBars(wp, kind === "bull" ? 95 : 67);
  const bands = kind === "bull" ? BULL_BANDS : BEAR_BANDS;

  const lots = [];
  const snap = [];
  const logEntries = [];
  const markers = [];
  let ptr = 0;
  let realized = 0;

  function sellFromLots(qty, preferLabel) {
    const alloc = [];
    let need = qty;
    const order = [];
    lots.forEach((l, i) => { if (l.rem > 0) order.push(i); });
    if (preferLabel) {
      const pi = lots.findIndex((l) => l.label === preferLabel && l.rem > 0);
      if (pi >= 0) {
        const tmp = order.filter((i) => i !== pi);
        order.unshift(pi);
        order.splice(1, 0, ...tmp);
      }
    }
    for (const i of order) {
      if (need <= 0) break;
      const take = Math.min(lots[i].rem, need);
      lots[i].rem -= take;
      need -= take;
      alloc.push({ label: lots[i].label, qty: take, price: lots[i].price });
    }
    return alloc;
  }

  function totalQty() { return lots.reduce((s, l) => s + l.rem, 0); }

  for (let i = 0; i < bars.length; i++) {
    while (ptr < evDefs.length && evDefs[ptr].bar <= i) {
      const ev = evDefs[ptr++];
      const close = bars[i].c;
      if (ev.type === "buy") {
        lots.push({ label: ev.tag, price: close, qty: ev.qty, rem: ev.qty });
      } else if (ev.type === "sell") {
        const alloc = sellFromLots(ev.qty, ev.targetLabel);
        alloc.forEach((a) => {
          realized += (close - a.price) * a.qty;
          logEntries.push({
            bar: i, type: "sell", tag: ev.tag, price: close, text: `卖出 ${a.label} ${a.qty} 股 @ ${fmt(close)}`,
          });
        });
      } else if (ev.type === "tp") {
        const qty = ev.ratio === 1 ? totalQty() : Math.floor(totalQty() * ev.ratio);
        const alloc = sellFromLots(qty);
        alloc.forEach((a) => {
          realized += (close - a.price) * a.qty;
          logEntries.push({
            bar: i, type: "tp", tag: ev.tag, price: close, text: `止盈 ${a.label} ${a.qty} 股 @ ${fmt(close)}`,
          });
        });
      } else if (ev.type === "sl") {
        const alloc = sellFromLots(totalQty());
        alloc.forEach((a) => {
          realized += (close - a.price) * a.qty;
          logEntries.push({
            bar: i, type: "sl", tag: ev.tag, price: close, text: `止损清仓 ${a.label} ${a.qty} 股 @ ${fmt(close)}`,
          });
        });
      }
      if (ev.type === "buy" || ev.type === "sell" || ev.type === "tp" || ev.type === "sl") {
        markers.push({ bar: i, type: ev.type, tag: ev.tag, price: bars[i].c });
      }
      logEntries.push({ bar: i, type: ev.type, tag: ev.tag, price: null, text: ev.text, explain: ev.explain });
    }
    const close = bars[i].c;
    const qty = totalQty();
    const cost = lots.reduce((s, l) => s + l.rem * l.price, 0);
    const avg = qty ? cost / qty : 0;
    snap.push({ close, qty, avg, cost, mv: qty * close, pnl: qty * close - cost, realized });
  }

  return { kind, bars, bands, snap, logEntries, markers, lots };
}

/* ---------- K 线渲染 ---------- */
const KW = 920, KH = 400;
const ML = 54, MR = 64, MT = 18, MB = 30;

function renderChart() {
  const wrap = $("kline-wrap");
  const s = scenario;
  const n = s.bars.length;
  const plotW = KW - ML - MR;
  const plotH = KH - MT - MB;

  const allPrices = [];
  s.bars.forEach((b) => { allPrices.push(b.h, b.l); });
  s.bands.forEach((b) => allPrices.push(b.price));
  let pMin = Math.min.apply(null, allPrices);
  let pMax = Math.max.apply(null, allPrices);
  const pad = (pMax - pMin) * 0.08 || 0.5;
  pMin -= pad; pMax += pad;

  const x = (i) => ML + (i + 0.5) * (plotW / n);
  const y = (p) => MT + plotH - ((p - pMin) / (pMax - pMin)) * plotH;
  const bw = Math.max(2.5, (plotW / n) * 0.62);

  let svg = `<svg viewBox="0 0 ${KW} ${KH}" role="img" aria-label="K线模拟图">`;
  svg += `<rect x="0" y="0" width="${KW}" height="${KH}" fill="#101726" rx="8"/>`;
  svg += `<rect x="${ML}" y="${MT}" width="${plotW}" height="${plotH}" fill="none" stroke="#22304d" stroke-width="1"/>`;

  // 网格与 Y 轴刻度
  const yTicks = 6;
  for (let t = 0; t <= yTicks; t++) {
    const p = pMin + ((pMax - pMin) * t) / yTicks;
    const yy = y(p);
    svg += `<line x1="${ML}" y1="${yy}" x2="${ML + plotW}" y2="${yy}" stroke="#1a2337" stroke-width="1"/>`;
    svg += `<text x="${ML - 6}" y="${yy + 4}" text-anchor="end" fill="#93a1bb" font-size="11">${fmt(p, 2)}</text>`;
  }
  // X 轴刻度（每 10 根）
  const xStep = Math.max(10, Math.ceil(n / 12));
  for (let i = 0; i < n; i += xStep) {
    svg += `<text x="${x(i)}" y="${KH - 8}" text-anchor="middle" fill="#93a1bb" font-size="11">${i}</text>`;
  }

  // 价格参考线（补仓带 / 止盈档 / 止损线）
  s.bands.forEach((b) => {
    const yy = y(b.price);
    const color = b.kind === "tp" ? "#a78bfa" : b.kind === "sl" ? "#e11d48" : "#f59e0b";
    svg += `<line x1="${ML}" y1="${yy}" x2="${ML + plotW}" y2="${yy}" stroke="${color}" stroke-width="1" stroke-dasharray="5,4" opacity="0.75"/>`;
    svg += `<text x="${ML + plotW + 4}" y="${yy + 4}" fill="${color}" font-size="11">${b.label} ${fmt(b.price, 2)}</text>`;
  });

  // 当前进度竖线
  if (curIdx >= 0 && curIdx < n) {
    const xx = x(curIdx);
    svg += `<line x1="${xx}" y1="${MT}" x2="${xx}" y2="${MT + plotH}" stroke="#4c8dff" stroke-width="1" stroke-dasharray="3,3"/>`;
  }

  // K 线（只画到当前）
  for (let i = 0; i <= curIdx; i++) {
    const b = s.bars[i];
    const up = b.c >= b.o;
    const color = up ? "#f2574a" : "#22c08a";
    const xx = x(i);
    svg += `<line x1="${xx}" y1="${y(b.h)}" x2="${xx}" y2="${y(b.l)}" stroke="${color}" stroke-width="1"/>`;
    const yTop = y(Math.max(b.o, b.c));
    const hh = Math.max(1.5, Math.abs(y(b.o) - y(b.c)));
    svg += `<rect x="${xx - bw / 2}" y="${yTop}" width="${bw}" height="${hh}" fill="${color}" rx="0.8"/>`;
  }

  // 持仓成本线（只有持仓时）
  let avgPts = [];
  for (let i = 0; i <= curIdx; i++) {
    if (s.snap[i].qty > 0) avgPts.push(`${x(i)},${y(s.snap[i].avg)}`);
  }
  if (avgPts.length > 1) {
    svg += `<polyline points="${avgPts.join(" ")}" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linejoin="round"/>`;
  }

  // 事件标记
  const markerColor = { buy: "#f2574a", sell: "#22c08a", tp: "#a78bfa", sl: "#e11d48" };
  s.markers.forEach((m) => {
    if (m.bar > curIdx) return;
    const xx = x(m.bar);
    const yy = y(m.price);
    const color = markerColor[m.type] || "#4c8dff";
    svg += `<circle cx="${xx}" cy="${yy}" r="5" fill="${color}" stroke="#101726" stroke-width="2"/>`;
    svg += `<text x="${xx}" y="${yy - 9}" text-anchor="middle" fill="${color}" font-size="11" font-weight="500">${m.tag}</text>`;
  });

  svg += "</svg>";
  wrap.innerHTML = svg;
}

/* ---------- 面板渲染 ---------- */
function renderPanels() {
  const s = scenario;
  const snap = s.snap[curIdx];
  const first = s.snap[0].close;
  const last = snap.close;
  const chg = last - first;
  const chgPct = first ? (chg / first) * 100 : 0;

  const priceEl = $("sim-price");
  priceEl.textContent = fmt(last, 2);
  priceEl.className = "sim-price " + (chg >= 0 ? "up" : "down");
  $("sim-chg").textContent = (chg >= 0 ? "+" : "") + fmt(chg, 2) + " (" + (chgPct >= 0 ? "+" : "") + fmt(chgPct, 2) + "%)";

  $("st-qty").textContent = fmtInt(snap.qty);
  $("st-avg").textContent = snap.qty ? fmt(snap.avg, 3) : "--";
  $("st-mv").textContent = snap.qty ? fmt(snap.mv, 0) : "--";
  const realizedEl = $("st-realized");
  realizedEl.textContent = (snap.realized >= 0 ? "+" : "") + fmt(snap.realized, 0);
  realizedEl.className = "stat-value " + (snap.realized >= 0 ? "positive" : "negative");
  const totalEl = $("st-total");
  const totalPnl = snap.pnl + snap.realized;
  totalEl.textContent = (totalPnl >= 0 ? "+" : "") + fmt(totalPnl, 0);
  totalEl.className = "stat-value " + (totalPnl >= 0 ? "positive" : "negative");
  const pnlEl = $("st-pnl");
  if (snap.qty === 0) {
    pnlEl.textContent = "--";
    pnlEl.className = "stat-value";
  } else {
    pnlEl.textContent = (snap.pnl >= 0 ? "+" : "") + fmt(snap.pnl, 0);
    pnlEl.className = "stat-value " + (snap.pnl >= 0 ? "positive" : "negative");
  }

  // 持仓切片
  const lotsEl = $("lots");
  if (s.lots.length === 0 || s.lots.every((l) => l.rem === 0)) {
    lotsEl.innerHTML = '<div class="text-muted text-small">当前无持仓</div>';
  } else {
    lotsEl.innerHTML = s.lots
      .filter((l) => l.rem > 0)
      .map((l) => `<div class="lot"><span>${l.label}</span><span class="lot-qty">${fmtInt(l.rem)} 股</span><span class="lot-price">成本 ${fmt(l.price, 2)}</span></div>`)
      .join("");
  }

  // 日志
  const logEl = $("sim-log");
  const shown = s.logEntries.filter((e) => e.bar <= curIdx).slice(-60);
  logEl.innerHTML = shown
    .map((e) => {
      const cls = "log-item k-" + e.type;
      return `<div class="${cls}"><span class="li-time">[bar ${e.bar}] ${e.tag}</span><div class="li-msg">${e.text}</div></div>`;
    })
    .join("");
  logEl.scrollTop = logEl.scrollHeight;

  // 讲解条
  const latest = s.logEntries.filter((e) => e.bar <= curIdx && e.explain).slice(-1)[0];
  if (latest) {
    lastExplain = latest.explain;
    const tagEl = $("explainer-tag");
    tagEl.textContent = "当前讲解：" + latest.tag;
    tagEl.className = "viz-badge";
    $("explainer-text").innerHTML = latest.explain;
  } else {
    $("explainer-tag").textContent = "等待开始";
    $("explainer-text").textContent = "点击「播放」，从第一根 K 线开始，系统会告诉你每一步发生了什么、为什么。";
  }
}

/* ---------- 播放控制 ---------- */
function stopTimer() {
  if (timer) { clearInterval(timer); timer = null; }
  playing = false;
  $("btn-play").textContent = "▶ 播放";
}
function startTimer() {
  stopTimer();
  if (curIdx >= scenario.bars.length - 1) { curIdx = 0; }
  playing = true;
  $("btn-play").textContent = "⏸ 暂停";
  timer = setInterval(() => {
    if (curIdx >= scenario.bars.length - 1) {
      stopTimer();
      renderAll();
      return;
    }
    curIdx++;
    renderAll();
  }, 460 / speed);
}
function renderAll() {
  renderChart();
  renderPanels();
}
function resetSim() {
  stopTimer();
  curIdx = 0;
  renderAll();
}

/* ---------- 止盈动画 ---------- */
let tpStage = 0;
const TP_STATUS = [
  "未触发：持有 100%",
  "L1 触发：卖出 1/3，剩余 66.7%",
  "L2 触发：再卖剩余 1/2，剩余 33.3%",
  "L3 触发：全部卖出，剩余 0%",
];
function renderTp() {
  const width = [100, 66.6, 33.3, 0][tpStage];
  $("tp-anim-fill").style.width = width + "%";
  $("tp-anim-status").textContent = TP_STATUS[tpStage];
  $("tp-step").setAttribute("aria-pressed", String(tpStage > 0));
  $("tp-step").textContent = tpStage >= 3 ? "演示完成" : "演示：触发 L" + (tpStage + 1);
}

/* ---------- 初始化 ---------- */
function initPipeline() {
  const nodes = document.querySelectorAll(".pipe-node");
  const renderStage = (idx) => {
    const d = PIPELINE[idx];
    $("pipe-detail-title").textContent = d.title;
    $("pipe-detail-body").innerHTML = d.body;
    $("pipe-detail-points").innerHTML = d.points.map((p) => `<li>${p}</li>`).join("");
    nodes.forEach((node, i) => node.setAttribute("aria-pressed", String(i === idx)));
  };
  nodes.forEach((node) => {
    node.addEventListener("click", () => renderStage(Number(node.dataset.pipe)));
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); renderStage(Number(node.dataset.pipe)); }
    });
  });
  renderStage(0);
}

function initGlossary() {
  $("glossary").innerHTML = GLOSSARY.map(
    ([term, desc]) => `<div class="glossary-item"><h3><em>词条</em>${term}</h3><p>${desc}</p></div>`
  ).join("");
}

function initSim() {
  $("path-bull").addEventListener("click", () => { setPath("bull"); });
  $("path-bear").addEventListener("click", () => { setPath("bear"); });
  $("btn-play").addEventListener("click", () => { playing ? stopTimer() : startTimer(); });
  $("btn-prev").addEventListener("click", () => { stopTimer(); if (curIdx > 0) { curIdx--; renderAll(); } });
  $("btn-next").addEventListener("click", () => { stopTimer(); if (curIdx < scenario.bars.length - 1) { curIdx++; renderAll(); } });
  $("btn-reset").addEventListener("click", resetSim);
  $("sim-speed").addEventListener("change", (e) => {
    speed = Number(e.target.value) || 2;
    if (playing) { const i = curIdx; stopTimer(); curIdx = i; startTimer(); }
  });
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toUpperCase();
    if (["BUTTON", "SELECT", "INPUT", "TEXTAREA", "A"].includes(tag)) return;
    if (e.code === "Space") { e.preventDefault(); playing ? stopTimer() : startTimer(); }
  });
  setPath("bull");
}

function setPath(kind) {
  stopTimer();
  scenario = buildScenario(kind);
  curIdx = 0;
  $("path-bull").setAttribute("aria-pressed", String(kind === "bull"));
  $("path-bear").setAttribute("aria-pressed", String(kind === "bear"));
  renderAll();
}

function initTp() {
  $("tp-step").addEventListener("click", () => {
    if (tpStage < 3) tpStage++;
    renderTp();
  });
  $("tp-reset").addEventListener("click", () => { tpStage = 0; renderTp(); });
  renderTp();
}

document.addEventListener("DOMContentLoaded", () => {
  initPipeline();
  initGlossary();
  initSim();
  initTp();
});

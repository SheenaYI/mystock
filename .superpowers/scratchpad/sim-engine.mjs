// sim-engine.mjs
// Pure simulation logic for the "一夜持股法" observation prototype.
// No DOM, no localStorage — every function here must stay unit-testable
// with plain Node. Any randomness must come in via an explicit `rng` param.

export const INDUSTRIES = ['半导体', '新能源', '医药生物', '消费电子', '军工', '食品饮料', '有色金属', '汽车零部件'];

const NAME_PREFIXES = ['锐晶', '恒远', '天启', '云图', '星辰', '沃德', '鼎盛', '华锦', '翔宇', '博源', '联创', '嘉合', '瑞德', '迅捷', '长风'];
const NAME_SUFFIXES = ['科技', '实业', '材料', '制药', '电子', '动力', '精工', '控股', '股份', '集团'];

// mulberry32 PRNG — small, fast, deterministic for a given seed.
export function createRng(seed) {
  let state = seed >>> 0;
  return function rng() {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createStockPool(rng, count = 36) {
  const pool = [];
  for (let i = 0; i < count; i++) {
    const industry = INDUSTRIES[i % INDUSTRIES.length];
    const prefix = NAME_PREFIXES[Math.floor(rng() * NAME_PREFIXES.length)];
    const suffix = NAME_SUFFIXES[Math.floor(rng() * NAME_SUFFIXES.length)];
    pool.push({
      id: `SIM${String(i + 1).padStart(3, '0')}`,
      name: `${prefix}${suffix}`,
      industry,
      baseMarketCapYi: 30 + rng() * 220, // 30~250亿
      volatility: 0.5 + rng() * 1.0,     // 0.5~1.5
    });
  }
  return pool;
}

export function generateDailyMetrics(stock, rng) {
  const changePct = -3 + rng() * 11; // -3% ~ +8%; most rolls won't clear the 3-5% filter, mirrors real distribution
  const volumeRatio = 0.5 + rng() * 2.5;
  const turnoverPct = 1 + rng() * 14;
  const marketCapYi = stock.baseMarketCapYi * (0.9 + rng() * 0.2);
  const hadLimitUpIn20d = rng() < 0.35;
  const aboveAvgLine = rng() < 0.55;
  const above5And10Day = rng() < 0.5;
  const volumeStepPattern = rng() < 0.4;
  const inTopHotSector = rng() < 3 / INDUSTRIES.length; // roughly "top 3 sectors of the day" odds
  const basePrice = 8 + rng() * 60; // 8~68元
  const closePrice = Number((basePrice * (1 + changePct / 100)).toFixed(2));
  return {
    stockId: stock.id, changePct, volumeRatio, turnoverPct, marketCapYi,
    hadLimitUpIn20d, aboveAvgLine, above5And10Day, volumeStepPattern, inTopHotSector,
    closePrice,
  };
}

export const DEFAULT_STRATEGY_PARAMS = Object.freeze({
  changePctMin: 3, changePctMax: 5,
  volumeRatioMin: 1.4,
  marketCapMinYi: 50, marketCapMaxYi: 200,
  turnoverMinPct: 5, turnoverMaxPct: 10,
  maxSingleStockPct: 20,
  maxTotalPositionPct: 50,
  maxHoldings: 3,
  takeProfitOpenPctMin: 2,
  stopLossOpenPct: -1.5,
});

export function scoreCandidate(stock, metrics, params) {
  const reasons = [];
  const hardChecks = [
    { pass: metrics.changePct >= params.changePctMin && metrics.changePct <= params.changePctMax,
      reason: `涨幅${metrics.changePct.toFixed(1)}%（要求${params.changePctMin}%~${params.changePctMax}%）` },
    { pass: metrics.volumeRatio >= params.volumeRatioMin,
      reason: `量比${metrics.volumeRatio.toFixed(2)}（要求>${params.volumeRatioMin}）` },
    { pass: metrics.marketCapYi >= params.marketCapMinYi && metrics.marketCapYi <= params.marketCapMaxYi,
      reason: `流通市值${metrics.marketCapYi.toFixed(0)}亿（要求${params.marketCapMinYi}~${params.marketCapMaxYi}亿）` },
    { pass: metrics.turnoverPct >= params.turnoverMinPct && metrics.turnoverPct <= params.turnoverMaxPct,
      reason: `换手率${metrics.turnoverPct.toFixed(1)}%（要求${params.turnoverMinPct}%~${params.turnoverMaxPct}%）` },
  ];
  const passedHardFilters = hardChecks.every(c => c.pass);
  hardChecks.forEach(c => { if (c.pass) reasons.push(c.reason); });

  const softFlags = [
    [metrics.hadLimitUpIn20d, '20日内有过涨停'],
    [metrics.aboveAvgLine, '全天站稳均价线上方'],
    [metrics.above5And10Day, '站稳5日/10日线'],
    [metrics.volumeStepPattern, '成交量台阶式放量'],
    [metrics.inTopHotSector, `属于今日热点板块「${stock.industry}」前三`],
  ];
  let softScore = 0;
  softFlags.forEach(([flag, reason]) => { if (flag) { softScore += 1; reasons.push(reason); } });

  const score = passedHardFilters
    ? 0.5 + (softScore / softFlags.length) * 0.5
    : (softScore / softFlags.length) * 0.3;

  return { passedHardFilters, score: Number(score.toFixed(3)), reasons };
}

export function pickTopDiverse(pool, metricsByStockId, params, count = 3) {
  const scored = pool
    .map(stock => {
      const metrics = metricsByStockId[stock.id];
      const { passedHardFilters, score, reasons } = scoreCandidate(stock, metrics, params);
      return { ...stock, ...metrics, passedHardFilters, score, reasons };
    })
    .filter(c => c.passedHardFilters)
    .sort((a, b) => b.score - a.score);

  const picks = [];
  const usedIndustries = new Set();
  for (const c of scored) {
    if (picks.length >= count) break;
    if (usedIndustries.has(c.industry)) continue;
    picks.push(c);
    usedIndustries.add(c.industry);
  }
  if (picks.length < count) {
    for (const c of scored) {
      if (picks.length >= count) break;
      if (picks.includes(c)) continue;
      picks.push(c);
    }
  }
  return picks;
}

export function selectDailyPicks(pool, params, rng, count = 3) {
  const metricsByStockId = {};
  for (const stock of pool) {
    metricsByStockId[stock.id] = generateDailyMetrics(stock, rng);
  }
  return pickTopDiverse(pool, metricsByStockId, params, count);
}

export function computeBuyPriceRange(closePrice) {
  return {
    low: Number((closePrice * 0.995).toFixed(2)),
    high: Number((closePrice * 1.005).toFixed(2)),
    suggested: closePrice,
  };
}

export function computePositions(picks, capital, params) {
  const n = Math.min(params.maxHoldings, picks.length);
  const chosen = picks.slice(0, n);
  if (chosen.length === 0) return [];

  const totalBudget = capital * (params.maxTotalPositionPct / 100);
  const perStockCap = capital * (params.maxSingleStockPct / 100);
  const perStockBudget = Math.min(totalBudget / chosen.length, perStockCap);

  return chosen.map(c => {
    const buyPrice = c.closePrice;
    const shares = Math.floor(perStockBudget / buyPrice / 100) * 100;
    const investedAmount = Number((shares * buyPrice).toFixed(2));
    return {
      stockId: c.id, name: c.name, industry: c.industry,
      buyPrice, shares, investedAmount, score: c.score, reasons: c.reasons,
    };
  });
}

export function simulateNextDayChangePct(score, rng) {
  // Box-Muller transform for an approximately normal draw, mean shifted by
  // matchScore so that better-matching picks (per the configured strategy
  // params) are more likely to gap up the next morning. This is what makes
  // tuning the strategy parameters visibly change the win rate/equity curve
  // instead of producing pure noise.
  const u1 = Math.min(Math.max(rng(), 1e-9), 1 - 1e-9);
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  const baseStdPct = 2.2;
  const meanBiasPct = (score - 0.5) * 4; // score 0..1 -> bias -2pp..+2pp
  return z * baseStdPct + meanBiasPct;
}

function classifyOutcome(changePct, params) {
  if (changePct <= params.stopLossOpenPct) return 'stop_loss';
  if (changePct >= params.takeProfitOpenPctMin) return 'take_profit';
  return 'flat_exit';
}

export function resolveSellOutcome(position, nextDayChangePct, params) {
  const sellPrice = Number((position.buyPrice * (1 + nextDayChangePct / 100)).toFixed(2));
  const ruleTriggered = classifyOutcome(nextDayChangePct, params);
  const pnlAmount = Number(((sellPrice - position.buyPrice) * position.shares).toFixed(2));
  const pnlPct = Number((((sellPrice - position.buyPrice) / position.buyPrice) * 100).toFixed(2));
  return { stockId: position.stockId, name: position.name, buyPrice: position.buyPrice, sellPrice, pnlAmount, pnlPct, ruleTriggered };
}

export function createInitialState(initialCapital, strategyParams = DEFAULT_STRATEGY_PARAMS) {
  return {
    day: 1,
    phase: 'selection',
    initialCapital,
    capital: initialCapital,
    positions: [],
    lastPicks: [],
    lastSettlement: null,
    history: [],
    strategyParams: { ...strategyParams },
    stockPool: null,
  };
}

export function resetSimulation(initialCapital, strategyParams, rng) {
  const state = createInitialState(initialCapital, strategyParams);
  return { ...state, stockPool: createStockPool(rng) };
}

export function runSelectionPhase(state, rng) {
  if (state.phase !== 'selection') {
    throw new Error(`runSelectionPhase called in phase "${state.phase}", expected "selection"`);
  }
  const picks = selectDailyPicks(state.stockPool, state.strategyParams, rng, 3);
  const positions = computePositions(picks, state.capital, state.strategyParams);
  const investedTotal = positions.reduce((sum, p) => sum + p.investedAmount, 0);
  return {
    ...state,
    phase: 'holding',
    lastPicks: picks,
    positions,
    capital: Number((state.capital - investedTotal).toFixed(2)),
  };
}

export function runSettlementPhase(state, rng) {
  if (state.phase !== 'holding') {
    throw new Error(`runSettlementPhase called in phase "${state.phase}", expected "holding"`);
  }
  const settlement = state.positions.map(position => {
    const changePct = simulateNextDayChangePct(position.score, rng);
    return resolveSellOutcome(position, changePct, state.strategyParams);
  });
  const proceedsTotal = settlement.reduce((sum, s) => {
    const position = state.positions.find(p => p.stockId === s.stockId);
    return sum + s.sellPrice * position.shares;
  }, 0);
  const totalPnlAmount = Number(settlement.reduce((sum, s) => sum + s.pnlAmount, 0).toFixed(2));
  const winCount = settlement.filter(s => s.pnlAmount > 0).length;
  const newCapital = Number((state.capital + proceedsTotal).toFixed(2));
  const historyEntry = {
    day: state.day,
    picks: state.lastPicks,
    results: settlement,
    totalPnlAmount,
    totalPnlPct: Number(((totalPnlAmount / state.initialCapital) * 100).toFixed(2)),
    winCount,
    capitalAfter: newCapital,
  };
  return {
    ...state,
    phase: 'selection',
    day: state.day + 1,
    capital: newCapital,
    positions: [],
    lastSettlement: settlement,
    history: [...state.history, historyEntry],
  };
}

export function updateStrategyParams(state, newParams) {
  return { ...state, strategyParams: { ...state.strategyParams, ...newParams } };
}

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

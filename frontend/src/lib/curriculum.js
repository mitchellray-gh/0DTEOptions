// Learn-tab content: guided lessons + quizzes on 0DTE options. Content only —
// no dependencies. Progress is tracked in localStorage by the LearnPage.
//
// Lesson bodies use a tiny markup: **bold** is honored by the renderer; blank
// lines separate paragraphs.

export const LESSONS = [
  {
    id: 'what-is-0dte',
    title: 'What is a 0DTE option?',
    minutes: 3,
    body: `A **0DTE** option is one that **expires today** — "zero days to expiration."

Buying a call is a bet the stock rises; buying a put is a bet it falls. Because there's no time left, 0DTE options are almost pure bets on the next few hours of price movement.

They are **extremely high risk**: the value can go to **zero within minutes**, and unlike longer-dated options there's no time for the trade to recover. Most professionals treat 0DTE as speculation, not investing.`,
    quiz: {
      question: 'What does "0DTE" mean?',
      options: [
        'The option expires today',
        'The option has zero delta',
        'A zero-commission trade',
        'A dividend-adjusted expiry',
      ],
      answer: 0,
      explain: '0DTE = zero days to expiration — it expires at the end of today\'s session.',
    },
  },
  {
    id: 'calls-vs-puts',
    title: 'Calls vs. puts',
    minutes: 3,
    body: `A **call** gives you the right to BUY 100 shares at the strike price. You buy calls when you think the price will go **up**.

A **put** gives you the right to SELL 100 shares at the strike. You buy puts when you think the price will go **down**.

Each contract controls **100 shares**, so a $0.50 premium actually costs **$50** (0.50 × 100). Your maximum loss when buying is the premium you paid — but that can be a total loss.`,
    quiz: {
      question: 'You expect SPY to fall this afternoon. Which do you buy?',
      options: ['A call', 'A put', 'Shares', 'A bond'],
      answer: 1,
      explain: 'Puts profit when the underlying falls.',
    },
  },
  {
    id: 'greeks',
    title: 'The Greeks (in plain English)',
    minutes: 4,
    body: `**Delta** — how much the option moves per $1 move in the stock. A 0.50 delta call gains ~$0.50 for every $1 the stock rises.

**Gamma** — how fast delta changes. 0DTE options have huge gamma near the strike, so P&L swings violently.

**Theta** — time decay. It's how much value the option loses each day just from time passing. On expiration day theta is brutal — extrinsic value bleeds to zero by the close.

**Vega** — sensitivity to implied volatility. Less important for 0DTE because there's so little time left.`,
    quiz: {
      question: 'Which Greek measures time decay?',
      options: ['Delta', 'Gamma', 'Theta', 'Vega'],
      answer: 2,
      explain: 'Theta is the daily loss of value from time passing — vicious on 0DTE.',
    },
  },
  {
    id: 'iv-and-edge',
    title: 'Implied volatility & "edge"',
    minutes: 4,
    body: `**Implied volatility (IV)** is the market's guess at how much the stock will move, baked into the option's price. Higher IV = more expensive options.

This app computes a **reference IV** — the volume-weighted IV of near-the-money contracts — as a "fair" anchor for the whole chain. It then reprices each contract with Black-Scholes at that IV.

When a contract's **ask** is meaningfully **below** its fair value, that gap is the **edge**. But edge is an approximation, not a guarantee: quotes are delayed, and a small edge is easily eaten by spreads and commissions.`,
    quiz: {
      question: 'In this app, "edge" is the gap between a contract\'s ask and its…',
      options: [
        'Black-Scholes fair value at the chain\'s reference IV',
        'Opening price',
        '52-week high',
        'Dividend yield',
      ],
      answer: 0,
      explain: 'Edge = fair value (BS at reference IV) minus the ask price.',
    },
  },
  {
    id: 'position-sizing',
    title: 'Position sizing & risk',
    minutes: 3,
    body: `Never risk more than a small slice of your account on a single 0DTE trade. This app sizes trades so the **entire premium** (the worst case, a 100% loss) stays within your chosen risk-per-trade, e.g. 2% of the account.

If your account is $5,000 and you risk 2%, that's **$100** of premium per idea. At $0.50/contract that's about **2 contracts**.

Sizing by worst-case loss is what keeps one bad 0DTE trade from becoming a catastrophic one.`,
    quiz: {
      question: 'A $10,000 account, 2% risk. Roughly how much premium per trade?',
      options: ['$2,000', '$1,000', '$200', '$20'],
      answer: 2,
      explain: '2% of $10,000 = $200 of premium at risk per trade.',
    },
  },
  {
    id: 'exits',
    title: 'Take-profit, stop-loss & discipline',
    minutes: 4,
    body: `Every trade plan here stages an **exit before you enter**: a take-profit (partway to fair value) and a stop-loss (about 50% of premium).

Here's the hard truth this app's own backtester surfaces: with a **small** take-profit versus a **large** stop, the reward:risk can be worse than 1:1 — which means even a decent win-rate can still lose money after commissions and 0DTE theta.

The lesson: respect your stops, take profits mechanically, and understand that **frequent small wins can be wiped out by a few full-premium losses**. Discipline and sizing matter more than being "right."`,
    quiz: {
      question: 'Why can a high win-rate 0DTE strategy still lose money?',
      options: [
        'Losses (near full premium) can be much larger than the small wins',
        'Because commissions are illegal',
        'Because puts always expire worthless',
        'It can\'t — high win-rate always wins',
      ],
      answer: 0,
      explain: 'If wins are small and losses are near-total, negative expectancy dominates.',
    },
  },
];

export const LS_PROGRESS = 'zdte.progress';

export function loadProgress() {
  try {
    const raw = localStorage.getItem(LS_PROGRESS);
    const p = raw ? JSON.parse(raw) : {};
    return p && typeof p === 'object' ? p : {};
  } catch {
    return {};
  }
}

export function saveProgress(p) {
  try { localStorage.setItem(LS_PROGRESS, JSON.stringify(p)); } catch { /* ignore */ }
}

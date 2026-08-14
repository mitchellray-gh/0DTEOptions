import React from 'react';

/**
 * Methodology & Data — plainly explains what the app's strategy research is
 * trained/tested on, and the honest audit conclusions. Linked from Learn.
 */
export default function MethodologyPage() {
  return (
    <div className="rh-page">
      <h2>Methodology &amp; Data</h2>
      <p className="rh-lead">
        Full transparency on what this app is built from, what's real vs modeled,
        and what our own risk audits concluded. Read this before trusting any number.
      </p>

      <div className="rh-card">
        <h4>📊 What the research is trained on</h4>
        <p>
          The credit-spread / iron-condor research uses <strong>real historical
          options data from Databento (OPRA feed)</strong> — the consolidated US
          options tape. Specifically: <strong>SPY 1-minute consolidated best
          bid/offer (CBBO-1m)</strong>, ~56 real trading days (May–Aug 2026). The
          underlying price is derived from live option quotes via put-call parity.
          No synthetic prices are used in the audited backtest.
        </p>
      </div>

      <div className="rh-card">
        <h4>🟢 What's real vs. ⚠️ modeled</h4>
        <div className="rh-lesson-body">
          <p><strong>Real:</strong> option bid/ask, the underlying path, all
          fills priced at the true bid (sells) and ask (buys), plus 1-tick
          slippage and $0.65/contract commissions.</p>
          <p><strong>Modeled / approximated:</strong> probability-of-profit (via
          Black-Scholes N(d2)), and — for the live app's charts &amp; some
          fallbacks — data that is <strong>~15 minutes delayed</strong> (CBOE /
          Yahoo). The live scanner is NOT real-time.</p>
        </div>
      </div>

      <div className="rh-card">
        <h4>🔍 What our audits found (the honest part)</h4>
        <div className="rh-lesson-body">
          <p>We ran the strategy through a <strong>quant risk audit</strong> and
          an <strong>infrastructure audit</strong>. Both flagged serious issues:</p>
          <p>• An early "+50% return" result was <strong>a mirage</strong> — it
          used mid-prices and was optimized on the same data it was measured on.</p>
          <p>• Re-run correctly (real bid/ask fills + an out-of-sample split), the
          edge <strong>collapsed</strong>: it barely beat buy-and-hold on a
          handful of trades and <strong>FAILED</strong> the overfitting test.</p>
          <p>• The sample (56 days, one calm market regime) is far too small and
          has <strong>not</strong> been crash-tested.</p>
          <p><strong>Conclusion: no reliable, tradable edge has been proven.</strong>{' '}
          That's a feature, not a bug — the pipeline is designed to expose false
          edges rather than sell you one.</p>
        </div>
      </div>

      <div className="rh-card">
        <h4>🚫 Why this is not a live trading system</h4>
        <p>
          The app polls delayed data over REST, stores paper positions in your
          browser, and has <strong>no broker connection, no order routing, and no
          streaming execution layer</strong>. Live 0DTE options trading needs a
          separate, fault-tolerant streaming service (WebSockets, order state
          machine, crash recovery, a server-side risk watchdog). None of that
          lives here by design.
        </p>
      </div>

      <footer className="disclaimer" style={{ marginTop: 16 }}>
        <strong>Educational use only.</strong> Nothing here is investment advice.
        Backtested and simulated results do not predict live performance. 0DTE
        options can lose 100% of premium in minutes. Never trade money you can't
        afford to lose.
      </footer>
    </div>
  );
}

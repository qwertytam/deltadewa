# Weekly Digest — BREACH: Annual carry cost out of policy (1st week)

**As of:** 2026-08-05

## What changed

Compared against the snapshot from 2026-07-29.

**Threshold crossings:**

- **Worst roll verdict:** MONITOR → N/A
- **Carry budget:** within budget → over budget
- **IPS compliance (overall):** all pass → a metric failing
- **IPS compliance: Annual carry cost:** pass → fail

**Other material moves:**

- **Convexity:** 18.00% → 19.00% (+1.00%)
- **VIX:** 18.00 → 22.00 (+4.00)
- **Carry as % of notional:** 1.00% → 1.15% (+0.15pp)

---

# Part VII: Hedge Program Report

**Program:** SPX Tail Hedge (SPX)  
**Period:** Week of 2026-08-05  
**As of:** 2026-08-05

---

## 1. Cost

| Metric | Value |
|--------|-------|
| Annual theta (carry cost) | -$73,000 |
| Carry as % of book notional | 1.15% |
| IPS budget | ≤ 1.00% |
| Status | ✗ FAIL |

## 2. Protection

| Metric | Value |
|--------|-------|
| Premium paid | $300,000 (paid) |
| IPS crash scenario | -25% shock |
| Payoff ratio at crash | 8.5× |
| Convexity (net P&L % of book) | 19.0% |
| IPS convexity target | 15.0%–25.0% of book |
| Status | ✓ PASS |

## 3. Market Context

| Metric | Value |
|--------|-------|
| VIX | 22.0 |
| VIX regime | NORMAL |
| SKEW percentile | 45.0% |
| Hedge-cost verdict | FAIR |
| Data quality | CACHED |

## 4. Return Framing

| | Value |
|---|-------|
| Annual carry drag | −1.15% |
| Carry cost this period | $1,400 over 7 day(s) |
| Cumulative carry cost since 2026-07-01 | $2,800 |
| Point-in-time premium invested | $300,000 |

> Before/after-hedge total return (start/end book value) is not tracked; the figures above are carry consumption only, not a return.

## 5. Monetization Realized

Realized gains: **n/a — planned (C4)**

_Monetization is reported separately and never netted against carry cost._  
IPS schedule: 2 step(s) defined.

## 6. IPS Compliance

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Annual carry cost | ≤ 1.00% of notional | 1.15% | ✗ FAIL |
| Crash convexity (-25% shock) | 15.0%–25.0% of book | 19.0% | ✓ PASS |

**Overall: ✗ FAIL**

**Recommended action — Annual carry cost:** Carry is above the IPS budget — trim size.

## 7. Decision & entry timing

**Verdict:** MAINTAIN  
**Rationale:** test rationale

**Entry-timing recommendation:** test entry recommendation


---
Running v0.8.2

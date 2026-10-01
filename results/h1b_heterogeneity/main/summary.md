# H1b main (main result; seeds 2026260001-2026260230, n = 230, D = 0.01)

| Condition | median τ | non-recovery (R_pre = 0) | median R_pre | median A deliveries [0, 12,000) | follower fraction | first B delivery after move, median [IQR] | B deliveries [12,000, 18,000) |
|---|---|---|---|---|---|---|---|
| homo (100 × 60°) | 10,844 | 37 (0) | 300 | 896 | 0.243 | 1,868 [909, 3,804] | 72 [15, 184] |
| het120 (20 × 120° + 80 × 37.43°) | 13,184 | 50 (1) | 334 | 974 | 0.243 | 1,852 [841, 3,422] | 64 [7, 183] |

Δ = median τ(het120) − median τ(homo) = **2,341** steps, paired bootstrap 95% CI [721, 4,148] (10,000 resamples). Per-seed paired τ difference, median [IQR]: 0 [-2,328, 5,776].
Static efficiency ratio het120 / homo: median **1.09** [1.02, 1.17] (seeds excluded for zero homo deliveries: 0).

Verdict rule: (a) median shorter False; (b) CI excludes 0 True; (c) efficiency ratio ≥ 0.8 True → **not supported**.

Secondary, descriptive (not used for the verdict): paired median difference het120 − homo in time to first B delivery -194 steps; in B deliveries [12,000, 18,000) 5.
het120 pickups by group (all seeds, A / B): scouts 50950 / 72130, recruits 172687 / 426211; first B pickup by a scout in 37 of 230 seeds (scouts are 20% of ants).

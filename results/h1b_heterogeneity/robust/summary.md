# H1b robust (robustness, exploratory; seeds 2026270001-2026270230, n = 230, D = 0.02)

| Condition | median τ | non-recovery (R_pre = 0) | median R_pre | median A deliveries [0, 12,000) | follower fraction | first B delivery after move, median [IQR] | B deliveries [12,000, 18,000) |
|---|---|---|---|---|---|---|---|
| homo (100 × 60°) | 13,708 | 57 (1) | 198 | 576 | 0.194 | 1,484 [782, 2,879] | 15 [4, 75] |
| het120 (20 × 120° + 80 × 37.43°) | 16,097 | 76 (1) | 236 | 676 | 0.203 | 1,978 [1,100, 3,165] | 14 [3, 51] |

Δ = median τ(het120) − median τ(homo) = **2,389** steps, paired bootstrap 95% CI [321, 4,694] (10,000 resamples). Per-seed paired τ difference, median [IQR]: 436 [-2,322, 7,656].
Static efficiency ratio het120 / homo: median **1.19** [1.09, 1.36] (seeds excluded for zero homo deliveries: 0).

Verdict rule: (a) median shorter False; (b) CI excludes 0 True; (c) efficiency ratio ≥ 0.8 True → **not supported**.

Secondary, descriptive (not used for the verdict): paired median difference het120 − homo in time to first B delivery 192 steps; in B deliveries [12,000, 18,000) -2.
het120 pickups by group (all seeds, A / B): scouts 38527 / 34610, recruits 127756 / 232917; first B pickup by a scout in 29 of 230 seeds (scouts are 20% of ants).

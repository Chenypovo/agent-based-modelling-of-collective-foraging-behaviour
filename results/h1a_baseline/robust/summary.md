# robust (robustness, exploratory; seeds 2026250001-2026250020, D = 0.02, thresholds 0.25/0.125)

| half-life | median tau | non-recovery (of which R_pre=0) | median R_pre | median A deliveries [0,12000) | efficiency ratio vs 1000 [95% CI] | follower fraction |
|---|---|---|---|---|---|---|
| 250 | 9131 | 5 (1) | 6 | 56 | 0.21 [0.12, 0.43] | 0.011 |
| 500 | 24000 | 11 (2) | 90 | 359 | 0.76 [0.47, 0.90] | 0.078 |
| 1000 | 9006 | 5 (0) | 178 | 576 | 1.00 [1.00, 1.00] | 0.207 |
| 2000 | 9132 | 0 (0) | 138 | 670 | 1.06 [0.88, 1.20] | 0.326 |
| 4000 | 9614 | 1 (0) | 73 | 466 | 0.74 [0.56, 1.18] | 0.426 |

Seeds excluded from efficiency ratio (zero deliveries at half-life 1000): 0

Paired bootstrap (10,000 resamples) of delta = median tau(intermediate) - median tau(extreme):

| intermediate | extreme | delta | 95% CI |
|---|---|---|---|
| 500 | 250 | 14869 | [-1884, 18384] |
| 500 | 4000 | 14386 | [-977, 14740] |
| 1000 | 250 | -126 | [-7218, 7307] |
| 1000 | 4000 | -608 | [-3430, 5808] |
| 2000 | 250 | 2 | [-6468, 4320] |
| 2000 | 4000 | -481 | [-2432, 4509] |

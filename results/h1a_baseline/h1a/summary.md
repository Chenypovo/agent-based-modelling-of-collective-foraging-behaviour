# h1a (main result; seeds 2026240001-2026240020, D = 0.01, thresholds 0.25/0.125)

| half-life | median tau | non-recovery (of which R_pre=0) | median R_pre | median A deliveries [0,12000) | efficiency ratio vs 1000 [95% CI] | follower fraction |
|---|---|---|---|---|---|---|
| 250 | 11046 | 6 (0) | 138 | 451 | 0.52 [0.44, 0.64] | 0.084 |
| 500 | 9802 | 5 (0) | 190 | 701 | 0.84 [0.62, 0.89] | 0.160 |
| 1000 | 12910 | 6 (0) | 298 | 923 | 1.00 [1.00, 1.00] | 0.239 |
| 2000 | 8578 | 3 (0) | 318 | 927 | 0.97 [0.93, 1.10] | 0.358 |
| 4000 | 14909 | 1 (0) | 294 | 943 | 0.97 [0.93, 1.07] | 0.465 |

Seeds excluded from efficiency ratio (zero deliveries at half-life 1000): 0

Paired bootstrap (10,000 resamples) of delta = median tau(intermediate) - median tau(extreme):

| intermediate | extreme | delta | 95% CI |
|---|---|---|---|
| 500 | 250 | -1244 | [-7654, 6117] |
| 500 | 4000 | -5107 | [-9776, 2500] |
| 1000 | 250 | 1863 | [-7796, 9946] |
| 1000 | 4000 | -2000 | [-8292, 3600] |
| 2000 | 250 | -2469 | [-10919, 2612] |
| 2000 | 4000 | -6332 | [-10840, -4268] |

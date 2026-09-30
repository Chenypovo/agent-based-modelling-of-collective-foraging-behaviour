# PH6780 Stage 3D matched-lifetime decay-law ablation

## Evidence status

Stage 3D is a prospective exploratory extension designed after the Stage 3C Mechanism FAIL result was observed. It is not an independent confirmatory study. Engineering validity, interaction classification, and descriptive endpoints are reported separately.

Engineering status: **PASS**. All 40 new hard-cutoff arms and all 40 reused exponential arms passed identity, receipt, configuration, integrity, and resource validation. The matched-lifetime audit, hard-cutoff versus exponential single-change audit, and within-hard-cutoff B0/C single-change audit passed. Stage 3C was reused read-only from 436 files with frozen snapshot SHA-256 `414b413aed3fab6ed62f7e69dc35bd6e58d7f9055618a293bd47819e8537e7ed`.

The outcome-blind formal run started at `2026-09-22T22:14:42+0800` (`2026-09-22T14:14:42Z`) and ended at `2026-09-22T23:20:19+0800` (`2026-09-22T15:20:19Z`) with exit code 0. The recorded wall-clock interval was 3,937 seconds. Across the 40 arms, measured process CPU totalled 1,278.887689 seconds and measured arm wall time totalled 1,300.686860 seconds. The largest single-arm CPU time was 38.363145 seconds, largest arm wall time was 47.155072 seconds, maximum recorded peak RSS was 782,196,736 bytes, largest retained arm was 8,713,058 bytes, and largest single file was 8,576,165 bytes. All values were below their frozen limits.

Frozen classification: **NO_CLEAR_INTERACTION**.

## Frozen design

The study reused the 20 completed exponential B0/C pairs from Stage 3C and added 20 hard-cutoff B0/C pairs with the same seeds. The hard cutoff was 2,000 steps, matching only the theoretical single-deposit lifetime from q=1 to signal_off=0.25 under a 1,000-step exponential half-life. Diffusion remained zero. C retained the frozen 24-step recovery search; all other paired dynamics were unchanged.

## Primary interaction

| Quantity | Result |
|---|---:|
| Mean interaction, d_cut − d_exp | -408.4000 steps |
| 95% paired bootstrap interval | [-1974.2538, 1022.3137] |
| Hard-cutoff pre-A ratio, C/B0 | 0.744444 |
| Classification | **NO_CLEAR_INTERACTION** |

The interaction is negative when the relative C effect is more favourable under hard cutoff and positive when it is less favourable. Classification follows only the frozen interval, identity, completeness, and pre-A safeguards.

## Four-cell primary summaries

| Cell | Mean capped time | Median | Non-delivery |
|---|---:|---:|---:|
| Exponential B0 | 7864.35 | 7414.00 | 2/20 |
| Exponential C | 7072.00 | 6421.00 | 0/20 |
| Hard cutoff B0 | 7183.20 | 7017.50 | 0/20 |
| Hard cutoff C | 5982.45 | 6764.00 | 0/20 |

The reused exponential mean C−B0 difference was -792.35 steps with its Stage 3C interval [-2077.5625, 593.3150]. The descriptive hard-cutoff mean C−B0 difference was -1200.75 steps with interval [-2000.0800, -405.8813].

### All 20 seed-level interactions

| Seed | Exp B0 | Exp C | Cut B0 | Cut C | d_exp | d_cut | Interaction |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026092101 | 11337 | 9155 | 10777 | 7449 | -2182 | -3328 | -1146 |
| 2026092102 | 6992 | 6619 | 6992 | 6992 | -373 | +0 | +373 |
| 2026092103 | 6893 | 5621 | 7037 | 8551 | -1272 | +1514 | +2786 |
| 2026092104 | 4207 | 6160 | 4207 | 7049 | +1953 | +2842 | +889 |
| 2026092105 | 11231 | 8083 | 6998 | 6568 | -3148 | -430 | +2718 |
| 2026092106 | 12000 | 11243 | 3969 | 2239 | -757 | -1730 | -973 |
| 2026092107 | 6209 | 6209 | 6209 | 4398 | +0 | -1811 | -1811 |
| 2026092108 | 10407 | 6135 | 6303 | 1226 | -4272 | -5077 | -805 |
| 2026092109 | 7557 | 4851 | 7721 | 6767 | -2706 | -954 | +1752 |
| 2026092110 | 7271 | 6009 | 7919 | 7271 | -1262 | -648 | +614 |
| 2026092111 | 6235 | 6339 | 2961 | 1329 | +104 | -1632 | -1736 |
| 2026092112 | 10149 | 7151 | 7151 | 6469 | -2998 | -682 | +2316 |
| 2026092113 | 11135 | 5698 | 6587 | 7068 | -5437 | +481 | +5918 |
| 2026092114 | 9499 | 9499 | 9499 | 9499 | +0 | +0 | +0 |
| 2026092115 | 1253 | 6081 | 10159 | 6081 | +4828 | -4078 | -8906 |
| 2026092116 | 9400 | 9725 | 7847 | 6761 | +325 | -1086 | -1411 |
| 2026092117 | 6317 | 2947 | 8459 | 7555 | -3370 | -904 | +2466 |
| 2026092118 | 4866 | 10489 | 4435 | 3710 | +5623 | -725 | -6348 |
| 2026092119 | 2329 | 6503 | 6575 | 4847 | +4174 | -1728 | -5902 |
| 2026092120 | 12000 | 6923 | 11859 | 7820 | -5077 | -4039 | +1038 |

## Descriptive secondary endpoints

These aggregates are post hoc descriptive summaries with no additional significance tests. They cannot replace or revise the frozen interaction classification.

**Exponential B0:** discovery observed 20/20, mean discovery after relocation 1746.55, mean B deliveries 2.7, non-delivery fraction 0.1, pre-A total 53, mean old-food dwell 3470.65, and mean obsolete-trail occupancy 4647.1.

**Exponential C:** discovery observed 20/20, mean discovery after relocation 845.1, mean B deliveries 3.05, non-delivery fraction 0.0, pre-A total 62, mean old-food dwell 3639.9, and mean obsolete-trail occupancy 4398.6.

**Hard cutoff B0:** discovery observed 20/20, mean discovery after relocation 1140.1, mean B deliveries 3.65, non-delivery fraction 0.0, pre-A total 90, mean old-food dwell 3916.95, and mean obsolete-trail occupancy 6007.25.

**Hard cutoff C:** discovery observed 20/20, mean discovery after relocation 968.05, mean B deliveries 3.65, non-delivery fraction 0.0, pre-A total 67, mean old-food dwell 3705.05, and mean obsolete-trail occupancy 4609.5.

## Interpretation limits

The experiment isolates one matched-lifetime contrast in one fixed scalar-only arena. Matching 2,000 steps does not match the full concentration curve, signal_on lifetime, cumulative exposure, or repeated deposition. The model is not an animal experiment. It uses zero diffusion, one half-life, one cutoff, one recovery duration, fixed geometry, a capped endpoint, and 20 reused seeds. The result cannot establish that hard cutoff is more biologically realistic, that either decay law is generally superior, or that the mechanism is SOTA.

No seed was removed, added, replaced, or rerun based on outcomes. No parameter scan, LLM, random search, TPE, new recovery strategy, cell direction, PCA, diffusion, or food-coordinate navigation was used.

# H1b Step 1: seeds per condition (from stored H1a runs; no simulation)

Method: `scripts/h1b_power.py`; 1000 simulated experiments per n, 1000 bootstrap resamples each; 20% shorter tau for recovered hetero runs, censored runs unchanged.

| Data | Pairs | Censored share | Paired diff median [IQR] | n=20 | n=30 | n=40 | n=50 | n=60 | n=70 | n=80 | n=90 | n=100 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D = 0.01 (used) | 40 | 0.25 | 0 [-4,802, 1,174] | 0.12 | 0.15 | 0.22 | 0.29 | 0.29 | 0.32 | 0.38 | 0.42 | 0.46 |
| D = 0.02 (sensitivity) | 40 | 0.26 | 0 [-4,280, 9,735] | 0.08 | 0.08 | 0.13 | 0.17 | 0.13 | 0.16 | 0.20 | 0.21 | 0.23 |

False detection rate with no effect: h1a: n=20 0.006, n=60 0.006, n=100 0.012; robust: n=20 0.014, n=60 0.019, n=100 0.015

**Chosen n = 100** (smallest n with detection rate >= 0.8 on D = 0.01 data; else 100 (cap)).

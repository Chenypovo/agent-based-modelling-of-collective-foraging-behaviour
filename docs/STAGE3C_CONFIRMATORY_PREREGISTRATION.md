# Stage 3C-P: finite trail-recovery confirmatory study preregistration

Status: frozen before any Stage 3C runner implementation or confirmatory
simulation. The preregistration starts from branch
`codex/stage3b-recovery-search-pilot` at commit
`ddd9dd732cdcb7177177549d39b585c8b839fe03`, whose parent is
`658e39439a1e94f7ff185d2cefc92bdeba5f19a8`. Stage 3C-P adds documentation
only. It does not produce confirmatory evidence or a scientific conclusion.

## Scientific question

> In a direction-free scalar pheromone field, does a finite trail-recovery
> search, compared with immediate random search after signal loss, shorten
> food-delivery recovery after food relocation, and does it increase
> persistence on obsolete trails?

The study is a narrow controlled comparison of a frozen local recovery rule. It
does not test a SOTA or novel navigation framework, human-like intelligence, or
whether a recovery mechanism has already been proved effective.

## Prior evidence and limitations

Stage 3B established an **Engineering PASS** and a **Pilot viability PASS** for
the frozen B0/C implementation. Across its five exploratory paired seeds, C
reacquired a locally detectable pheromone signal in 73.89% of completed
recovery episodes. Food B was discovered in 5/5 B0 arms and 4/5 C arms, while a
food B delivery occurred in 2/5 B0 arms and 1/5 C arms. The direction was mixed,
and aggregate transport did not favour C.

Those five seeds were previously observed, the sample was small, and the
post-relocation window was only 6,000 steps. They are excluded from all Stage 3C
confirmatory statistics. Stage 3B supports only the claim that the 24-step
mechanism can run and can often reacquire some local scalar signal. It does not
show that C improves adaptation, delivery efficiency, correct-route recovery,
or complete path navigation.

Stage 3C changes the observation horizon because Stage 3B had substantial
right-censoring of food B delivery. This decision is frozen before any Stage 3C
seed is run or inspected. It is not a response to Stage 3C outcomes. Ant
behaviour, sensing, deposition, decay, and recovery rules remain unchanged.

## Confirmatory hypotheses

The primary directional hypothesis is that C reduces the paired capped time to
the first completed food B delivery relative to B0. The operational success
criterion is the complete **Mechanism PASS** rule below; a negative mean paired
difference alone is insufficient.

The obsolete-trail hypothesis is that C may increase post-relocation occupation
near old food A or the obsolete nest-to-A trail, and may increase persistence of
scalar pheromone in that frozen region. This is a secondary explanatory
hypothesis. It has no independent PASS threshold and cannot override the
primary result.

## Frozen conditions

Only two conditions are permitted:

- **B0:** after the frozen signal-loss rule fires, the ant immediately uses the
  existing FCRW/random-search movement.
- **C:** after the same signal-loss rule fires, the ant uses the already frozen
  finite recovery search for at most 24 movement steps, then returns to the
  same FCRW if it has not reacquired a signal or contacted food.

C's recovery rule is exactly the Stage 3B rule. The later implementation must
produce a machine-readable single-change audit showing that the recovery branch
is the only behavioural difference between B0 and C.

The shared environment and behavioural parameters are frozen as follows:

| Item | Frozen value |
|---|---:|
| Population | `N=100` |
| Square domain | `L=300` |
| Nest | `(150,150)` |
| Food A | `(240,150)` |
| Food B | `(150,240)` |
| Step size | `0.6` |
| Cell size | `1` |
| Food/contact radius | `0.75` |
| Pheromone deposit | `q=1` |
| Pheromone representation | scalar concentration only |
| Diffusion | `0` |
| Decay | exponential only |
| Exponential half-life | `1000` steps |
| Signal thresholds | `signal_on=0.5`, `signal_off=0.25` |
| Signal-loss duration | `2` consecutive low-signal samples |
| Bilateral sensor geometry | distance `1`, angle `+/-pi/4` |
| Maximum turn | `pi/3` |
| Follower noise amplitude | `0.05` |
| FCRW persistence | `gamma=0.2` |
| C recovery limit | `24` movement steps |

All sensing geometry, thresholds, noise, precomputed random schedules, FCRW,
deposition, food detection, delivery, cargo, role transitions, boundary rules,
event order, and population rules remain the frozen Stage 3B versions. No ant
may use a food coordinate, nest coordinate, cell direction, global gradient,
global field scan, source identity, future information, or offline metric for
navigation. Environment contact checks may use coordinates but may not expose
them to movement logic.

`hard_cutoff_cell_timer` is outside Stage 3C and is reserved for Stage 3D. It
must not be enabled, compared, or added to either arm.

## Seeds and pairing

The confirmatory sample is exactly these 20 new seeds:

`2026092101`, `2026092102`, `2026092103`, `2026092104`, `2026092105`,
`2026092106`, `2026092107`, `2026092108`, `2026092109`, `2026092110`,
`2026092111`, `2026092112`, `2026092113`, `2026092114`, `2026092115`,
`2026092116`, `2026092117`, `2026092118`, `2026092119`, `2026092120`.

Every seed supplies one B0/C pair. Within a pair, both arms must share the same
initial ant state, initial random state, treatment-independent random inputs and
turn schedules, food-relocation time, environment, and measurement
configuration. The recovery-side schedule must also be generated identically;
B0 constructs it for identity checking but never reads it for movement. Pairing
identity must be checked before outcome analysis.

The Stage 2C seeds, Stage 3A functional seeds, and Stage 3B exploratory seeds
must not enter the confirmatory sample or bootstrap. No seed may be replaced,
added, dropped, or rerun to select a more favourable outcome. A valid
non-delivery is retained and assigned the prespecified capped value; it is not
an engineering failure.

## Timeline

Food A is active for `t=0-5999`. At `t=6000`, food A is removed and food B
becomes active. Food B is then observed for `t=6000-17999`, giving a 12,000-step
post-relocation observation window and `18,000` total simulation steps.

Relocation changes only which food location is active. Existing pheromone,
agent position, heading, role, cargo, timer, path history, and random schedules
remain untouched. Cargo acquired from A remains deliverable as A and never
counts as food B recovery.

The 12,000-step window was chosen before observing any confirmatory seed because
the 6,000-step Stage 3B window produced many arms without a food B delivery. The
longer horizon is an observation-design revision, not behavioural tuning.

## Primary endpoint

The primary endpoint is the number of steps from relocation at `t=6000` to the
first completed food B delivery. If the first food B delivery occurs at step
`t_B`, its recovery time is `t_B - 6000`. If no food B delivery is completed by
the end of `t=17999`, the arm receives the valid capped value `12,000`.

For each seed pair:

`delta_time = capped_time_C - capped_time_B0`

Therefore, `delta_time < 0` favours C, `delta_time = 0` records no observed
paired difference, and `delta_time > 0` favours B0. Capping is part of the
endpoint and must not be replaced after execution by excluding non-deliveries,
extending selected runs, or using a discovered-event time.

## Secondary endpoints

Secondary and explanatory endpoints are reported descriptively and may not
replace the primary endpoint:

- time from relocation to first food B discovery, with missingness reported;
- cumulative food B deliveries and the non-delivery fraction in each arm;
- post-relocation ant-steps within 10 distance units of obsolete food A;
- post-relocation ant-steps in the frozen obsolete-trail region, defined as cell
  centres within 2 distance units of the nest-to-A line segment;
- obsolete-trail scalar persistence, recorded every 100 steps as scalar mass and
  counts of cells at or above `signal_off` and `signal_on` in that same region;
- C recovery episode count, reacquisition rate, timeout rate, and food-contact
  endings, with B0 recovery count fixed at zero by definition;
- food B discovery and delivery by the same ant within the frozen 100-step
  post-recovery-episode window;
- food A deliveries before relocation and delivery rate per 1,000 pre-relocation
  steps.

Offline food/trail regions are measurement masks only and must never enter ant
movement. Secondary endpoints will not receive separate success labels or be
searched for the most favourable comparison. Their role is to explain the
primary result, including a possible speed/persistence trade-off.

## Statistical analysis

Analysis begins only after all 40 runs have either passed validation or the
study has been classified INCONCLUSIVE. For each arm, report the mean and median
primary capped time and the number of valid non-deliveries. Report the 20
individual paired differences and their arithmetic mean.

The primary uncertainty analysis is a paired percentile bootstrap with exactly
`10,000` replicates and bootstrap seed `2026092199`. Each replicate samples 20
seed-pair indices with replacement and preserves the B0/C observations within
each selected pair. The replicate statistic is the mean of the resampled
`delta_time` values. The 95% confidence interval is the 2.5th and 97.5th
percentiles of those 10,000 replicate means. Arms must never be resampled
independently.

Also report the relative reduction in mean capped recovery time:

`relative_reduction = (mean_B0 - mean_C) / mean_B0`

The pre-relocation safeguard is computed from total food A deliveries across
all 20 arms in each condition:

`pre_A_ratio = total_pre_A_deliveries_C / total_pre_A_deliveries_B0`

No alternative confidence interval, one-sided interval, uncapped survival
analysis, transformed endpoint, seed subgroup, outlier deletion, or secondary
endpoint may replace these frozen primary calculations. Any additional analysis
must be clearly labelled post hoc and cannot change the formal mechanism
decision.

## PASS / FAIL / INCONCLUSIVE rules

**Mechanism PASS** requires all four conditions below at the same time:

1. `mean_C <= 0.80 * mean_B0`, equivalent to at least a 20% reduction in mean
   capped recovery time;
2. the upper endpoint of the paired-bootstrap 95% confidence interval for mean
   `delta_time` is strictly below `0`;
3. `pre_A_ratio >= 0.80`;
4. all 40 runs are valid and complete, with passing configuration identity,
   pair identity, single-change audit, population conservation, boundary,
   finite-number, output-integrity, resource, and protected-file checks.

If all 40 runs and the frozen analysis are valid but any one of these four
conditions is not met, the formal decision is **Mechanism FAIL**. Describing the
direction as mixed does not replace PASS or FAIL.

The decision is **INCONCLUSIVE** if the valid evidence set is incomplete or the
frozen analysis cannot be computed because of an implementation error, identity
mismatch, corrupt or missing output, failed integrity check, triggered resource
limit, undefined primary ratio, or other prespecified engineering invalidity.
A scientifically unfavourable but valid non-delivery is capped at 12,000 and
contributes to PASS/FAIL; it does not make the study INCONCLUSIVE.

Engineering PASS, the Stage 3B exploratory observations, Stage 3C confirmatory
evidence, and any later final scientific conclusion are four distinct evidence
levels. Passing tests or audits establishes engineering validity only.

## Engineering and resource gates

Before any confirmatory run, the future Stage 3C-E implementation must pass
focused and full regression tests without changing Stage 3A/3B results. It must
produce audits for scalar-only navigation, food-coordinate isolation,
treatment-independent random-schedule identity, B0 replay, configuration
identity, pair identity, and the single behavioural change. It must record the
source commit and hashes before the first run.

Each run has frozen limits of 600 seconds wall time, 600 seconds process CPU,
2 GiB peak resident memory, and 512 MB temporary output. Any individual retained
file above 50 MB stops execution. The complete 40-run study is limited to 8 CPU
hours and 8 GB retained output. Monitoring must not alter simulation randomness
or event order. Crossing any limit pauses execution and yields INCONCLUSIVE
until a documented engineering review; it never authorises a smaller selected
sample.

Every valid run must finish 18,000 steps with exactly 100 ants, finite scalar and
agent values, no boundary violation, complete event/summary output, the intended
seed and arm identity, and hashes matching the frozen implementation. The five
pre-existing untracked trees `.tmp_progress_report/`, `from_prof/`, `output/`,
`reports/`, and `results/stage2c_multiseed_confirmation/` remain protected from
modification, movement, staging, or deletion.

## Future execution order and exact stop conditions

Stage 3C-P stops after this document is committed and reviewed. It must not
implement the runner, start Stage 3C-E, or run any seed.

If Stage 3C-E is separately authorised, its order is frozen:

1. implement the runner, validation, tests, and audit artifacts without running
   a confirmatory seed;
2. run B0 and then C for seed `2026092101` as the first paired engineering and
   resource check;
3. inspect only completion, files, timing, memory, storage, pair identity,
   integrity, and audits; do not inspect the scientific outcome to tune rules;
4. if those checks pass, retain this pair as part of the 20-pair sample and stop
   for separate master approval;
5. only after that approval, run the remaining 19 pairs in ascending seed order,
   B0 followed by C within each pair;
6. after all 40 runs validate, execute the frozen analysis once and issue the
   formal PASS or FAIL decision.

An engineering error, corrupt artifact, identity mismatch, or resource-limit
event stops further runs immediately. Existing artifacts are preserved. Resume
or any technically necessary rerun requires a documented engineering cause and
separate approval; it may not be motivated by an observed scientific result.
An unfavourable result, non-delivery, mixed direction, or failure to approach a
PASS threshold is never a stopping or rerun condition. Behavioural parameters
cannot be changed after the first pair.

## Excluded scope

Stage 3C excludes continuation of Stage 2C PCA; modification or rerunning of the
Stage 3B pilot; hard-cutoff decay-law ablation; half-life scanning; diffusion;
cell direction; LLM, random-search, or TPE optimisation; GPU or AutoDL use; and
any final paper-level conclusion. It also excludes alternative recovery
durations, seed expansion, interim efficacy analysis, and parameter selection
from confirmatory outcomes.

## Required future artifacts

A valid future execution must preserve at least the following reviewable
artifacts:

- frozen source/configuration manifest with commit and SHA-256 identities;
- runner and test receipts, including a full regression-test result;
- scalar/coordinate isolation, common-random-number, pair-identity, B0-replay,
  and single-change audit records;
- immutable per-run configuration, status, resource, event, and summary files
  for all 40 runs;
- population, boundary, finite-number, completeness, and protected-file checks;
- a 20-row paired primary-endpoint table retaining every frozen seed;
- raw or exactly reproducible 10,000-replicate paired-bootstrap output and its
  percentile interval using seed `2026092199`;
- secondary-endpoint tables clearly separated from the primary decision;
- a storage/resource summary, complete delivery manifest, and final report that
  states Engineering status and Mechanism PASS/FAIL/INCONCLUSIVE separately.

No future artifact may silently overwrite Stage 3B output or convert an
engineering test, exploratory observation, or secondary result into
confirmatory evidence.

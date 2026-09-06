# Stage 2C preregistration: paired multi-seed confirmation

Date: 6 September 2026. Status: documentation only; no Stage 2C runner has been implemented and no Stage 2C simulation or resource pilot has been run as part of this preregistration.

> Stage 2C paired confirmation of a frozen provisional implementation — not an exact reproduction of Fig. 4.

## 1. Scope, authority and provenance

The research question is:

> In the completely frozen provisional Stage 2A colony model, does `local_weighted_pca_tangent`, compared with `stored_cell_direction`, consistently improve follower alignment, colony order and transport performance across multiple new random seeds?

This question concerns these two implemented rules, these 20 seeds and this frozen model. It does not test all local geometry methods, establish an exact reproduction of Fig. 4, prove the paper correct or incorrect, or establish supervisor approval.

This commit authorises and records the protocol only. Runner implementation, a resource pilot and confirmatory simulations require a subsequent explicit instruction. The protocol does not authorise Stage 3, LLM work, parameter searches or changes to model behaviour.

| Reference | Frozen identity or purpose |
|---|---|
| Intake branch | `codex/stage2b-local-trail-geometry` |
| Implementation and input-artifact commit | `3226100a5fa52777acedbf8cfa25c71559ab525d` |
| Preregistration branch | `codex/stage2c-multiseed-confirmation` |
| Original Stage 2A diagnostic baseline; unchanged `main` | `02a953af132a44aabcf8be92a873de7694d4a5fb` |
| Exploratory seed | `20260824`; excluded from every confirmatory statistic |

The implementation commit identifies both existing follower rules and the frozen input artifacts. A later runner commit must separately record its own identity and this preregistration commit, and prove that the model behaviour remains identical to the implementation commit. New baseline runs must use each new seed; the single old Stage 2A CSV is not the control for the 20 new PCA runs.

Required source material read before drafting:

- `README.md`
- `docs/STAGE2_SPEC.md`
- `docs/STAGE2B_SPEC.md`
- `results/stage2_provisional/REPORT.md`
- `results/stage2_diagnostic/REPORT.md`
- `results/stage2b_local_geometry/REPORT.md`
- `results/stage2b_local_geometry/baseline_comparison.json`
- `results/stage2b_local_geometry/runtime.json`

No filesystem `AGENTS.md` was present in the project or its ancestor directories at intake. The user's `AGENTS.md` instructions supplied in the task conversation were read and apply; no replacement file is created. The frozen configuration JSON files and existing metric definitions in `scripts/run_stage2b.py`, `src/colony/metrics.py` and `src/colony/diagnostics.py` were also inspected read-only to resolve measurement definitions.

The existing Stage 2B record is an engineering **PASS**, mechanism-improvement **FAIL**, and Fig. 4 candidate **FAIL** for seed `20260824`. Its late-window mean psi decreased from `0.6364427983712712` to `0.5059466682881061`; deliveries decreased from `363` to `40`. Local continuity improved from approximately `23.224` to `10.681` degrees, while follower hit-step axis error changed from approximately `43.011` to `43.148` degrees. This motivates confirmation of the narrow negative result; it supplies no observations to the new confirmatory sample.

## 2. Evidence and assumption labels

These labels distinguish source status from the decision to hold a setting fixed. Freezing an assumption does not make it paper-explicit or supervisor-approved.

| Label | Meaning and application |
|---|---|
| **paper-explicit** | Content recorded as explicit in `docs/STAGE2_SPEC.md`: N=100, L=300, speed and sensing range 0.6, gamma 0.1, Theta 50 degrees, reflective boundaries, the nest-food axis pi/4, the three roles and stated transitions, and the Fig. 4 horizon. This document inherits that local source classification; it does not newly verify the original paper. |
| **frozen implementation choice** | An operational choice fixed for this study: the exact existing code, seed list, two rules, pairing, measurement definitions, aggregation, bootstrap algorithm, numerical gates, missing-data handling and resource protocol. These are not claims about the authors' implementation. |
| **provisional assumption** | The existing ZW interpretation, nest/food coordinates and radii, numerical initialisation, detection, discrete pheromone representation, direction inference, memory endpoints, interpolation, boundary numerics and event timing. They remain provisional while frozen. |
| **awaiting supervisor confirmation** | The questions in the Stage 2A/2B specifications concerning the authors' actual follower rule, pheromone representation, ties, memory, coordinates, initialisation, sampling and update timing. No approval or reply is inferred. |
| **unresolved** | Information not established: the unpublished author implementation, correspondence between this model and the exact Fig. 4 implementation, actual Stage 2C outcomes, current-machine runtime/storage, and the future runner's executable interface. A missing or invalid future measurement must also be recorded explicitly, not filled with an advantageous value. |

The PCA hypothesis itself remains a **provisional assumption**. Its use of local concentration-weighted cell geometry, heading-based axis sign, and existing degeneracy fallback is a **frozen implementation choice**, not a paper-explicit rule. New supervisor information must be recorded separately; it must not silently change this confirmatory protocol after results are observed.

## 3. Fixed design and complete seed list

There are exactly 20 confirmatory seed pairs and 40 rule-runs:

| Pair | Seed | Pair | Seed |
|---:|---:|---:|---:|
| 1 | 20260901 | 11 | 20260911 |
| 2 | 20260902 | 12 | 20260912 |
| 3 | 20260903 | 13 | 20260913 |
| 4 | 20260904 | 14 | 20260914 |
| 5 | 20260905 | 15 | 20260915 |
| 6 | 20260906 | 16 | 20260916 |
| 7 | 20260907 | 17 | 20260917 |
| 8 | 20260908 | 18 | 20260918 |
| 9 | 20260909 | 19 | 20260919 |
| 10 | 20260910 | 20 | 20260920 |

The inclusive interval is `20260901` through `20260920`. The exploratory seed `20260824` must not enter the confirmatory sample, bootstrap, gate calculations, improvement counts or confirmatory figures. Any contextual display of its existing results must be labelled separately as exploratory.

For every new seed:

- Control: `stored_cell_direction`.
- Experimental rule: `local_weighted_pca_tangent`.
- Both runs use the same seed, initial positions/headings, pre-generated random turn schedules, number of ants, horizon and all other model parameters.
- Within a pair, the only permitted behavioural configuration difference is `follower_direction_rule`. Across pairs, only the preregistered seed changes. Output paths and checkpoint identifiers are administrative metadata, never inputs to movement or random-number generation.
- The simulation random-number generator and random draw ordering remain frozen. The analysis bootstrap uses an independent generator.
- Run pairs sequentially on Mac CPU in ascending seed order, baseline then PCA. This order is fixed for reproducibility, not chosen by outcomes.

No failed seed may be replaced. No seed may be added, dropped or rerun because its scientific result is unfavourable. No tuning, new follower rule, pheromone change, memory change, role-transition change, boundary change or update-order change is allowed. GPU, AutoDL, Optuna, LLM-controlled ants and all parameter searches are excluded.

## 4. Frozen model configuration

The authoritative configuration is the full Stage 2A configuration at the implementation commit, together with the existing explicit `follower_direction_rule` field available at that commit. The later config manifest must enumerate every field and its source; the table below is not permission to change an unlisted default.

| Field or behaviour | Fixed setting |
|---|---|
| Population; arena; horizon | `N=100`, `L=300`, `steps=10000` |
| Movement | Existing provisional `zw`; `gamma=0.1`; `theta_deg=50.0`; `step_size=0.6`; `time_step=1.0` |
| Nest; food | Centres `(90.0, 90.0)` and `(240.0, 240.0)`; radii `3.0` each; inexhaustible food |
| Initialisation | All foragers at the nest centre; existing seeded IID uniform headings on `[0, 2*pi)` |
| Detection | Food: site radius plus sensing range; nest: site radius |
| Memory | `memory_stride=3`; append the final vertex if not retained |
| Transporter | Existing reversed, interpolated coarse path; becomes follower after nest delivery |
| Pheromone | Cell size `0.6`; sensing range `0.6`; deposit amount `1.0`; diffusion `0.0`; decay `0.0` |
| Baseline ties; no signal | Existing `food_projection_then_lexicographic`; `continue_heading` |
| PCA rule | Exact existing local weighted PCA, current-heading sign selection and degeneracy fallbacks; no stored direction, global nest/food coordinates or new randomness in inference |
| Boundary | Existing `reflect_overshoot_and_velocity_component` |
| Event order | Existing `move_deposit_then_transition_food_before_pheromone`, including existing ant/role processing order |
| Snapshots; state records | `1000, 4000, 10000`; `agent_state_interval=100` |
| Analysis late window | Every integer time `t=9000` through `t=10000`, inclusive: exactly 1001 end-of-step samples |

The same existing follower-rule entry point remains in use for follower motion, recruitment and conversion after delivery, as documented in Stage 2B. Instrumentation must remain observational and consume no simulation random draws. The nest-food axis may be used by evaluation metrics and the frozen baseline/event rules; it must not be added to the PCA decision.

The later audit must compare canonical behavioural configurations field by field within each pair, verify matching initial-state/turn-schedule hashes, and verify frozen source hashes. Output routing may place new results under a dedicated `results/stage2c_multiseed_confirmation/` directory without modifying any prior results or report files. This directory is not created by the present documentation task.

## 5. Endpoints and measurement windows

### 5.1 Primary endpoint

The primary endpoint is **late-window mean nematic order psi**, using the existing `nematic_order_psi` implementation, not a replacement definition of nematic order.

For seed `s` and rule `r`, let `psi_bar[s,r]` be the arithmetic mean of global psi over all 1001 end-of-step samples at `t=9000..10000`. All 100 ants contribute to each global sample. Then:

`delta_psi[s] = psi_bar[s,PCA] - psi_bar[s,baseline]`.

The primary study estimate is the arithmetic mean of the 20 paired `delta_psi` values. Each seed has equal weight. Ants and time steps are not independent statistical replicates. A final-time psi value must not substitute for the late-window mean.

For clarity, the frozen implementation folds headings into `[-pi/2, pi/2)`, takes their arithmetic mean for phi, and computes psi as the magnitude of the mean folded unit vector. It must not be replaced by a different double-angle statistic during this study.

### 5.2 Secondary endpoints

The following definitions are fixed analysis choices and preserve the Stage 2B measurement meanings. Metrics explicitly labelled late-window use `9000..10000`; the other time-aggregated metrics below use the entire run `1..10000`.

| Endpoint | Per-seed, per-rule definition |
|---|---|
| Late-window mean phi | Arithmetic mean of global `orientation_order_phi` over the same 1001 samples, in radians. Also report its absolute distance from pi/4; do not substitute a circular mean. |
| Follower late-window psi | At each late-window end-of-step state compute existing psi for followers, then average the time samples equally. Record follower counts and sample sufficiency; see the missingness rule below. |
| Follower hit-step mean axis error | Mean realised movement-heading axial error relative to the fixed nest-food axis on all follower sensing-hit steps during the full run, in degrees. Opposite headings along the same axis have zero error. Use movement after reflection, not directed error towards food. |
| Follower local continuity axis change | Mean axial change between selected directions for the same ant on immediately consecutive time steps where both steps are sensing hits and both directions are finite; full run, degrees. Do not bridge a miss or a time gap. |
| Sensing miss rate | Number of follower sensing misses divided by total follower sensing steps over the full run. |
| Cumulative deliveries | Successful food deliveries at `t=10000`; also retain the full cumulative trajectory. |
| Completed transporter path efficiency | For each completed delivery leg, endpoint displacement divided by actual return path length, using the existing definition. Report within-run mean and median over completed legs. Report incomplete-leg counts separately. |
| Active pheromone area fraction | Final number of positive-intensity cells divided by all arena grid cells. |
| 90% main-channel width | Final `all_active_history` measure: twice the intensity-weighted 90th percentile of cell-centre perpendicular distance from the nest-food axis, using the existing weighted-quantile definition. Do not switch to a favourable top-concentration mask. This is the retained historical-field width, not proof of a connected active transport corridor. |
| Final role counts | Forager, transporter and follower counts at `t=10000`, with their sum and existing transition totals. |
| First food discovery | First `food_detected` event time. |
| First successful delivery | First `food_deposited_at_nest` event time. |
| First pheromone recruitment | First `pheromone_sensed` forager-to-follower event time. |

Within each run, hit-step errors and continuity are step-weighted means; efficiency is leg-weighted. Across runs, first reduce to one value per seed/rule, then weight seeds equally. In particular, the PCA cross-seed follower-error gate is the mean of the 20 per-seed hit-step means, not a pooled mean over all ants or hits.

### 5.3 Zero denominators, sparse roles and missing observations

These decisions are fixed before any new observations:

- For baseline deliveries greater than zero, `delivery_ratio[s] = PCA_deliveries[s] / baseline_deliveries[s]`. A PCA count of zero gives ratio zero.
- If baseline deliveries are zero, the ratio is undefined, including `0/0`. Record a null value with reason `zero_baseline_deliveries`, both raw counts and whether PCA delivered anything. Do not use an epsilon, add one, assign infinity, remove the seed or replace its baseline. Gate 4 requires 20 defined finite ratios; otherwise it is not satisfied. A median over fewer valid ratios may be shown only as explicitly incomplete descriptive information.
- No follower sensing steps, no hits, no consecutive valid hit pairs, no completed delivery legs or no active pheromone field gives an unavailable derived metric with a reason and its denominator. It does not give a fabricated zero error, perfect efficiency or zero-width corridor.
- Preserve role counts below five as `insufficient sample`, consistent with the diagnostic warning. Show available raw role statistics with that warning. For the confirmatory follower late-window secondary summary, require at least five followers at all 1001 samples; otherwise mark it insufficient rather than select a favourable subset of times. This stricter summary eligibility is an analysis choice, not a model change.
- Events not observed by `t=10000` are right-censored: record null event time, `observed=false`, and censoring horizon 10000. Do not treat them as events at 10000 or 10001. Event-time paired differences and observed-time summaries use only explicitly identified pairs with both events observed, with denominators and all censored rows retained; these are descriptive, not a revised primary sample.
- Structural absence is encoded by null plus an availability/reason field, never by numerical NaN in JSON. NaN/infinity in physical state or otherwise defined measurements is an engineering failure. Absence of a role is not itself a population-conservation error.
- The primary analysis and all gates require all 20 valid pairs and their required measurements. No complete-case primary bootstrap, imputation, subset gate or replacement seed is permitted. An unassessable required gate is recorded as not satisfied with an explicit unresolved reason; it cannot yield mechanism PASS.

## 6. Statistical analysis fixed in advance

For every scalar endpoint report per-seed baseline, PCA and paired difference `PCA - baseline`. Report across-seed arithmetic mean, median and sample standard deviation (`ddof=1`) for both rules and the paired differences, with the number of available observations. Report the per-seed delivery ratios and their cross-seed median separately; neither a ratio of pooled deliveries nor a ratio of cross-seed means may replace it.

For the primary endpoint report counts of improved (`delta_psi > 0`), unchanged (`delta_psi = 0`) and worsened (`delta_psi < 0`) seeds, summing to 20 when complete. Use unrounded stored values and exact zero for this classification. Apply the same signed-difference counts to all numeric secondary endpoints with explicit direction labels; missing values have a fourth unavailable count. For counts and active area, an increase is descriptive and is not automatically improvement. Higher psi, deliveries and efficiency are favourable; lower axis error, continuity change, miss rate, absolute phi distance and channel width are favourable diagnostic directions. Earlier observed events are descriptive and their censoring must remain visible.

### 6.1 Paired bootstrap

The inferential unit is the complete seed pair. The required primary 95% confidence interval is for the **mean paired delta_psi**:

1. Order the 20 seed pairs numerically, `20260901..20260920`.
2. Use an independent NumPy `Generator` with explicitly selected `PCG64` and bootstrap seed **20260999**. Record NumPy's version and the generator identity in `summary.json`.
3. Generate **10000** bootstrap samples. Each sample draws 20 seed-pair indices uniformly with replacement from indices 0 through 19. Use a row-major `(10000, 20)` array of `int64` indices from the generator's `integers` operation with exclusive upper bound 20. The analysis generator is never used by the simulation.
4. For every bootstrap sample, average its 20 paired differences. The baseline and PCA observations travel together whenever their seed is resampled. Never resample the two rules separately, and never bootstrap individual ants or time points as if they were independent seeds.
5. Use a **percentile interval, 2.5% to 97.5%**, with linear interpolation: for sorted bootstrap means and probability `p`, use index `h=(10000-1)*p` and interpolate between its floor and ceiling. This is the NumPy `method="linear"` quantile definition. No BCa, basic, normal or one-sided substitution is allowed.
6. Compare the unrounded lower endpoint to zero. Gate 2 requires it to be strictly greater than zero; a lower bound equal to zero fails that condition.

The same fixed index array may also provide descriptive intervals for mean paired secondary differences only when all 20 pairs have defined values for that endpoint. Otherwise report the missingness and descriptive available-pair summaries without inventing a smaller-sample confirmatory interval. The four non-bootstrap gates are assessed directly; they are not replaced by secondary confidence intervals.

Show every seed in tables and figures, including failed, incomplete and scientifically unfavourable seeds. Do not select endpoints, seeds, time windows or statistical methods after examining results. No p-value is required; a p-value must never be the sole decision criterion. No multiple-metric search or selection of the most favourable interval is permitted. These intervals describe seed-to-seed variation conditional on the frozen model; they do not resolve uncertainty about the unpublished author implementation.

## 7. Separate engineering, mechanism and scientific decisions

### 7.1 Mechanism-improvement gate: binary PASS or FAIL

**Mechanism improvement = PASS only if all five conditions hold simultaneously:**

1. The mean of all 20 paired `delta_psi` values is **at least +0.10**.
2. The paired-bootstrap 95% interval for that mean has **lower bound greater than 0**.
3. The equal-seed mean of PCA follower hit-step mean axis errors is **at most 35 degrees** across all 20 seeds.
4. All 20 per-seed delivery ratios are defined and their **median is at least 0.80**.
5. All 40 runs complete the prescribed horizon with population conserved at every step, positions within the reflective arena, finite physical state and defined required measurements; paired configurations/initialisation match except for the follower rule; no failed seed was replaced and no unauthorised behavioural change occurred. Existing tests, source/input preservation checks and instrumentation checks must also pass.

If any condition fails or cannot be established, **Mechanism improvement = FAIL**, with each failed or unresolved condition shown separately. Better local continuity, an attractive figure or another isolated metric cannot compensate for a failed primary or transport threshold. The old Stage 2B absolute delivery threshold of 291 is not imported: the new study uses the fixed median of per-seed ratios.

A scientifically poor but numerically valid run remains a valid observation. An invalid or unfinished run stays in the manifest; it prevents a complete confirmatory claim until an allowed engineering recovery is complete. Report incomplete/invalid evidence separately from a fully observed scientific negative result.

### 7.2 Scientific conclusion: PASS, FAIL or MIXED

Always report `mechanism_improvement` separately from `scientific_conclusion`; MIXED never changes a binary mechanism FAIL to PASS.

To make conflicting-direction interpretation reproducible, use this fixed set of directional contrasts: late-window global psi and follower psi, follower hit-step axis error, local continuity change, sensing miss rate, cumulative deliveries, mean completed transporter efficiency, absolute late-window phi distance from pi/4, and main-channel width. Use each endpoint's mean paired contrast over all 20 eligible pairs; lower is favourable for the error/distance/width/miss endpoints and higher is favourable for psi/deliveries/efficiency. A conflict exists when at least one contrast is favourable and at least one is unfavourable; exact zero is neutral. A direction-only conflict is descriptive and does not establish a separate significant effect. Active area, final role proportions and censored event times remain contextual because they have no universal monotonic success target.

| Scientific label | Fixed interpretation |
|---|---|
| **PASS** | All five mechanism conditions pass, required directional evidence is assessable and the fixed contrasts do not conflict. Say only that this particular PCA rule is a candidate for further study in this frozen implementation. Do not claim exact reproduction. |
| **FAIL** | Complete, valid evidence fails one or more mechanism thresholds, with no conflicting directions in the fixed set. Say: this PCA rule was not supported in these 20 preregistered seeds and this frozen implementation. Do not generalise to all local geometry rules or to the paper. |
| **MIXED** | The fixed contrasts contain conflicting directions, or missing/invalid evidence prevents a complete scientific interpretation. Say the result is uncertain or incomplete, identify the specific conflict/reason, and still display any mechanism FAIL. MIXED is not success and does not authorise more seeds or tuning. |

### 7.3 Fig. 4 candidate gate, evaluated independently

For each seed/rule display the three candidate conditions using that run's own late-window means:

- `abs(late_window_mean_phi - pi/4) <= 0.15` radians;
- `late_window_mean_psi >= 0.90`;
- transport and role cycling have not collapsed.

For reproducibility, retain the existing Stage 2B operational meaning of the last condition: positive cumulative deliveries, at least one `follower_to_transporter` transition and at least one `transporter_to_follower` transition by the horizon. This is a minimal cycle check, not proof of sustained efficient transport. Also report late-window delivery increments and transition counts as context without replacing the fixed gate.

The study-level PCA candidate decision uses the equal-seed mean of its 20 late-window phi means, the equal-seed mean of its 20 late-window psi means, and requires the cycle condition and engineering validity for every PCA seed. Its thresholds are the same `0.15 rad` and `0.90`. Display all per-seed results and candidate counts beside this aggregate so that averaging cannot conceal individual failures. This aggregation is a **frozen implementation choice**, not a paper-explicit statistical criterion.

Candidate PASS does not override the mechanism gate or scientific conclusion. Even if PASS, the permitted description is only a **Fig. 4-like candidate in the frozen provisional implementation**, never exact reproduction or supervisor approval. Missing required candidate evidence prevents candidate PASS.

## 8. Resources, pilot, interruption and stopping

Execution is restricted to the existing **Mac CPU**, sequential rule-runs, with no GPU, AutoDL, externally rented compute or external charges. The future runner must support interruption and resumption before any confirmatory execution begins.

The resource pilot is fixed as the full paired run for the first confirmatory seed **20260901**, using N=100, L=300 and all 10000 steps for each rule. It is the first of the 20 pairs, not an extra seed or a reduced scientific design. If it completes validly, retain it in the confirmatory statistics and never rerun it merely because its outcome or runtime is inconvenient. The remaining 19 pairs can proceed only after the resource checks pass and execution has been explicitly authorised.

Pilot acceptance examines engineering validity, elapsed time, peak/retained additional storage, checkpoint cost and output completeness; it must not examine whether scientific effects are favourable as a condition for continuing. A valid negative pilot proceeds under the same resource rules as a positive one. Read-only existing Stage 2B runtime values (approximately 95.031 seconds for baseline replay and 147.111 seconds for the PCA simulation) are historical context only, not a current runtime guarantee. Actual storage remains unresolved until measured.

Before the pilot, obtain an initial projection from existing artifact sizes and historical runtime without rerunning old experiments. After the pilot and every completed rule-run, update a conservative projection for the entire planned 40-run study, including elapsed work, remaining work, analysis, figures, checkpoints and retained failure evidence. Use a 1.5 safety factor on remaining simulation/output time and storage, based on the slowest/largest completed comparable rule-run; separately record allowances for final analysis, figures and peak checkpoint overlap. Record the inputs and calculation, not only a pass flag.

**Pause before starting the next run when projected total wall time exceeds 4 hours (14400 seconds), or projected peak additional storage exceeds 2 GB (2000000000 bytes).** Pause as well if actual accumulated time/storage reaches its limit before completion, or if a defensible projection is unavailable. Count already completed work and pilot costs; do not reset the budget after interruption. Preserve the current checkpoint and report the estimate and reason. Do not automatically increase limits, reduce the seed list, shorten runs, discard retained files, move to AutoDL or incur costs. Continuing past a resource gate needs a later explicit decision.

Checkpoint/progress requirements for the future runner:

- Distinguish planned, running, interrupted, engineering-failed and completed states for every seed and rule. A seed pair is complete only after both full runs and audits pass.
- Checkpoints must preserve time, ant/role state, memories/routes, pheromone state, random-generator state or pre-generated schedules, pending events, metric accumulators and relevant diagnostic history. Resuming must preserve the uninterrupted trajectory and avoid duplicate counts or output rows.
- Bind checkpoints and completed outputs to seed, rule, canonical configuration hash, source/runner identity and artifact hashes. Reject mismatched resume attempts; never silently overwrite an existing completed run.
- Retain the last valid checkpoint, logs and failed-attempt provenance. A genuine engineering error may be repaired and resumed for the **same seed**, with a recorded cause and repair; a same-seed restart is allowed only if a valid checkpoint cannot be used, with prior evidence retained and the reason documented. A repair must not change the frozen behavioural model. Any proposed behavioural correction pauses this protocol for a new decision.
- Never rerun or choose between completed valid outcomes. Low psi, poor alignment, no discovery, no deliveries or another unfavourable scientific result is not an engineering error and is not a rerun reason.
- Stop on population loss, out-of-bounds state, numerical failure, configuration mismatch, source/input mutation or missing/corrupt checkpoint evidence. These failures are recorded, not replaced with another seed.

## 9. Required future outputs and preservation

Later Stage 2C execution must generate at least the following under its dedicated output directory. None is generated in the present task.

| Artifact | Required content |
|---|---|
| `config_manifest.json` | Complete settings for both rules and all seeds; source/preregistration/runner commits, package versions, configuration hashes, initial-state hashes and fieldwise single-rule audit |
| `seed_manifest.json` | All 20 fixed seeds, both rules, exploratory-seed exclusion, pilot inclusion and immutable planned ordering |
| `per_seed_metrics.csv` | Exactly 40 seed/rule identities, including placeholders for incomplete runs; primary and every secondary metric, denominators, statuses, censoring and reasons |
| `paired_comparison.csv` | All 20 seed identities, baseline/PCA metrics, paired differences, delivery ratios, missingness and per-seed engineering/candidate checks |
| `summary.json` | Mean/median/sample SD, improvement/equality/worsening counts, all gate inputs/verdicts, bootstrap specification and interval, scientific conclusion and limitations |
| `runtime.json` | Mac CPU/platform, elapsed time per run, accumulated and projected time/storage, resource pilot evidence, overheads, pauses and confirmation that no external compute was used |
| `checkpoint/progress_manifest.json` | Per-seed/rule progress, checkpoint identifiers/hashes, completion status, attempts, interruption/repair reasons and resource accounting |
| `REPORT.md` | All 20 pairs, endpoint definitions, three separate decision layers, failures/conflicts, evidence limits and links to all artifacts |
| Reproduction command record in `REPORT.md` | Exact working directory, environment/dependency versions, checkout identifiers, full pilot/run/resume/analysis commands and frozen manifest paths; executable only once the later runner exists |

The exact CLI and checkpoint serialisation are currently **unresolved implementation details**. A later implementation must document and validate them before execution; do not present an invented Stage 2C command as runnable now. The reproduction command record must enable reproduction from the stated checkout without reconstructing undocumented options.

At least four comparison figures are required, fixed in content before execution:

1. All 20 paired late-window psi values and per-seed delta_psi, with the across-seed mean, fixed bootstrap interval and +0.10 reference.
2. All 20 paired follower psi and hit-step axis errors, with the 35-degree criterion; include local continuity and sensing miss rate panels.
3. All 20 paired delivery counts, delivery ratios with the 0.80 reference, and completed transporter mean efficiency.
4. All 20 paired late-window phi, historical-field width, active area fraction, final F/T/f counts and first-event/censoring summaries, using clearly separated labelled panels.

All figures must show missing/failed seed slots explicitly and carry the Stage 2C provisional-implementation notice. No best-seed montage may replace the full comparison. Preserve enough per-time-step order/count/delivery data, event evidence, sensing sums/counts, transport summaries and final field summaries to independently recompute the registered statistics. Aggregate sensing online or retain compact sufficient records; do not write unbounded raw follower logs. No individual new raw diagnostic file may exceed the inherited 100 MB limit; all outputs and checkpoint overlap count towards 2 GB.

Before and after later execution, verify hashes for frozen model sources, prior specifications and all artifacts under `results/stage1/`, `results/stage2_provisional/`, `results/stage2_diagnostic/` and `results/stage2b_local_geometry/`. Protect the root proposal/briefing/template, bibliography and **every existing file under `reports/`**, including ignored duplicates, Turnitin and similarity files. Preserve ignored diagnostic data as well. Do not modify, move, delete or stage local report materials. Any preservation failure pauses work and is reported as an engineering failure.

## 10. Present documentation-only acceptance

This task may add only `docs/STAGE2C_PREREGISTRATION.md`. It may run the existing test suite to verify the branch baseline, but must not implement a runner, change model code or configuration, run any Stage 2C simulation/pilot, or generate new experimental outputs.

Acceptance requires `git diff --check`, review of the new document, staging only this path, `git diff --cached --check`, and staged name/status exactly `A docs/STAGE2C_PREREGISTRATION.md`. The local commit message is:

`docs: preregister Stage 2C paired multi-seed study`

After committing, the working tree must be clean, `main` must remain at `02a953af132a44aabcf8be92a873de7694d4a5fb`, and existing files must be unchanged. No push or merge is authorised. Actual Stage 2C measurements and verdicts remain unresolved until separately authorised execution is complete.

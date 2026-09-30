# Stage 3D: matched-lifetime decay-law ablation preregistration

Status: frozen before Stage 3D implementation and before any hard-cutoff formal
simulation. This extension starts from
`b4cfad857acd0beba50b662f92a3180cb074db05` after the complete Stage 3C
confirmatory result was observed. Stage 3C concluded **Mechanism FAIL** because
the frozen C mechanism did not meet all four confirmatory gates. Stage 3D is
therefore a prospective exploratory extension, not an independent confirmatory
study and not evidence of a SOTA method.

## Scientific question

> When the theoretical detectable lifetime of one pheromone deposit is
> matched, does changing the decay law from continuous exponential decay to a
> finite hard cutoff change the effect of the frozen 24-step recovery treatment
> C relative to B0?

The estimand is a difference of within-decay-law treatment differences. The
study does not test whether a hard cutoff is more biologically realistic, and
it does not establish general performance across decay parameters,
environments, or recovery strategies.

## Frozen four-cell design

The 20 Stage 3C seeds are reused without replacement, deletion, or addition:

`2026092101` through `2026092120` inclusive.

Each seed contributes four cells:

1. exponential + B0: read-only reuse of the completed Stage 3C arm;
2. exponential + C: read-only reuse of the completed Stage 3C arm;
3. hard cutoff + B0: one new formal Stage 3D arm;
4. hard cutoff + C: one new formal Stage 3D arm.

Stage 3D adds exactly 40 hard-cutoff arms. It must not rerun, copy, edit, or
replace the exponential arms. Before analysis, the implementation must verify
the Stage 3C execution identity, configuration, completed receipts, file hashes,
and all 40 reused arms.

Within each seed, all four cells use the same initial state, treatment-neutral
random inputs, food relocation, measurement rules, and non-treatment
parameters. Within a decay law, B0 and C differ only in finite recovery search.
Across decay laws, corresponding B0 or C cells differ only in the decay-law
configuration and the state needed to implement that law.

## Frozen simulation configuration

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
| Signal thresholds | `signal_on=0.5`, `signal_off=0.25` |
| Signal-loss duration | `2` consecutive low-signal samples |
| Bilateral sensors | distance `1`, angle `+/-pi/4` |
| Maximum turn | `pi/3` |
| Follower noise amplitude | `0.05` |
| FCRW persistence | `gamma=0.2` |
| C recovery limit | `24` movement steps |
| Total steps | `18,000` |
| Food relocation | `t=6000` |
| Observation end | `t=17999` |
| Post-relocation window | `12,000` steps |

B0 switches immediately to the existing FCRW after the frozen signal-loss
condition. C invokes the existing finite recovery search for at most 24
movement steps and otherwise returns to the same FCRW. No other movement,
sensing, deposition, food contact, cargo, role, boundary, population, event
order, or random-schedule rule may change.

The study prohibits diffusion, PCA, stored cell direction, food-coordinate or
nest-coordinate navigation, global gradients, new recovery strategies,
parameter scans, LLM search, random search, TPE, seed selection, and any change
to B0/C dynamics other than the frozen recovery treatment.

## Matched detectable lifetime

The exponential cells retain the Stage 3C law:

- `mode="exponential"`;
- `half_life_steps=1000`;
- `q=1`;
- `signal_on=0.5`;
- `signal_off=0.25`;
- diffusion `0`.

The new cells use:

- `mode="hard_cutoff_cell_timer"`;
- `cutoff_steps=2000`;
- `q=1`;
- `signal_on=0.5`;
- `signal_off=0.25`;
- diffusion `0`.

The hard-cutoff lifetime is frozen from

```text
2000 = ceil(ln(1 / 0.25) / (ln(2) / 1000)).
```

This calculation matches only the theoretical time for a single deposit of
size 1 under exponential decay to reach `signal_off=0.25`. It does not match
the complete concentration curve, the lifetime above `signal_on`, cumulative
exposure, integrated pheromone mass, or the behaviour produced by repeated
deposits. Those unmatched properties are part of the interpretation limit.

For `hard_cutoff_cell_timer`, a deposit sets the cell concentration to the
existing deposited scalar amount and refreshes that cell's remaining lifetime
to 2,000 steps. The timer, expiry order, and same-step redeposition behaviour
must be fixed in the engineering specification and covered by tests before any
formal arm is run.

## Primary endpoint

For each cell, the endpoint is the number of steps from relocation at `t=6000`
to the first completed food B delivery. If an arm has no food B delivery by the
end of `t=17999`, it receives the capped value `12,000`. A valid non-delivery
must remain in the analysis and is not an engineering failure.

For each seed:

```text
d_exp       = capped_time_C_exponential - capped_time_B0_exponential
d_cut       = capped_time_C_cutoff      - capped_time_B0_cutoff
interaction = d_cut - d_exp
```

`interaction < 0` means that C improves the capped endpoint more, relative to
B0, under hard cutoff than under exponential decay. `interaction > 0` means
the relative C effect is less favourable under hard cutoff. Direction is not
assumed in advance.

## Frozen statistical analysis

Analysis starts only after the 40 new hard-cutoff arms and all 40 reused
exponential arms pass identity, completeness, integrity, configuration, and
resource checks.

The primary statistic is the arithmetic mean of the 20 `interaction` values.
Its uncertainty is estimated with one paired percentile bootstrap:

- exactly `10,000` replicates;
- bootstrap seed `2026092299`;
- resampling unit: the complete seed-level four-cell record;
- 20 seed indices sampled with replacement per replicate;
- statistic: mean interaction;
- interval: 2.5th and 97.5th percentiles;
- NumPy percentile method: `linear`.

The complete bootstrap replicate-mean array must be retained, and its exact
byte-level SHA-256 must be recorded. Exponential and hard-cutoff arms may not be
resampled independently, and the four cells belonging to a selected seed must
remain together.

The hard-cutoff within-law `C-B0` mean and a separately labelled paired 95%
bootstrap interval are descriptive. It uses the same 10,000 seed indices,
bootstrap seed, and linear percentile method. The exponential within-law result
must be read directly from validated Stage 3C evidence and reported as reused
evidence rather than recomputed from a new simulation.

## Frozen classification

The hard-cutoff pre-relocation safeguard is

```text
pre_A_ratio_cutoff = total_pre_A_deliveries_C_cutoff
                     / total_pre_A_deliveries_B0_cutoff.
```

The classification is **INTERACTION_DETECTED** only when all conditions hold:

1. all 40 new hard-cutoff arms are valid and complete;
2. all 40 reused exponential arms and their Stage 3C identity are valid;
3. `pre_A_ratio_cutoff >= 0.80`;
4. the 95% bootstrap interval for mean interaction lies wholly below zero or
   wholly above zero.

If the complete evidence and frozen statistics are valid but the interaction
interval includes zero, or the pre-A safeguard is below 0.80, the classification
is **NO_CLEAR_INTERACTION**. If an interaction is detected, its observed
direction must be reported without relabelling either direction as a preferred
result.

The classification is **INCONCLUSIVE** if the required evidence is incomplete,
the reused identity is inconsistent, a file is corrupt or missing, a resource
limit is reached, or the frozen calculation cannot be completed. A scientifically
unfavourable but valid outcome is not INCONCLUSIVE and must not trigger reruns.

## Descriptive secondary endpoints

The following are reported by cell without replacing the primary endpoint or
classification:

- primary capped-time mean, median, and non-delivery count for all four cells;
- hard-cutoff `C-B0` paired differences and interval;
- exponential within-law results reused from Stage 3C;
- food B discovery time and missingness;
- cumulative food B deliveries;
- pre-relocation food A deliveries;
- old-food A dwell;
- obsolete-trail ant occupancy;
- final obsolete-trail scalar mass and cells above `signal_off` and
  `signal_on`;
- C recovery episode count, reacquisition rate, timeout rate, food-contact
  endings, and same-ant food B discovery and delivery within 100 steps.

These summaries receive no independent success labels. No seed subgroup,
outlier deletion, alternative censoring rule, added significance test, or
secondary endpoint may change the frozen classification.

## Engineering gates

Stage 3D uses independent implementation, runner, tests, documentation, and
result paths. Existing Stage 3C dynamics, results, reports, and analysis files
are immutable.

Before formal execution the implementation must demonstrate:

1. read-only verification of all reused Stage 3C configurations, receipts,
   execution identity, and file hashes;
2. refusal to overwrite or rerun exponential arms;
3. identical paired initial state and treatment-independent random schedules;
4. a single-variable audit showing decay law is the only environment change
   relative to the corresponding Stage 3C arm;
5. a single-variable audit showing recovery is the only B0/C mechanism change
   within hard cutoff;
6. completed receipts that cover every retained formal output;
7. exact-identity resume only, with completed arms immutable;
8. validation of all 20 four-cell seed records before analysis;
9. headless Matplotlib execution;
10. outcome-blind formal-run stdout until the complete run set is valid.

The test suite must cover the 2,000-step calculation, hard-cutoff timer refresh,
expiry and same-step redeposition, exponential read-only reuse, formal arm order
and identity, paired schedule identity, endpoint capping, interaction
calculation, bootstrap reproducibility, rejection of incomplete/corrupt/mismatched
evidence, resume equivalence, and all earlier regression tests.

Parallel execution may use at most two local workers. It is allowed only if
workers write to disjoint arm directories, share no mutable simulation state,
a non-formal fixture is byte-identical to single-worker execution, and the
combined conservative memory bound fits available local memory. Otherwise the
formal run is sequential. AutoDL, GPU execution, and outcome-triggered reruns
are prohibited.

## Resource limits

| Scope | Frozen limit |
|---|---:|
| Complete Stage 3D CPU | `28,800` seconds |
| Retained Stage 3D output | `8 GiB` |
| One arm wall time | `600` seconds |
| One arm CPU time | `600` seconds |
| One arm peak RSS | `2 GiB` |
| One arm temporary output | `512 MiB` |
| One retained file | `50 MiB` |

Resource checks use engineering information only and must not inspect outcomes
to decide whether execution continues.

## Execution and stopping rules

After implementation, the full uncached test suite and resource dry-run must
pass before formal execution. The formal order contains exactly the 40 new
hard-cutoff arms for seeds `2026092101` through `2026092120`, with B0 before C
inside each seed unless the frozen runner records an equally deterministic
paired worker schedule.

Execution stops immediately on a test failure, identity mismatch, corrupted or
missing evidence, protected-file change, resource-limit breach, nonzero formal
runner exit, or invalid resume request. The incomplete evidence is retained for
audit and may not be deleted, overwritten, or repaired by changing parameters.

Scientifically weak, null, mixed, or unfavourable results are not stopping
conditions. They must be analysed under the frozen rules after all evidence is
valid. No formal arm may be repeated to improve the observed result.

After successful analysis, the required report, primary table, descriptive
tables, bootstrap replicate means, manifest, and figures are written only to
`results/stage3d_decay_law_ablation/`. The final local result commit is created
without push or merge. Completion of Stage 3D does not authorise Stage 4,
LLM/random/TPE search, paper writing, or any further experiment.

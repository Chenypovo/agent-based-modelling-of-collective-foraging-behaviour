# Stage 4A proposal alignment and objective viability audit

Status: **OBJECTIVE_NOT_VIABLE - master decision required before search
preregistration or harness implementation**

This audit is read-only with respect to all Stage 3C and Stage 3D evidence. No
simulation was constructed, no formal seed was run, and no Random Search, TPE,
or LLM campaign was started. The Stage 3D frozen interpretation remains
`NO_CLEAR_INTERACTION`: the decay-law interaction was not detected, hard cutoff
is not established as better or more biologically realistic, its C
pre-relocation efficiency safeguard failed, and no further decay-law experiment
is authorised.

## Proposal-to-implementation alignment

| Proposal component | Current evidence | Status for Stage 4 |
|---|---|---|
| Interpretable scalar pheromone field | Stage 3A introduced float64 scalar concentration, bilateral local sensing, exponential decay, zero diffusion, and coordinate-isolation tests. | Completed within the deliberately narrowed scalar model. |
| Food discovery, recruitment, transport, and trail formation | Stage 3A research-scale fixed-seed validation and later multi-seed runs record all four behaviours. | Completed as model validation evidence. |
| Food-source relocation | Stage 3B introduced relocation at `t_r=6000`, with cargo provenance and no relocation signal supplied to agents. | Completed. |
| Finite local recovery | Stage 3B implemented the 24-step local recovery rule; Stage 3C tested B0 versus C over 20 paired seeds. | Completed; Stage 3C's frozen Mechanism decision is not revised here. |
| Multi-seed evaluation | Stage 3C contains 20 paired exponential B0/C seeds; Stage 3D adds 20 paired hard-cutoff B0/C runs while reusing Stage 3C unchanged. | Completed for the Stage 3C/3D questions. |
| Exponential pheromone decay | Stage 3A-3C use the frozen scalar exponential law. | Completed for the validated baseline and recovery study. |
| Decay-law ablation | Stage 3D compared matched single-deposit lifetime under exponential and hard-cutoff decay. | Completed with frozen classification `NO_CLEAR_INTERACTION`; no tuning or added seeds. |
| H1a decay-rate search | No registered search over exponential half-life or the proposed Stage 4 parameter space has run. | **Not completed.** |
| H1b movement heterogeneity | No matched homogeneous versus bounded scout-like/recruit-like study exists. | **Deferred.** Stage 4 must not imply completion. |
| LLM versus Random Search versus TPE | No common search harness or formal campaign exists. | **Not completed.** |
| Held-out robustness | No Stage 4 development/held-out split or winner evaluation exists. | **Not completed.** |

The proposal originally spans pheromone persistence, movement heterogeneity,
and task switching. In response to the requirement to make the model more
specific, the implemented scientific focus has narrowed to scalar pheromone
persistence and finite local recovery. Movement heterogeneity remains a stated
proposal hypothesis but is outside the present implementation and is explicitly
deferred.

## Endpoint mismatch

Stage 3C and Stage 3D use elapsed steps from relocation to the first completed
food B delivery, capped at `12,000`. That endpoint is event-based and does not
measure sustained retrieval.

Proposal Equation (2) instead defines `R_pre` as the mean retrieval rate during
the final 20% of the pre-relocation phase. It smooths post-relocation retrieval
with a trailing window `w=0.05*T_post` and declares recovery only when the
smoothed rate remains at least `0.8*R_pre` for another full window. With the
implemented timing, the constants are:

- `t_r=6000`;
- `T_post=12000`;
- final pre-relocation reference interval `[4800,6000)`;
- `w=600`;
- candidate recovery times `t` from `6600` through `17400`;
- empty qualifying set gives `tau_rec=12000` and non-recovery.

The Stage 3C/3D ledgers contain exact event time, event type, ant ID, and food
source. All 80 `ledger_events.json` files are covered by their arm's completed
receipt, and their stored byte count and SHA-256 were verified before this
audit. The data are sufficient to reconstruct delivery impulses and calculate
the proposal metric without rerunning a simulation.

For a deterministic discrete interpretation, a delivery at step `d` contributes
to the trailing interval `(s-600,s]`. `R_pre` counts A deliveries in
`[4800,6000)` and divides by 1,200; the post-relocation moving rate counts B
deliveries in `(s-600,s]` and divides by 600. Persistence is checked at every
integer `s` in `[t,t+600]`. This interval convention should be frozen if the
metric is repaired, although shifting an endpoint by one step does not change
the failure below.

## Read-only historical metric audit

| Decay law / arm | Runs | Non-capped under Equation (2) as written | Capped at 12,000 | `R_pre=0` | Non-capped with positive `R_pre` | Median `tau_rec` |
|---|---:|---:|---:|---:|---:|---:|
| Exponential / B0 | 20 | 16 | 4 | 12 | 4 | 600 |
| Exponential / C | 20 | 16 | 4 | 11 | 5 | 600 |
| Hard cutoff / B0 | 20 | 12 | 8 | 9 | 3 | 8,187 |
| Hard cutoff / C | 20 | 13 | 7 | 8 | 5 | 7,335 |
| **Total** | **80** | **57** | **23** | **40** | **17** | - |

The literal capped fraction is 23/80 (28.75%), so the failure is not caused by
more than 90% of runs receiving the cap. The problem is that 40/80 runs have no
delivery during the short final pre-relocation reference interval. For those
runs, `R_pre=0`, the threshold `0.8*R_pre` is zero, and the persistence condition
is satisfied even with no post-relocation retrieval. They are automatically
assigned the earliest admissible value, `tau_rec=600`.

This affects the frozen search baseline directly: 12/20 exponential B0 runs
have `R_pre=0`, so its median `tau_rec` is the mathematical floor of 600. The
proposal target of a 20% median reduction would require a candidate median of
at most 480, but Equation (2) does not permit any recovery time below 600.
Therefore no candidate can satisfy the stated recovery target. Treating the
literal 600 values as successful recovery would also reward absence of baseline
retrieval rather than recovery of retrieval.

## Gate decision and minimum revision

Stage 4A stops at `OBJECTIVE_NOT_VIABLE`. The common search space, campaign
design, resource estimate, LLM interface, search harness, and Stage 4 tests are
not frozen or implemented, because doing so would preregister an impossible
target.

The minimum metric revision requiring master approval is:

> Preserve Equation (2), `t_r`, `T_post`, `w`, the 0.8 threshold, and the 20%
> improvement rule, but add: if a replicate has `R_pre=0`, it cannot establish
> recovery relative to a positive retrieval baseline; record it as
> non-recovery with `tau_rec=T_post`.

Applied retrospectively only as a feasibility check, this rule would leave 17
of 80 runs non-capped and cap 63/80 (78.75%), below the prespecified 90% stop
threshold. The exponential B0 median would become 12,000, making a 20% target
of 9,600 mathematically reachable. These recalculated values are diagnostic,
not an authorised replacement endpoint or a Stage 4 result.

Master must accept, reject, or replace that zero-reference rule before a Stage 4
search preregistration is written. If accepted, the static-efficiency aggregate,
development and held-out seeds, common search space, budgets, resource estimate,
and provider-neutral LLM contract can then be frozen in a new authorised Stage
4A continuation. Until then, formal Stage 4 campaign count remains zero.

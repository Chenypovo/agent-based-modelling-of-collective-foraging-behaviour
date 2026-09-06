# Stage 2C storage plan

Date: 6 September 2026. Status: runner storage design and storage-only validation. No Stage 2C pilot or full run has been started.

> Stage 2C storage engineering only — this is not scientific evidence, a pilot result, or an exact reproduction of Fig. 4.

## Scope and frozen protocol

This change only separates retained outputs, shared seed inputs and transient recovery state. It does not change `docs/STAGE2C_PREREGISTRATION.md`, the 20 registered seeds, either follower rule, N, L, the 10,000-step horizon, the simulation random draws or update order, the registered metrics or gates, the 1.5 safety factor, the four-hour limit, or the 2,000,000,000-byte limit. No prior result directory is changed.

The resource dry-run and storage fixture do not execute an ant-dynamics step. They cannot be interpreted as a Stage 2C resource pilot, a scientific run, or evidence about the PCA hypothesis.

## Original 4.39 GB projection

The original dry-run returned `projected_peak_additional_bytes = 4,387,720,058` and `action = pause`. Its inputs were:

| Item | Bytes | Status |
|---|---:|---|
| Largest historical result directory | 12,288,757 | measured historical proxy |
| Checkpoint numeric allowance | 30,001,600 | analytical uncompressed allowance |
| Two checkpoint slots charged to every run | 60,003,200 | original accounting choice |
| Original `per_run_bytes` | 72,291,957 | 12,288,757 + 2 × 30,001,600 |
| Remaining rule-runs | 40 | preregistered |
| Safety factor | 1.5 | frozen |
| Separate checkpoint overlap | 30,001,600 | original accounting choice |
| Final analysis/figures allowance | 20,000,000 | frozen runner allowance |
| Already stored dry-run material | 201,038 | measured |

The original calculation was:

`201,038 + 1.5 × 40 × 72,291,957 + 30,001,600 + 20,000,000 = 4,387,720,058 bytes`.

It counted two rotating checkpoint slots as long-term data for all 40 completed runs and then added checkpoint overlap again. It also treated the full Stage 2B directory, including figures and diagnostics not emitted per Stage 2C rule-run, as one retained run.

## New storage structure

### Shared once per seed

Each seed has one immutable `shared_seed_artifact.zip`, used by both baseline and PCA. It contains the initial ant state and the complete pre-generated turn schedule. Its metadata binds the seed, paired configuration identity, initial-state hash, turn-schedule hash, source/input/protocol identity and array hashes. `follower_direction_rule` and output routing are excluded only from the shared-pair configuration identity; each run checkpoint still binds its own rule and full behavioural configuration hash.

The second rule loads the existing shared artifact and rejects any seed, configuration, identity or content-hash mismatch. It does not generate or save a second copy.

### Active run

Only one rule-run is active because execution is sequential. It may have two rotating checkpoint slots. Before replacing the unreferenced slot, the stale file is removed while the currently referenced checkpoint remains valid; atomic publication therefore needs at most the current valid slot plus the new temporary slot.

The active checkpoint contains current time, ants and roles, travel paths, return routes and memory, current pheromone intensity/direction accumulators, transition counters, streaming diagnostic accumulators, active transport state, RNG policy identity, rule/config/source/protocol hashes, and references to the shared seed artifact and history manifest. It does not embed the turn schedule, frozen configuration, initial state or all earlier output rows again.

Metrics, sampled agent states, role-specific observations, events and completed-transport observations are appended as immutable JSON chunks. Every checkpoint generation references an immutable manifest with contiguous row ranges and SHA-256 hashes. A previous checkpoint continues to reference its previous manifest, so publication failure cannot invalidate the last valid generation.

Per-run spatial snapshot copies are not Stage 2C registered outputs and are not retained by `StreamingSimulation`. Registered per-time order/count/delivery rows, sampled ant states, all events, sufficient diagnostic accumulators and the final pheromone field remain retained. This is an output-storage change only; movement, transitions, random draws and metrics are untouched.

### Completed run

Completion atomically publishes an immutable `completed/` directory containing:

- consolidated full history tables;
- result, configuration, diagnostic and transition records;
- final agents and the full final pheromone intensity/direction arrays;
- one compact final checkpoint;
- a receipt with completion time, config/source identity, checkpoint generation/hash, shared artifact hash and recursive artifact hashes.

The final checkpoint references the shared seed artifact, consolidated completed-history manifest and hashed final pheromone artifact. It remains loadable and is retained as required by the preregistration. The two active slots and active history chunks are removed only after the completed directory and progress pointer are durable. Interrupted or engineering-failed runs retain their last referenced checkpoint, matching history manifest, shared artifact and failure provenance.

## Retained versus transient accounting

`stored_bytes` counts current long-term files and excludes active rotating slots and active history chunks, because those are added separately as a one-run transient peak. Completed final checkpoints are not excluded: one is retained for every completed run.

The new peak formula is:

`stored_bytes`

`+ 1.5 × remaining_runs × (retained_completed_run_bytes + retained_checkpoint_bytes_per_completed_run)`

`+ remaining_shared_seed_artifacts × shared_seed_artifact_bytes`

`+ active_checkpoint_overlap_bytes`

`+ completion_publication_overlap_bytes`

`+ final_analysis_allowance_bytes`.

The two-slot overlap appears once, not once per completed run. Shared artifacts appear once per remaining seed, not once per rule. The completion-publication allowance separately covers the temporary coexistence of active history and the completed representation. Final analysis and figures retain their own allowance.

Historical estimates and storage-only measurements are explicitly distinguished in `runtime.json` through `measurement_status`; a future completed pilot pair would replace relevant proxies with the largest measured current-machine completed-run values, without reducing the historical bound when the pilot is smaller.

## Storage-only preflight

The preflight uses paper-scale array shapes and non-registered fixture seed `991337`. It executes zero ant-dynamics steps. It creates the initial state and turn schedule, serialises the production shared artifact and initial checkpoint, and then serialises a deliberately conservative non-scientific state in which every ant carries a non-zero bounded random-walk path plus a one-third return route and the pheromone arrays contain dense non-zero pseudo-random values.

The fixture does not use all-zero arrays to demonstrate favourable compression. Lossless ZIP sizes are measured directly; no future compression ratio is asserted. Fixed non-secret hash-shaped identity values preserve the production metadata field lengths while keeping the byte measurement stable when documentation changes. The 1.5 factor remains applied to each remaining run's retained artifacts.

Development storage-only measurements were:

| Artifact | Bytes |
|---|---:|
| Shared initial-state and turn-schedule artifact | 7,665,750 |
| Immutable empty history manifest | 435 |
| Initial checkpoint | 91,343 |
| Synthetic maximum active checkpoint, one slot | 25,425,476 |
| Active two-slot overlap | 50,850,952 |
| Synthetic maximum completed checkpoint | 19,684,283 |
| Dense final pheromone artifact | 5,730,390 |

The fixture's raw numeric content included 8,000,000 bytes of turn schedule, 16,001,600 bytes of travel paths, 5,334,400 bytes of return routes, and 6,000,000 bytes of pheromone intensity/direction accumulators. These are storage fixtures, not generated trajectories or scientific observations.

## Current resource decision

The development dry-run used:

| Formula item | Bytes | Evidence status |
|---|---:|---|
| `stored_bytes` | 208,931 | committed clean-worktree filesystem measurement |
| `retained_completed_run_bytes` | 11,834,031 | historical category proxy plus dense final-field fixture and 1 MB metadata allowance |
| `retained_checkpoint_bytes_per_completed_run` | 19,684,283 | storage-only measured conservative fixture |
| `shared_seed_artifact_bytes` | 7,665,750 | storage-only measured; 20 artifacts remain |
| `active_checkpoint_overlap_bytes` | 50,850,952 | storage-only measured; charged once |
| `completion_publication_overlap_bytes` | 11,834,031 | conservative one-run publication allowance |
| `final_analysis_allowance_bytes` | 20,000,000 | separate allowance |

This gives:

`208,931 + 1.5 × 40 × (11,834,031 + 19,684,283) + 20 × 7,665,750 + 50,850,952 + 11,834,031 + 20,000,000 = 2,127,307,754 bytes`.

The honest conservative estimate remains 127,307,754 bytes above the 2 GB limit. Therefore the resource dry-run still returns `action = pause` and the Stage 2C pilot remains unauthorised and unstarted. No evidence, checkpoint reliability, registered seed, horizon, threshold or safety factor is reduced to force a pass.

An estimate below a threshold would only be a resource dry-run PASS. It would not be a scientific PASS, pilot PASS, PCA result, or author-code reproduction.

# Stage 2C storage plan

Date: 6 September 2026. Status: Storage Pass 2 engineering PASS and storage-only dry-run PASS. No Stage 2C pilot or scientific run has been started.

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

Storage Pass 1 development measurements were (the completed-checkpoint format is superseded below):

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

## Storage Pass 1 resource decision (superseded)

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

That conservative estimate was 127,307,754 bytes above the 2 GB limit. The Storage Pass 1 dry-run returned `action = pause`; the Stage 2C pilot remained unauthorised and unstarted. No evidence, checkpoint reliability, registered seed, horizon, threshold or safety factor is reduced to force a pass.

An estimate below a threshold would only be a resource dry-run PASS. It would not be a scientific PASS, pilot PASS, PCA result, or author-code reproduction.


## Storage Pass 2: completed-checkpoint compression

Only the completed final checkpoint now uses deterministic **ZIP LZMA** (ZIP method 14). Active rotating checkpoints, the initial checkpoint and the shared seed artifact continue to use their existing DEFLATE format (method 8). The production completion writer explicitly requests completed compression only at the configured final time, with the shared artifact, history manifest and external final field present.

Both formats retain schema version 2, the same JSON metadata and all 400 array members. Member order, the fixed 1980 timestamp and file attributes remain deterministic. The existing reversible `float64_xor_v1` representation is unchanged. There is no additional array encoding, deduplication, precision reduction, path truncation or field removal. ZIP headers select the decompressor; the common reader accepts both methods and still checks the complete checkpoint SHA-256, internal array hashes, seed/rule/config/source/input/preregistration identity, the 1,000,000,000-byte decompressed-size limit, and the shared/history/final-field references before accepting restored state.

### Measured member sizes

The non-registered `991337` fixture uses the same production codec and paper-scale shapes, with **zero simulation steps**. Every maximal-fixture travel path, return route and pheromone array is non-zero. No registered seed or scientific metric is used. The initial fixture remains an initial-state sizing reference; it is not used to claim final-state compression.

Raw sizes below include each `.npy` header. Percentages use the complete archive size, including ZIP headers. Individual member records, compressed trial archives and comparison evidence were written only under `/private/tmp/stage2c-storage-pass2/`.

| Members | Count | Raw bytes | Previous DEFLATE bytes | Previous share | New LZMA bytes | New share |
|---|---:|---:|---:|---:|---:|---:|
| JSON metadata | 1 | 374,060 | 23,687 | 0.1203% | 17,034 | 0.1007% |
| Travel paths | 100 | 16,014,400 | 14,659,145 | 74.4713% | 12,557,907 | 74.2542% |
| Return routes | 100 | 5,347,200 | 4,941,231 | 25.1024% | 4,273,330 | 25.2680% |
| Other state arrays | 200 | 28,800 | 16,096 | 0.0818% | 19,651 | 0.1162% |
| ZIP container overhead | — | — | 44,124 | 0.2242% | 44,124 | 0.2609% |
| **Complete archive** | **401** | **21,764,460** | **19,684,283** | **100%** | **16,912,046** | **100%** |

The new production archive is **2,772,237 bytes smaller** (about 14.08%) and is **87,954 bytes below 17,000,000**. Every decompressed member is byte-identical to the old archive, and decoded ant-state identities agree. The production LZMA archive is also byte-identical to the initial algorithm-only trial. The production initial checkpoint (91,343 bytes), active checkpoint (25,425,476 bytes), and legacy final checkpoint remain byte-identical to the pre-change fixture archives; shared storage and the final pheromone file retain their previous measured sizes.

The fixture measures the legacy and new completed formats on every fresh storage preflight, rather than inserting a favourable size constant into the projection. The full per-member measurement is returned with the preflight evidence. The same 1.5 factor still applies to all remaining completed-run outputs and checkpoints; no future compression ratio is assumed.

### Encoding and verified reading time

The isolated production dry-run measured the following on the current Mac CPU, Python 3.9.4 and NumPy 1.26.2. These are storage-fixture timings, not scientific simulation or pilot timings.

| Format | Full production encoding, seconds | Verified archive reading and state decoding, seconds |
|---|---:|---:|
| Previous DEFLATE | 0.495119416 | 0.427277500 |
| Completed LZMA | 5.852722584 | 1.556958917 |

Encoding includes production state packing, array hashes, JSON and compression. Reading starts from archive bytes and includes the complete archive SHA-256, metadata/identity checks, internal array hashes, decompression and reconstruction of the saved state. It excludes filesystem latency and external-artifact restoration; reference restoration and its rejection paths are covered by the small engineering tests. The artificial sizing state has no scientific observation timeline and is never passed to a simulation or endpoint calculator.

Rather than charging only the 5.357603168-second encoding increment, the resource projection conservatively adds the **full new encoding plus verified reading cost**, `5.852722584 + 1.556958917 = 7.409681501 seconds`, to each remaining run before the 1.5 factor. The extra charge remains even if a future observed run duration already includes its final encoding. Missing, negative or non-finite overhead measurements make the time projection unresolved and pause execution. The 14,400-second limit is unchanged.

### Complete measured resource formulas

For comparison, this pass's clean pre-change dry-run measured `stored_bytes = 208,657`, giving:

`208,657 + 1.5 × 40 × (11,834,031 + 19,684,283) + 20 × 7,665,750 + 50,850,952 + 11,834,031 + 20,000,000 = 2,127,307,480 bytes`.

The small difference from the earlier documented 2,127,307,754-byte snapshot is measured dry-run metadata/output-path length, not a change to an allowance or checkpoint. For Storage Pass 2, the complete formula is still:

`stored_bytes + 1.5 × remaining_runs × (retained_completed_run_bytes + retained_checkpoint_bytes_per_completed_run) + remaining_shared_seed_artifacts × shared_seed_artifact_bytes + active_checkpoint_overlap_bytes + completion_publication_overlap_bytes + final_analysis_allowance_bytes`.

The audited production dry-run under `/private/tmp/stage2c-storage-pass2/dry-after/` produced:

| Input | Value | Evidence |
|---|---:|---|
| Already retained dry-run files | 266,996 bytes | measured; now includes detailed member/timing evidence |
| Remaining runs / shared artifacts | 40 / 20 | no scientific run started |
| Completed outputs excluding checkpoint | 11,834,031 bytes per run | unchanged historical categories, dense field fixture and metadata allowance |
| Retained final checkpoint | 16,912,046 bytes per run | new production LZMA fixture |
| Shared seed artifact | 7,665,750 bytes per seed | production measurement; unchanged |
| Active two-slot overlap | 50,850,952 bytes | unchanged; charged once |
| Completion publication overlap | 11,834,031 bytes | unchanged; charged once |
| Final analysis and figures | 20,000,000 bytes | unchanged allowance |

`266,996 + 1.5 × 40 × (11,834,031 + 16,912,046) + 20 × 7,665,750 + 50,850,952 + 11,834,031 + 20,000,000 = 1,961,031,599 bytes`.

Remaining capacity is **38,968,401 bytes** below the 2,000,000,000-byte cap, with **13,968,401 bytes** of margin below the preferred 1,975,000,000-byte target. The checkpoint term saves `1.5 × 40 × 2,772,237 = 166,334,220 bytes`; after the measured metadata increase, the total projection falls by 166,275,881 bytes. No retained evidence or resource threshold was removed.

The complete time formula is:

`elapsed_seconds + 1.5 × remaining_runs × (per_run_seconds + completed_checkpoint_seconds_allowance) + analysis_seconds_allowance`.

`14.419555791 + 1.5 × 40 × (147.110828958 + 7.409681501) + 600 = 9,885.650183331 seconds`.

That is approximately **2 h 44 min 46 s**, leaving 4,514.349816669 seconds below four hours. Simulation time remains the slowest historical Stage 2B proxy; no current-machine scientific pilot has been observed. The dry-run returns `action = continue` for these resource estimates only. Byte counts for metadata and measured elapsed/codec times may vary slightly across fresh temporary directories and machines; each fresh dry-run recalculates them.

### Engineering and preservation acceptance

- No-cache complete suite: **128 passed in 76.79 s**, including all previous tests and seven additional parameterised cases. Command: `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 TMPDIR=/private/tmp MPLBACKEND=Agg MPLCONFIGDIR=/private/tmp/stage2c-storage-pass2/mpl XDG_CACHE_HOME=/private/tmp/stage2c-storage-pass2/cache python3 -B -m pytest -q -p no:cacheprovider --basetemp /private/tmp/stage2c-storage-pass2/full-tests`.
- Baseline and PCA both retain exact scientific-artifact bytes after bounded engineering interruptions at `t=23` and `t=61`. Each new final checkpoint is byte-identical between continuous and resumed execution. Direct checkpoint tests also restore precisely at both stated times; runner tests retain their last durable boundary at `t=20` or `t=60` and replay the uncommitted suffix.
- Both legacy DEFLATE and new LZMA final checkpoints restore and re-encode to the identical new final bytes. Complete SHA mismatch, corrupted payloads with otherwise valid ZIP CRC and whole-file hash, array-hash mismatch, seed/rule/config/identity mismatch, oversized decompression claims, and corrupt shared/history/final-field references are rejected. Existing embedded checkpoint compatibility tests still pass.
- All Stage 2C dynamics tests now use non-registered fixture seeds: `991337`, plus `991338` only for the existing different-seed initialisation check. Test guards forbid every registered scientific seed and paper-scale simulation initialisation, including the isolated frozen-source comparison. The formal seed manifest, bootstrap seed, scientific configuration and rules are unchanged.
- The production dry-run was additionally executed with simulation constructors, `step`, `run` and endpoint calculation replaced by failure guards. It produced only planned/missing metric placeholders, zero simulation steps and no scientific metrics. No `runs/` directory or formal `results/stage2c_multiseed_confirmation/` directory was created.
- Before/after SHA-256 maps match for **110 protected files**, including ignored report/result material, and **26 frozen source files** match their initial and frozen-commit identities. Preregistration SHA-256 remains `2dfe51cdc027f67994745b86c2e40d42babbc3188db0cdeb3965b52e30247bc6`.
- Full-test log, individual member analysis, before/after archives, dry-run JSON and protection maps remain under `/private/tmp/stage2c-storage-pass2/`. No Stage 1, 2A or 2B result or report was modified. Only this plan, the checkpoint/storage-time code and the Stage 2C engineering tests are included in the local change.

**Engineering acceptance: PASS. Storage-only dry-run resources: PASS.** This is not a pilot PASS, a scientific result, mechanism evidence, or a Fig. 4 reproduction. No `20260901` pilot or other scientific simulation was run. Pilot execution remains paused pending separate explicit authorisation; this storage change does not grant it.

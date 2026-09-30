# Stage 3D engineering specification

Stage 3D adds one independent hard-cutoff execution and analysis layer. It does
not modify the Stage 3C simulation, evidence, or analysis. The hard-cutoff arms
instantiate the frozen Stage 3C B0 and C simulation classes with a validated
`DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=2000)`.

## Execution identity and evidence

Formal execution requires a clean tracked worktree. A pre-run audit binds the
Git commit, branch, Python, NumPy, platform, execution-critical file hashes,
all Stage 3C evidence hashes, all 40 new configurations, the matched-lifetime
calculation, pair identity, random schedules, and protected files.

Every new arm writes to a seed/arm-specific temporary directory. No scientific
file is published during simulation. On success, the runner writes the complete
artifact set, validates every file, writes a receipt covering every file except
the receipt itself, and atomically renames the directory to its final path.
Completed arms cannot be overwritten.

An externally interrupted, unpublished arm retains `resume_identity.json`.
Resume is permitted only when seed, arm, complete configuration, and frozen
execution identity match. Because all random schedules are deterministic and no
scientific output has been published, resume restarts that arm from step zero.
A fixture audit verifies that this restart produces byte-equivalent scientific
payloads to continuous execution. An arm that records `failure.json` is not
automatically retried.

## Hard-cutoff event order

At each simulation step the field clock advances before movement and contact.
A hard-cutoff cell expires when
`current_time - last_deposit_time >= cutoff_steps`. Expiry sets concentration
to zero and clears its timer. Transporter deposits occur later in that same
step, add `q` to the current concentration, and set `last_deposit_time` to the
current field time. Therefore a deposit on the exact expiry step first observes
expiry, then starts a fresh 2,000-step timer. A positive deposit before expiry
adds concentration and refreshes the timer. Zero deposits do not refresh it.

## Pairing and single changes

The Stage 3C horizon-stable schedules are reused unchanged. Their independent
streams depend on seed, ant id, and stream id, not on decay law or arm. A
machine-readable audit verifies identical initial headings, FCRW turns,
follower noise, and recovery-side schedules for corresponding exponential and
hard-cutoff cells.

Across decay laws, the simulation record may differ only in `decay`. Within the
hard-cutoff law, B0 and C may differ only in the treatment label and the frozen
24-step recovery branch. Food coordinates remain confined to contact and
offline measurement code.

## Execution mode and resource handling

Formal runs are sequential on one local CPU worker in ascending seed order,
with B0 followed by C. This avoids shared mutable state and removes the need to
claim a two-worker memory bound. Per-arm wall, CPU, RSS, temporary-output and
single-file limits are checked during and after execution. The complete study
checks the 28,800-second CPU and 8-GiB retained-output limits.

Formal run stdout contains engineering status and resource fields only. Science
is read only after all 40 new arms and 40 reused Stage 3C arms validate. The
analysis is single-use: existing output files cause refusal rather than
overwrite.

## Analysis

The primary analysis preserves each complete four-cell seed record during
10,000 bootstrap resamples. The saved `.npy` file contains all mean interaction
replicates, and the JSON record contains both its data SHA-256 and file SHA-256.
Secondary results are descriptive. Figures use Matplotlib Agg and carry the
required exploratory/reuse statement.

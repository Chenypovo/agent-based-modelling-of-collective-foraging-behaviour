# Stage 2C-E5A bounded resource-history control

## Scope

Stage 2C-E5A changes administrative resource logging only. It does not change
movement, follower direction, pheromones, state transitions, random draws,
turn schedules, seeds, population, arena, horizon, late window, endpoints,
bootstrap definitions, scientific gates, the 2,000,000,000-byte limit, the 1.5
safety factor or the 28,800-second limit. It does not authorise a scientific
run or a scientific conclusion.

The production transaction is explicit:

```bash
./run_stage2c.sh --mode repair-resource-history
```

This command is not a resume command. It exposes no seed, rule, horizon or
scientific configuration override. A later PCA resume, later seeds and final
analysis each require separate authorisation.

## Bounded representation

Before any root administrative file is changed, the transaction stores the
exact pre-migration administrative files in a deterministic immutable ZIP.
This includes every byte of the original `checkpoint/progress_manifest.json`.
The immutable intent records the archive size and SHA-256, each member's size
and SHA-256, and the SHA-256 of every non-administrative formal file.

The active manifest then uses resource-history schema 2:

- `legacy` binds the original manifest and archive, the 190-record count, an
  ordered-record hash, the latest record hash and the latest decision;
- `static_evidence` binds one content-addressed catalogue;
- `records` contains later compact decisions in strict sequence order.

The catalogue deduplicates large evidence objects by canonical-content
SHA-256. Fixed objects may not silently change. `measurement_status` may have
more than one content-addressed value because its evidence basis can change as
runs complete. Each compact record retains the full projection hash, the
resource-decision scalars, static references and a hash of the per-run status
view. `runtime.json` remains the current full projection.

Each compact record is at most 2,048 bytes. At most 4,096 post-migration
records and 1,000,000 bytes of static evidence are permitted. The resource
projection reserves all still-available bytes under both limits before it can
return `continue`. Thus the whole remaining study reserves at most 9,388,608
additional resource-history bytes, rather than assuming that future logs are
free.

Corrupt archives, hashes, static references, member sets, sequences, duplicate
records, missing records, altered latest decisions and unknown schemas fail
closed.

## Three execution identities

The migration preserves three separate execution bindings:

- Baseline seed `20260901` remains bound to
  `51504fa4156042f1fbc7468c4db26a64dd16d527`;
- the already-started PCA seed `20260901` remains bound to
  `2072f86aba72109bd4c6d60645a86cff6aff4211`;
- all 38 strictly uninitialised records bind to the new committed E5A control
  identity when the migration is eventually authorised.

The current controller must be a different committed identity with a clean
tracked worktree. All identities must share the preregistration hash, input
hash and all 26 frozen scientific source hashes. The compatibility proof also
checks the accepted runner, metric, checkpoint, streaming and storage
definitions. A resumed PCA checkpoint is loaded with its original E4B
execution identity, and any final PCA receipt continues to carry that identity.

## Exact production admission

The production command takes the existing lock without creating or truncating
it. Before the first write it verifies:

- the old control commit and valid E1, E2 and E4 evidence;
- E4's recorded `continue` decision;
- the paused `two_gb_limit` runtime with unchanged limit, safety factor and
  time allowance;
- the completed Baseline receipt and exactly 15 artifacts;
- the interrupted PCA at t=7500, generation 76, its exact checkpoint path and
  SHA-256, its internal time, shared initial identity and sole interrupted
  attempt from t=0;
- two standard rotating PCA checkpoint slots and the referenced lossless
  history;
- 38 exact uninitialised records;
- no symlink, unknown file, unknown transaction or active lock;
- committed clean E5A code whose changes are restricted to this document,
  resource-history/control code, CLI integration and tests.

The transaction records immutable intent, deterministic old and prepared
archives, content hashes, atomic root publication, complete engineering tests,
post-publication checkpoint loading, fixed-point resource accounting and an
immutable receipt. An interrupted transaction can only continue the same
intent. A completed transaction cannot run again.

Every receipt declares:

```ini
simulation_started=false
simulation_steps_executed=0
scientific_metrics_generated=false
pca_resumed=false
other_seed_initialised=false
final_scientific_conclusion_available=false
```

If the migrated resource calculation still says `pause`, the migration remains
an administrative migration only and does not resume anything.

## Engineering-test evidence

The new receipt stores the exact command, complete stdout and stderr, exit
code, passed/failed/skipped/xfailed/xpassed counts, UTC start and finish,
wall-clock duration, temporary-directory peak bytes and long-term receipt
bytes. After all assertions finish, only the newly created test fixture
directory is removed. Earlier engineering, failure and migration evidence is
not deleted or rewritten. Historical external fixture directories are counted
only when they still exist.

## E5A execution boundary

This implementation round permits engineering code, tests, a migration on a
complete copy outside the workspace, read-only estimates and one local commit.
It forbids running the production migration on the formal directory, PCA
`--resume`, pilot, full, analyse or any formal scientific simulation.

# Stage 2C resource amendment — 8 September 2026

This is a transparent, post-start resource appendix. It does not replace or amend the bytes of `docs/STAGE2C_PREREGISTRATION.md`. Implementation of the amendment and migration tool is authorised; applying migration to the formal study requires separate master authorisation.

The original 14,400-second stopping rule operated normally: after the only completed Baseline run, the runner paused for `four_hour_limit` before initialising PCA. That stop was not bypassed. The decision below was made before PCA initialisation and solely from elapsed time, storage and engineering integrity. No Baseline psi, phi, deliveries, axis error or other scientific effect was read to make this decision.

## Effective resource protocol

The cumulative time limit changes from **14,400 seconds to 28,800 seconds**. Future time pauses use `eight_hour_limit`. Original runtime files and historical `four_hour_limit` entries remain original evidence and are never relabelled or recalculated.

The **2,000,000,000-byte storage limit** and **1.5 safety factor** are unchanged. Also unchanged are all 20 seeds, pair order, both follower rules, N, L, steps, late window, primary endpoint, bootstrap seed and repetitions, mechanism PASS/FAIL/MIXED gates, Fig. 4 candidate gates, missing-data rules and the prohibition on rerunning unfavourable results. This amendment makes no scientific claim or hypothesis judgement.

The following machine-readable declaration is verified by the runner. Its complete document SHA-256 is part of the new control identity and resource reports.

<!-- resource-policy -->
{"original_time_limit_seconds":14400.0,"effective_time_limit_seconds":28800.0,"storage_limit_bytes":2000000000,"safety_factor":1.5,"amendment_before_pca_initialisation":true}
<!-- /resource-policy -->

## Resource-only rationale and formulas

The completed Baseline took **250.956673666 seconds**. The existing conservative estimate based only on that completed run is **16,127.480149890982 seconds**:

`453.61370101598305 + 1.5 × 39 × (250.956673666 + 6.716257084) + 600`.

The historical Stage 2B timing ratio is

`147.110828958 / 95.03053899999999 = 1.5480374046705137`.

Applying that ratio to the current Baseline gives a PCA resource proxy of

`250.956673666 × 1.5480374046705137 = 388.49031778665966 seconds`.

A conservative planning proxy after the first pair is

`453.61370101598305 + 388.49031778665966 + 1.5 × 38 × (388.49031778665966 + 6.716257084) + 600 = 23,968.878786430243 seconds`.

The supplied planning proxy **23,976.078375097244 seconds** is retained conservatively. It is 7.199588667001 seconds above the direct substitution above; this difference is an additional planning margin, not a measured cost. No smaller supplied estimate is substituted.

That is approximately 6 hours 40 minutes, with about **4,824 seconds** below the new eight-hour limit. The ratio is a resource-planning proxy, **not measured current PCA time and not a scientific result**. Migration/tests and subsequent actual costs must still be charged; the planning proxy is not a guaranteed completion time.

Storage remains `stored evidence + 1.5 × remaining runs × (retained output allowance + completed checkpoint allowance) + remaining shared artifacts × shared allowance + active checkpoint overlap + completion publication overlap + final analysis allowance`. Old failure evidence, checkpoint repair evidence, deterministic migration archives, every retained engineering-test allowance and the migration receipt are counted. The existing historical lower bounds remain in force before the complete first pair. Exceeding 2 GB still returns `pause`.

## Execution identity and migration

`repair-resource-amendment` is an explicit engineering-only transaction. The completed Baseline retains execution identity `51504fa4156042f1fbc7468c4db26a64dd16d527`; its receipt, final checkpoint, shared artifact and all completed files remain byte-identical. The new study control and subsequent runs use the separately committed amended identity. Progress records the identity registry and each run's execution identity; final analysis reports the same lineage without changing endpoint calculations.

Admission requires exactly the recognised completed-Baseline/39-planned state, the original four-hour pause, valid E1 and E2 evidence, and committed clean code. Equivalence checks compare protected scientific files, metric definitions, configurations and the unchanged run-one/checkpoint-publication/completion functions against the actual old Git commit. The only shared-artifact compatibility exception is the exact old seed artifact pinned by a completed migration, verified against its own identity. No checkpoint is re-signed or re-encoded.

An exclusive existing lock protects the transaction. Immutable intent, deterministic `previous.zip` and `prepared.zip` precede root publication. Old history is retained as an exact list prefix. Root publication is atomic and fsynced; interruption may only continue the same intent. Passed engineering evidence can be reused after interrupted finalisation; failed new tests are retained and stop the transaction. Completed migration cannot be repeated, and ordinary modes reject incomplete migration. Resource accounting includes the receipt itself. A completed migration may still return resource `pause`.

E4A does not execute the formal migration, initialise PCA, inspect scientific effects or produce a paired-pilot or Stage 2C scientific conclusion. Master must separately authorise the formal migration and any later scientific execution.

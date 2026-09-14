# Project progress snapshot — 14 September 2026

## Purpose

This branch is a read-only snapshot for preparing a progress report on another
machine. It combines the committed project history with the local Stage 2C
execution evidence that existed on 14 September 2026.

It is not the active execution branch. Do not resume Stage 2C from this branch
or treat the interrupted PCA history as a completed scientific result.
The zero-byte operational `.runner.lock` file is intentionally excluded from
the snapshot; it is not research evidence and must be recreated by the active
runner when needed.

## Git identity

- Snapshot branch: `codex/progress-report-snapshot-2026-09-14`
- Source implementation commit: `36ab78a32b7ea22f2902574fdb517a5e4b20e4e3`
- Active implementation branch at capture time:
  `codex/stage2c-multiseed-confirmation`
- Local `main` at capture time:
  `02a953af132a44aabcf8be92a873de7694d4a5fb`

## Evidence status

| Area | Status | Evidence-safe interpretation |
| --- | --- | --- |
| Stage 1 single-ant models | Complete | SRW, FCRW and provisional ZW implementations and repeated-run outputs are available. |
| Stage 2A colony workflow | Engineering complete; target state not reproduced | Recruitment and transport occur, but the paper's Fig. 4-like ordered state was not reproduced. |
| Stage 2A diagnostics | Complete | Direction sensing, transporter paths and pheromone-field failure modes were measured. |
| Stage 2B local PCA candidate | Complete, candidate not supported | The frozen single-seed PCA rule improved local continuity but worsened ordering and delivery performance. This does not reject all local-geometry methods. |
| Stage 2C protocol and runner | Engineering complete | Paired seeds, checkpoints, streaming diagnostics, resource gates and audit receipts are implemented. |
| Stage 2C scientific study | Incomplete | One Baseline run is complete. Its paired PCA run is interrupted at t=7500. No paired pilot or multi-seed conclusion is available. |
| Stage 3 / LLM-guided experiments | Not started | No LLM experiment result is present in this snapshot. |

## Stage 2C state at capture

- Confirmatory seeds: `20260901` to `20260920`.
- Planned scientific runs: 40, arranged as 20 Baseline/PCA pairs.
- Completed runs: 1 of 40 (Baseline for seed `20260901`).
- Completed pairs: 0 of 20.
- PCA for seed `20260901`: interrupted at `t=7500` with a valid checkpoint.
- Remaining records: 38 strictly uninitialised runs.
- The latest recorded resource decision is a pause caused by the two-gigabyte
  storage gate.
- E5A bounded resource-history code is committed, but the formal
  `repair-resource-history` migration had not been executed in the captured
  result directory.

Do not quote partial PCA metrics from the interrupted run. Scientific comparison
of Baseline and PCA requires both members of the pair to complete.

## Where to find the evidence

- Proposal and requirements: repository root PDFs/DOCX and `references.bib`.
- Stage specifications: `docs/`.
- Stage 1 report: `results/stage1/REPORT.md`.
- Stage 2A report: `results/stage2_provisional/REPORT.md`.
- Diagnostic report: `results/stage2_diagnostic/REPORT.md`.
- Stage 2B report: `results/stage2b_local_geometry/REPORT.md`.
- Stage 2C preregistration: `docs/STAGE2C_PREREGISTRATION.md`.
- Stage 2C formal state and audit evidence:
  `results/stage2c_multiseed_confirmation/`.
- Current Stage 2C status:
  `results/stage2c_multiseed_confirmation/checkpoint/progress_manifest.json`
  and `results/stage2c_multiseed_confirmation/runtime.json`.

## Recommended report wording

The defensible current conclusion is that the individual and colony simulation
pipelines have been implemented and diagnosed, while exact reproduction of the
paper's ordered collective state remains unresolved. A local weighted-PCA
direction rule was tested as a controlled candidate and was not supported by
the fixed-seed Stage 2B result. The preregistered Stage 2C paired multi-seed
study is engineered but not scientifically complete, so it cannot yet support
a final mechanism verdict.

## Using this snapshot on another machine

```bash
git clone https://github.com/Chenypovo/agent-based-modelling-of-collective-foraging-behaviour.git
cd agent-based-modelling-of-collective-foraging-behaviour
git switch codex/progress-report-snapshot-2026-09-14
```

Use this branch to read evidence and write the progress report. Continue formal
experiments only from the active execution workspace after a separately
authorised resource-history migration and checkpoint-resume decision.

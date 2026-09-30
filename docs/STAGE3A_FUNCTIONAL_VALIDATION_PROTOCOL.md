# Exponential B0 functional validation — pre-run protocol

Authorised after engineering Stage 3A, before Stage 3B. Frozen before any research
scale trajectory in this session. User selected 12,000 steps per seed. This
supersedes the previous tiny-pilot-only scope solely for the runs below.

## Configuration and order

Baseline source: f3273425be2f447fa92b1c7df6bc0064feb99833. Preserve that source
and all existing evidence. Add observation tooling, not steering changes.

N=100; square L=300; nest=(150,150); A=(240,150); B=(150,240);
step_size=0.6; diffusion=0; exponential half_life_steps=1000;
scalar bilateral B0. All other defaults remain as committed: cell_size=1,
q=1, contact radius=0.75, sensor distance=1, angle=pi/4, thresholds on=0.5 and
off=0.25, loss streak=2, follower noise=0.05, max turn=pi/3, FCRW gamma=0.2.
**relocation_step=None**: only A is active. No recovery C.

Seeds, in execution order: **2026091701, 2026091702, 2026091703, 2026091704,
2026091705**. The first is the fixed pilot; the remaining four are exploratory,
not confirmation seeds or a decay-law comparison. No replacement seeds.

Run seed 1 first. Completion requires all 12,000 steps without numerical/state
failure or resource-cap violation. Functional success for expansion requires at
least one discovery, delivery and verified recruitment (defined below). Then
run up to four remaining fixed seeds sequentially. If pilot functionality fails,
diagnose before expansion. Do not tune from B or relocated outcomes.

## Measurement definitions (observations never enter navigation)

- Discovery: environment records a food pickup; record first time/ant/source.
- Delivery: nest contact while carrying; record first time and final A/B totals.
- Raw recruitment: actual fcrw -> follower in `_move`, with pre-movement local
  S>=on. Record time, ant, left/right signal, position, heading, and a diagnostic
  zero-field counterfactual using the same fixed turn/noise (must remain fcrw).
- Verified recruitment: raw recruitment of an ant that has never deposited
  pheromone, proving the triggering trail came from other ants. No per-cell
  source identity is added. This conservative subset is used for the 4/5 gate.
- Follower food arrival: actual contact pickup when the post-movement,
  pre-contact role is follower. Report episode age, travelled distance and
  displacement, and whether that episode was verified recruitment. This proves
  arrival during following, not scientific causal advantage over random search.
- Trail continuity: off-line 8-neighbour connectivity of cells with P>=on and
  P>=off, between cells containing nest/A centres. Also record transport-route
  detectability at the first delivery: fraction and longest consecutive gap
  of the actual first returning ant's deposition positions above each threshold.
  Connected centre-cell paths are a strict geometric diagnostic, not a follower
  steering signal or proof of followability. Evaluate every 1000 steps, at first
  delivery, and endpoint; save field at first delivery and endpoint.
- State: original `validate()` every step; never bypass population, cargo,
  finite number or arena checks. Preserve only event logs, sampled aggregate
  traces and compact fields, not all agents' full step histories on disk.
- Runtime: elapsed wall and process CPU seconds, including initialisation;
  peak process RSS when available, plus exact output bytes. Estimate prospective
  5-pair and 20-pair B0-equivalent cost; C runtime remains unknown.

## Fixed resource limits and advancement

Sequential local CPU only. Hard per-run limits: 600 s wall, 600 s process CPU,
512 MiB output and 2 GiB peak RSS. Check wall/CPU each 100 steps and memory/disk
each 1000; caps may overshoot by one check interval. No GPU/AutoDL.
Stop the current run at a limit, preserving partial evidence and marking it
incomplete. No automatic horizon extension or repeated exploratory runs.

Minimum Stage 3B gate: >=4/5 seeds have discovery AND delivery; >=4/5 have verified
recruitment; scalar-only and food-coordinate isolation remain intact; all runs
have valid state and resource use fits the limits. Provisional feasibility
budget for later **5 pairs**: <=2 CPU-hours and <=2 GiB retained files using
twice the maximum measured per-seed cost, before unknown C overhead. Report
20-pair projections too, but do not authorise paired work here. Absence of any
follower food arrival must be highlighted even if the user's minimum count
gate passes: recruitment alone does not establish useful trail following.

## One revision allowance and fixed failure taxonomy

At most **one baseline revision**, only after a failure supported by observations.
Classify the earliest broken link, with secondary problems retained:
1. Food never randomly found: no pickup.
2. Transporter fails to return: pickup but no delivery; distinguish insufficient
   remaining observation time from invalid route implementation.
3. Trail vanishes before return: first-delivery route detectability is incomplete
   because of age/decay (rather than an undeclared spatial spreading mechanism).
4. Follower cannot detect trail: extant detectable deposits but no verified
   recruitment; inspect actual sensor readings and encounters.
5. Follower detects but cannot follow: recruitment exists but follower arrivals
   absent; inspect episode lengths, motion and loss events.

No speculative pre-run adjustment. If revision is needed, append a dated
decision with evidence, exactly one coherent change and unchanged seeds/horizon
**before** its execution. Retain original results separately. Re-run the same
pilot first; only if it succeeds may the same remaining four seeds be used for
the revised candidate. No second revision, no parameter sweep, no cherry-picked
seed replacement. Compare diagnostic observations honestly; this is exploratory
baseline repair, not held-out confirmation or recovery evaluation.

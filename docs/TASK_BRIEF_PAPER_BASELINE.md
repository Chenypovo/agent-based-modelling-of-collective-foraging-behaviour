# Task brief: Zhang & Yong (2023) baseline with Eq. (1) pheromone + five static checks

Written 2026-10-02 by the master session after the supervisor meeting. Read `docs/HANDOFF.md` and
`from_prof/PhysRevE.108.054306.pdf` (Zhang & Yong 2023, Sec. IV, Fig. 4, Eqs. 15–17) first.
Same process as before: plan file committed before any run, fresh seed blocks, ≤ 4 workers at low
priority, save per run, new branch from `h1b-heterogeneity`, do not push or merge without the user.
Target: finish by 5 Oct; H1a/H1b reruns and H2 follow in later briefs (deadline 15 Oct).

## Why

- Proposal Sec. 5.1: the model is "based primarily on Zhang and Yong (2023)" and must pass static
  checks (food discovery, recruitment, trail formation, transport, transition from dispersed to
  organised foraging / task redistribution) **before** any hypothesis test. H1a/H1b so far were run
  on a model that never passed these checks; keep those results as exploratory.
- Our scalar model departed from the paper in two rules that likely prevent organisation:
  1. after delivery the paper's transporter becomes a **follower** and returns to the food along the
     trail; ours reverts to a random-searching forager;
  2. the paper's transporter retraces a **coarse-grained** memory (every 3rd vertex; repeated trips
     straighten the route — the supervisor's sketch); ours retraced exactly, then used path integration.
- The paper has no evaporation/diffusion and lists "trail longevity (evaporation)" and
  "egocentric and geocentric navigation" as future work. Stage 2 (`src/colony/`, paper-faithful,
  no decay) reached task redistribution but stayed disordered (ψ ≈ 0.64); its diagnostic named the
  absence of decay as a likely cause. Proposal Eq. (1) adds decay + diffusion.

## Fixed decisions (user, 2026-10-02)

- Return to the paper framework. Searching walk = **FCRW** (γ = 0.1, Θ = 50°, step 0.6, as in
  Fig. 4). **ZW** (same γ, Θ; generator in `src/ant_walks/models.py`) is run as a comparison arm in
  the validation because it costs only extra runs; the baseline stays FCRW.
- 100 ants, 300 × 300, **reflective** boundaries (paper), 12,000 steps for static runs (paper Fig. 4
  snapshots are at t = 10,000 and its order-parameter curves run to 20,000; our checks average over
  [10,000, 12,000)). A 600 × 600 arm is a robustness check only.
- Geometry: nest (150, 150); food A at distance 90 on the 45° axis (so the paper's target
  φ = π/4 applies); relocation food B (used later) at the same distance on the 135° axis.
  The paper's Fig. 4 layout is roughly nest (90, 90), food (240, 240), distance ≈ 212 (estimated
  from the figure, as in Stage 2). Our shorter distance makes discovery and trail formation easier,
  so our timings are not directly comparable with Fig. 4; a paper-layout arm (below) gives the
  direct comparison. The report must state this.
- Pheromone = proposal Eq. (1) via `DiffusingField` (explicit FD, P = 0 at the edge, D = 0 reproduces
  the validated field). Sensing = existing bilateral scalar sensing with on/off thresholds.
- Old work stays: Stage 5, H1a, H1b results are kept and labelled "exploratory, earlier model".

## Model rules to implement (as options; "off" must reproduce current behaviour, with tests)

| Role | Rule |
|---|---|
| Forager | FCRW (or ZW); becomes transporter on food contact; becomes follower when bilateral signal ≥ on-threshold. |
| Transporter | Retraces its own remembered path coarse-grained with stride 3 (keep vertices 0, 3, 6, …, last), moving 0.6 per step along the interpolated reversed route; deposits q = 1 per step. On nest contact: delivers, path memory resets at the nest, **turns 180° and becomes a follower** (paper: T → f). |
| Follower | Existing scalar trail following; becomes transporter on food contact (paper: f → T); if the signal stays below the off-threshold for `loss_steps`, reverts to forager (not in the paper; needed for relocation — state it as our addition). |

Reuse `src/colony/` where it helps (coarse-grain route, φ/ψ order-parameter code, Stage 2 tests),
but the field must be the Eq. (1) scalar field.

## Five static checks (proposed defaults — written before any run; the user may change them only before Step 3)

Measured on 20 seeds per condition; a check passes if the **median meets it and ≥ 16/20 seeds meet it**.
Two tiers, fixed now (user, 2026-10-02): checks 1–4 are the same in both; only check 5 differs.
"Full pass" = all five at the full level; "basic pass" = checks 1–4 plus check 5 at the basic level.
Why the basic tier: Stage 2 reached only ψ ≈ 0.64, and our follower → forager reversion (not in the
paper) keeps some ants searching, so ≤ 10% foragers may be unreachable. The report states which tier
the baseline reached.

| Check | Metric | Pass |
|---|---|---|
| 1. Food discovery | first-passage time (first pickup) | ≤ 4,000 steps |
| 2. Recruitment | share of food pickups made by ants that arrived as followers, in [4,000, 12,000) | ≥ 50% |
| 3. Trail formation | share of pheromone mass within 5 units of the nest–food segment at t = 10,000 | ≥ 50% |
| 4. Transport | deliveries in [6,000, 12,000) | ≥ 100, and cumulative deliveries close to linear in that window (report R²) |
| 5. Organised foraging / task redistribution (paper Fig. 4, Eqs. 15–17) | ψ, φ, role counts averaged over [10,000, 12,000) | **Full pass:** ψ ≥ 0.9; |φ − π/4| ≤ 0.1; foragers ≤ 10% of N. **Basic pass:** ψ ≥ 0.8 and ≥ pheromone-off ψ + 0.1; |φ − π/4| ≤ 0.1; foragers ≤ 25% of N |

Controls on the same seeds: **pheromone off** (deposit 0) must fail checks 2, 3 and 5 (shows the
order comes from pheromone); **ZW** arm reported with the same table. **Arena 600 × 600** arm (user, 2026-10-02;
supervisor suggested a larger arena): same baseline settings, nest at (300, 300), food A still 90
units away on the 45° axis, cell size 1; checks whether the result depends on walls keeping ants near
the nest. Report its five-check table; if it fails, the report says the baseline depends on arena size.
It does not change which baseline is chosen. Report time series of ψ, φ and
F/T/f counts and snapshots at t = 1,000 / 4,000 / 10,000 like paper Fig. 4.

## Steps

0. Plan `docs/PAPER_BASELINE_PLAN.md` (seeds, grid, rules above with any clarifications), committed before runs.
1. Implement the rules + tests (T → f with 180° turn; stride-3 route; reflective boundary;
   pheromone-off; φ/ψ on synthetic fields: aligned → ψ = 1, uniform → ψ ≈ 2/π).
2. **Paper-faithful check** (exploratory, 10 seeds): no decay, D = 0, FCRW. Report whether it
   orders. This documents what Eq. (1) adds.
3. **Calibration** (exploratory, fresh seeds, 10 per cell): half-life ∈ {500, 1000, 2000},
   D ∈ {0, 0.01, 0.02}, thresholds ∈ {0.5/0.25, 0.25/0.125}. Selection rule (supervisor: pick the
   best): among cells at **full pass**, choose the one with the most deliveries in
   [6,000, 12,000); if none, do the same among cells at **basic pass**; tie within 5% → smaller D,
   then half-life 1000. If no cell reaches basic pass, stop and report to the user.
4. **Validation** of the chosen baseline: 20 fresh seeds; pheromone-off control; ZW arm; arena-600 arm;
   **paper-layout arm** (static only, 20 seeds, 20,000 steps): nest (90, 90), food (240, 240), same
   baseline settings, reported against paper Fig. 4 (order-parameter curves to 20,000, snapshots at
   1,000 / 4,000 / 10,000). For comparison only; not used for H1a/H1b and does not change the choice.
5. **Write-up** `results/paper_baseline/REPORT.md` (plain figures: line plots, not heatmaps; one
   sentence per figure saying what it shows) + update `docs/HANDOFF.md`.

## Needs the user

- Change any pass threshold above **before Step 3** runs.
- If no calibration cell passes, decide what to relax.

## Out of scope here

H1a/H1b reruns and H2 (next briefs), path integration / landmarks (optional extension later).

# Stage 3B: finite recovery search and paired relocation pilot

Status: frozen before Stage 3B implementation or simulation. Starting identity:
branch `codex/stage3-scalar-decay-baseline`, commit `658e39439a1e94f7ff185d2cefc92bdeba5f19a8`.

This is an engineering and exploratory five-seed paired pilot. The five seeds
were already observed in Stage 3A, so they are not confirmatory or held out.
Negative results are valid and cannot trigger tuning, seed replacement, reruns,
longer horizons, or selection among recovery variants.

## Scientific and information boundary

B0 remains the fair main baseline. C changes exactly one mechanism: after a
follower loses its signal, it performs a finite local recovery search before
falling back to the same FCRW. Both use ground scalar pheromone concentration,
exponential half-life 1000 steps, diffusion 0, and no hard cutoff. Neither cell
nor agent receives cell direction, food/nest direction, source identity, global
trail, global field-search result, or food identity usable for navigation.
Navigation makes exactly two local scalar queries. Food coordinates exist only
for environment contact and offline reporting.

All new recovery state, numerical choices and behavioural interpretation are
**provisional**. Recovery is an engineering hypothesis, not a biological fact.

## Frozen shared configuration

N=100; L=300; nest=(150,150); A=(240,150); B=(150,240);
step_size=0.6; cell_size=1; deposit q=1; contact radius=0.75;
exponential half-life=1000; diffusion=0; signal_on=0.5; signal_off=0.25;
loss_steps=2; bilateral sensor distance=1 and angle +/-pi/4; max turn=pi/3;
follower noise amplitude=0.05; FCRW gamma=0.2; total steps=12000;
relocation_step=6000. B0 loses signal after two consecutive S<off samples and
uses FCRW on that same movement, exactly as the frozen implementation does.

At t=6000 A is removed and equally distant B becomes active. Existing field,
agents, heading, roles, timers and own paths are untouched; no relocation signal
reaches ants. Carried A remains deliverable and never counts as B recovery.
The shared event order remains decay -> relocation -> sensing/movement -> contact
-> deposition. Before t=6000, relocation B0 must replay a same-seed static B0
step for step, including agents, cargo, scalar field and events.

Frozen execution order: for each seed 2026091701 through 2026091705, run B0 then
C; finish the first pair and its engineering/resource audit before later pairs.
There are ten runs total and no replacement or additional seed.

## C recovery rule

Each ant has an explicit local `RecoveryState` with `recovery_active`,
`recovery_step`, `recovery_anchor_heading`, `recovery_initial_side`, and
`last_reliable_heading`. B0 constructs an independent side schedule for pairing
identity but never reads it during movement.

While normally following, if S=max(C_L,C_R)>=signal_off, first apply the frozen
scalar steering and store the resulting heading as `last_reliable_heading`.
Low samples do not update it. On the second consecutive S<signal_off, C starts
recovery instead of using FCRW. The anchor is the last reliable heading. The
normal invariant is that it exists because a follower can only be recruited at
S>=signal_on. Explicit fallback, used only if externally supplied invalid state
breaks that invariant, is the pre-movement current heading; it is logged as a
fallback and uses no environmental coordinate.

Duration is exactly 24 recovery movements, four fixed six-step segments. Their
target offsets from the anchor are `side*15`, `-side*30`, `side*45`, and
`-side*60` degrees. Each movement turns toward the segment target by the shortest
circular angle, clipped to the shared max turn, then adds the already precomputed
per-ant/time follower noise and clips the combined turn to max turn. This uses
the same noise schedule entry B0 would have at that global time; it draws no new
noise. The provisional ordering is target correction plus noise, then clip.

Initial side comes only from a precomputed +/-1 schedule generated with
`SeedSequence([global_seed, ant_id, 4])`, indexed by global time minus one.
Entering recovery never draws randomness. B0 and C have identical initial state,
FCRW turns, follower noise and side schedules; B0 does not use sides.

Every recovery movement first reads the same two local scalar samples. If
S>=signal_on, recovery clears in that same step and frozen follower scalar
steering supplies that movement. Values `signal_off <= S < signal_on` do not end
recovery. Otherwise the scheduled recovery movement occurs and increments the
counter. After movement 24, recovery state clears and role is set to FCRW;
movement 24 is still recovery. The following global step uses exactly the frozen
FCRW schedule at that time, with no saved recovery bias. Food contact may end an
episode after its recovery movement and changes the role to transporter through
the unchanged environment contact rule. No episode is extended or broadcast.

## Frozen observations

Recovery episodes store compact summaries: seed, ant, start/end, start position,
anchor, side, duration, outcome (`reacquired`, `timeout`, `food_contact`),
reacquisition position/concentration, movement distance, anchor fallback flag,
and whether B pickup or delivery occurs within a fixed **100-step post-episode
window**. This window is provisional, metric-only, frozen before simulation, and
does not change behaviour. Reacquiring any signal is not labelled correct-route
recovery. Old/new route labels are offline geometry only.

Every 100 steps record role counts (B0 has recovery=0), ants within a provisional
10-unit radius of old A, old-food dwell ant-steps, scalar active area at off/on,
and old-trail residual cell/intensity summaries. The offline old-trail region is
the set of cell centres within 2 distance units of the straight nest-to-A line
segment; this provisional metric is never supplied to ants. Field snapshots are fixed at
t=5999, 6000, 7000, 9000 and 12000 only. Long-term output excludes per-step
agent states and per-step fields. Seed 2026091701 retains full compact events;
later seeds retain summaries, sampled series and recovery episodes only.

Pre-relocation report A discovery/delivery, cumulative A deliveries, verified
recruitment, follower food arrivals/episode lengths, delivery rate per 1000 steps,
and recovery count. Post-relocation report B first discovery/delivery, B totals,
missing flags, capped recovery time (first B delivery minus 6000, capped at 6000;
if no B delivery, 6000), old-food dwell, role series, active area, residual old
trail, and complete/incomplete cargo. Pair deltas are C-B0 for first B discovery,
first B delivery, capped recovery time, B deliveries and pre-A deliveries.
If both arms lack a first event, its delta is null; if one lacks it, use the
capped time for the recovery-time delta and report event delta as null.
Old-food dwell ratio is C/B0 post-relocation dwell, null when B0 dwell is zero.
Recovery reacquisition rate is reacquired episodes / ended recovery episodes.
No significance test or confirmatory claim is permitted.

## Gates and resources

Before research runs: tests, scalar/food isolation, random-schedule identity,
single-change audit and same-seed B0 static-prefix replay must pass. First execute
B0 then C for seed 2026091701 and audit the pair. Engineering failure preserves
the scene and stops without automatic repair/rerun. C performing worse is not an
engineering failure.

Each local Mac CPU run is capped at 600 s wall, 600 s process CPU, 2 GiB peak RSS
and 512 MB temporary output. Check time every 100 steps and RSS/output every 1000.
All five pairs are capped at 2 CPU-hours and 2 GB retained output. Any file above
50 MB stops the pilot. Target each long-term run below 10 MB and the commit below
100 MB. No GPU, AutoDL, Stage 2C/PCA, hard-cutoff comparison, diffusion experiment,
optimiser, 20-seed confirmation, push, merge or automatic next stage.

Engineering PASS requires every stated identity/isolation/test/state/protection
and resource gate, and ten completed runs unless a predefined engineering error
causes the required stop. Pilot viability requires actual recovery episodes,
complete episode metrics, single-change attribution, at least one pair with B
discovery or delivery, and enough output to design a later confirmation study.
Five-seed direction is descriptive only; it cannot establish population benefit,
SOTA, or confirmed recovery efficacy.

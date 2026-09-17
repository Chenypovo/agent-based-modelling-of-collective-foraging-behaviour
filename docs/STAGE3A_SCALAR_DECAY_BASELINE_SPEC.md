# Stage 3A: pure scalar B0 and decay infrastructure

Written before implementation. This is an independent, paper-informed model,
not an exact reproduction of Zhang–Yong (2023). Stage 2A is a legacy baseline;
the fair main control for new experiments is B0. Stage 2C/PCA remains frozen.
Only engineering validation is authorised here; Stage 3B requires master review.

## Evidence labels

- **confirmed (code):** the frozen `src/ant_walks/models.py` implements FCRW
  sign repetition with probability gamma and uniform turn magnitude. Stage 3
  calls that implementation; it does not redefine it. Source/version identity
  is in `protected_sha256_before.json` (base HEAD 36ab78a).
- **confirmed (mathematics):** exponential rate lambda = ln(2)/half_life_steps,
  its inverse, and the single-deposit threshold-crossing formula below.
- **provisional:** all new behavioural assumptions and numerical settings in
  the table below, including deposition, sensing, thresholds and event order.
  They are fixed for engineering fixtures, not fitted biological values.
- **engineering choice:** separate `scalar_baseline` package, float64 grid,
  nearest-cell lookup, explicit timestep API, separate per-ant random streams,
  bounded path storage and environment-owned cargo bookkeeping.
- **unresolved:** biological calibration, empirical lifetime law, sensor geometry,
  realistic memory capacity, recruitment/transport rates, and scientific benefit
  of either decay mode. No claim from the paper is newly inferred here.

## Frozen provisional settings

| Rule | Engineering fixture default |
|---|---|
| Arena / nest | square [0,40]^2 / (20,20), contact radius 0.75 |
| Population / horizon / seed | 10 / 100 / 20260917 |
| Motion | step 0.6, FCRW gamma 0.2, maximum turn pi/3 |
| Sensor geometry | two point samples at distance 1, heading +/- pi/4 |
| Signal | S=max(C_L,C_R); on=0.5, off=0.25; equality is detected |
| Loss | 2 consecutive S<off steps; FCRW on the second step itself |
| Scalar steering | b=(C_L-C_R)/(C_L+C_R+1e-12), turn=clip((pi/3)b+noise,+/-pi/3) |
| Noise | independent uniform [-0.05,0.05] radians on follower steps |
| Grid / deposition | cell width 1; q=1 per transporter per step, one containing cell |
| Diffusion | exactly 0, no configurable nonzero implementation |
| Default decay | exponential half_life_steps=20 (canonical lambda=ln(2)/20) |
| Alternative decay | `hard_cutoff_cell_timer`, explicit integer cutoff_steps |
| Memory | own actual outbound vertices, at most horizon+1; reverse replay to nest |
| Boundaries | clip position to square; clip sensor location for nearest-cell sample |
| Food | one unlimited contact source; A=(28,20), B=(20,28), radii 0.75 |
| Relocation | optional fixed integer step; A removed and B added simultaneously |

These are provisional rules even where a value resembles a legacy setting.
Grid indexing includes the upper arena edge in the last cell. No interpolation,
convolution, smoothing or automatic spread is permitted. Repeated deposits add
concentration without a cap; overflow is rejected rather than stored.

## Field and timestep contract

The field stores only scalar concentration and (for cutoff only) a last-deposit
timestamp per cell. Geometry, time and decay configuration are implementation
metadata. No cell direction, direction_sum, mean direction, food identity,
food coordinate, source direction, global path, or hidden target field exists.
The model is ground scalar pheromone, not an airborne plume; diffusion=0.

At integer step t (initial field time 0):
1. Advance the field to t: exponential decay or cutoff expiry.
2. Apply any environment relocation at t, recording carried A cargo.
3. Every non-transporter reads exactly its two local scalar samples from this
   decayed, pre-deposition field; choose role/heading and move. Transporters
   reverse their own outbound path. All movement precedes new deposition.
4. Resolve endpoint food/nest contacts (no broadcast of coordinates or relocation).
5. Add q at each ant's resulting position if it transported during this step,
   including its delivery step. These deposits become senseable next step.

Both modes therefore use **decay/expiry first, deposition last**. A direct field
`step(deposits)` performs exactly advance-by-one then deposit.
Exponential: P(t+dt)=P(t)*exp(-lambda*dt)+deposition, dt=1 in simulation.
Positive finite half-life or positive finite rate is required. Both can be
supplied only if rates agree within relative tolerance 1e-12, zero absolute
tolerance; normalise to the half-life-derived lambda when both are supplied.
No silent precedence for inconsistent inputs. Equivalent parameterisations are
an equivalence check, never a scientific ablation. Cutoff rejects exponential
parameters; exponential rejects cutoff parameters.

`hard_cutoff_cell_timer`: a positive deposit adds concentration and refreshes
that cell's timestamp. Zero deposit does not refresh it. There is no continuous
decay. At age >= cutoff_steps the whole concentration clears before same-step
new deposits. This cell-level timer is not a molecular lifetime model.

Future matching uses a single reference deposit q>threshold>0:
T_detect=ln(q/P_threshold)/lambda. Freeze **ceil(T_detect)** as cutoff_steps
(snap numerical values within 1e-12 of an integer to that integer). At exact
threshold equality exponential is still detected, whereas cutoff is zero at
expiry: report this discrete endpoint difference, do not tune it away.
Repeated deposition refresh/addition means the modes are not equivalent.
Here only the conversion is implemented/tested; no foraging-based selection.

## Navigation and information isolation

Navigation accepts heading, C_L, C_R, role, consecutive low-signal count, a
pre-generated FCRW turn and one fixed-distribution noise draw. It receives no
environment, field object, position, food coordinate, cargo identity or event.
Positive mathematical angle means left. Equal concentrations give zero
deterministic turn; symmetric noise is independent of the environment.
The sensor adapter sees position/heading and scalar field only, and makes two
point queries. It never searches the whole field.

Roles are exactly `fcrw`, `follower`, `transporter`. A searching ant with S>=on
becomes follower. A follower increments low count only when S<off; otherwise
resets it. On the loss-count limit it uses FCRW immediately, with no recovery,
casting, saved reliable trail direction, or recovery_duration parameter.
FCRW turns come from the existing Stage 1 API, with one schedule entry per global
step, consumed at the current step when searching; no special search on loss.

All ants retain only their own outbound positions for possible reverse transport.
Transporters need no food/nest vector. After delivery the path resets at the
current nest-contact position. This finite, horizon-bounded memory is permitted
self-path memory, not a global route or inference of a food destination.
Food coordinates exist only in the contact environment (and reporting/config).
Cargo provenance is owned by the metric ledger, never passed to navigation.
Source contact can trigger pickup but never steer or bias a tie/noise/search.

## Relocation and metrics

The environment changes active source A to equal-distance B at the declared
step without touching the field or ants. No relocation message reaches agents.
Discovery is each pickup contact, counted separately by A/B (not unique scouts).
Deliveries use the source identity recorded at pickup. At relocation record
IDs of ants already carrying A; later A deliveries remain A. No recovery score
is computed in Stage 3A. Endpoint collision rather than swept collision is a
provisional geometric rule.

## Acceptance and scope

Test analytic decay, repeated deposits, parameter normalisation, cutoff expiry
and refresh, common order, footprint/non-diffusion, field schema, left/right/tie,
loss-to-FCRW, coordinate isolation, relocation/cargo, population, bounds,
finite values and reproducibility; run all legacy tests without cache/bytecode
and with MPLBACKEND=Agg. Hash every pre-existing tracked file plus existing
src/tests/scripts/docs/results and the four protected material trees, then
verify bytes and protected-tree membership after execution.

Only single-cell traces, a single ant on an artificial straight trail and gap,
a 10-ant/100-step smoke test and a tiny relocation fixture may run. No recovery C,
formal multi-seed confirmation, N=100/12000, scientific decay comparison, scan,
diffusion experiment, LLM/optimiser, GPU or AutoDL. Record runtime and disk bytes.
Engineering PASS needs every gate; failure prevents advancement. If PASS, make
only the requested local commit, no push/merge, and stop for master acceptance.

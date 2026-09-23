# Stage 4 search benchmark preregistration

Status: **OBJECTIVE_VIABLE_WITH_PREREGISTERED_AMENDMENT**. This freezes the comparison design before any Stage 4 candidate, campaign, or external LLM request. The retrospective 80-run Stage 3C/3D audit is endpoint feasibility evidence, not a Stage 4 scientific result. Its 63/80 (78.75%) capped fraction limits discrimination and can create ties.

## Scientific scope and objective

The model remains a scalar pheromone model with exponential decay, zero diffusion, `signal_on=0.50`, and Stage 3C deposit amount, arena, food geometry, population, relocation at step 6000, and 18000-step horizon. Hard cutoff, PCA, cell direction, food coordinates, global direction, and new mechanisms are excluded. Movement heterogeneity is deferred; H1b is not complete.

The sole modification to Proposal Equation (2) is in `STAGE4_OBJECTIVE_AMENDMENT.md`: a replicate with zero food A delivery in `[4800,6000)` has `tau_rec=12000` and `non_recovery=true`. All other replicates use the frozen trailing 600-step B-delivery rate and inclusive 600-step persistence test. This amendment applies to every method, candidate, and seed and cannot be revised after results. The primary outcome is the median amended `tau_rec` over five development seeds. The secondary constraint is aggregate static efficiency: total food A deliveries in `[4800,6000)` over the five candidate seeds divided by the corresponding frozen B0 baseline total. Equal seed count and window imply the same ratio of average rates. If the baseline total is zero, mark the entire benchmark `INCONCLUSIVE_BASELINE`; do not choose replacement seeds.

A candidate meets the biological target only if `median_tau <= 0.80 * baseline_median_tau` **and** `static_efficiency_ratio >= 0.80`. The single minimisation score given identically to all methods is `median_tau` when the static constraint passes, otherwise `12000 + median_tau + 12000*(0.80-static_efficiency_ratio)/0.80`. Target discovery uses the two original conditions, not just this score. Lower score selects the campaign winner; exact score ties select the earlier opportunity. No secondary metric breaks a primary tie after results. The retrospective exponential B0 median is 12000, giving a mathematical 9600 target; the actual frozen development baseline must be evaluated independently.

## Search space and identity

Exactly four candidate parameters are permitted:

| Parameter | Domain |
|---|---|
| `half_life_steps` | continuous log scale, inclusive 250 to 4000 |
| `signal_off` | continuous, inclusive 0.10 to 0.40 |
| `loss_steps` | integer 1 to 6 |
| `recovery_duration` | categorical 0, 12, 24, 36, 48 |

Duration zero is B0. Positive durations use the same finite local recovery rule, changing only its maximum duration; after the fourth six-step segment the last local angle persists until timeout. `half_life_steps` and `signal_off` are rounded to nine significant decimal digits before simulation and serialized as decimal strings. A candidate's identity is SHA-256 of UTF-8 JSON with sorted keys and compact separators, containing exactly these four canonical fields. Identical hashes reuse verified results, yet still consume an opportunity.

## Equal budgets and held-out isolation

Development seeds are `2026100101..2026100105`; held-out seeds are `2026100201..2026100210`; campaign IDs/seeds are `2026101001..2026101005`. These do not overlap the Stage 3C/3D seed set. Random Search, Optuna TPE, and LLM each receive five independent campaigns. Every campaign begins with empty own history and has 12 candidate opportunities; every valid candidate runs the same five development seeds. This totals 180 opportunities and at most 900 candidate-seed evaluations before cache reuse. After all 12 opportunities, freeze one winner from that campaign and only then evaluate it on all ten held-out seeds. Up to 150 winner-seed evaluations and 15 baseline-seed evaluations bring the uncached upper count to 1065. Held-out results are invisible during proposal and selection.

Random and TPE use the campaign seed. TPE minimises the frozen score. An invalid LLM proposal consumes an opportunity. Exactly one repair is permitted for malformed JSON, missing fields, or out-of-range values, without changing its hypothesis. Extra fields or a fifth parameter fail the opportunity. A second invalid response also fails. The LLM may return only `hypothesis`, the four parameters, `expected_outcome`, and `brief_justification`. Its prompt contains only its own campaign's structured history and no source code, held-out results, seed choice, or authority to add a mechanism. The provider-neutral mock is the only Stage 4A1 adapter; no external request is authorised.

Cache reuse checks candidate, seed, simulation configuration, source identity, completed receipt, and every recursive artifact byte count and SHA-256. A repeated candidate is never simulated twice when valid cached evidence exists. Method histories never disclose that another method proposed the same candidate.

## Execution gate

Stage 4A1 performs engineering checks and small fixtures only. Formal candidates, campaigns, and external LLM calls remain zero. Stage 4B requires separate master approval of the exact API provider, model name/version, API key environment variable name, temperature, model-seed support, token cap per campaign, and total cost cap. The key must not enter code, Git, logs, or receipts. The storage upper bound in the engineering specification exceeds 8 GiB, so Stage 4B also requires an approved resource adjustment without unequal method budgets. No Random, TPE, LLM, or held-out formal experiment starts under this preregistration alone.

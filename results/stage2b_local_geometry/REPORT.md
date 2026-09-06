# Stage 2B local trail geometry report

Stage 2B single-rule ablation — not an exact reproduction of Fig. 4.

## Direct verdict

- engineering gate: **PASS**
- mechanism-improvement gate: **FAIL**
- Fig. 4 candidate gate: **FAIL**
- hypothesis verdict: **opposes_local_geometry_hypothesis_for_this_fixed_seed**

The verdict is limited to one pre-registered fixed seed. It is not a multi-seed robustness claim and is not an exact-reproduction claim.

## Isolation and unique change

- branch: `codex/stage2b-local-trail-geometry`
- frozen baseline commit: `02a953af132a44aabcf8be92a873de7694d4a5fb`
- changed rule: `stored_cell_direction` -> `local_weighted_pca_tangent`
- behavioural configuration differences: 1 (only follower rule: True)
- default-rule full replay compatibility: True
- protected SHA-256: 75 before / 75 after; all match = True
- tests: 59 passed in 4.13s
- pilot stable: True

The PCA decision consumes only local active-cell centres, concentrations, and the ant's current heading. Food/nest coordinates are used only by evaluation metrics and existing event rules.

## Scientific interpretation

The local PCA rule made consecutive selected trail axes smoother (23.224° to 10.681°), but it did not align movement with the nest-food axis (43.011° to 43.148°). Late-window psi fell from 0.636443 to 0.505947, the sensing miss rate rose from 2.43% to 18.43%, and deliveries fell from 363 to 40.

Therefore, smoother local tangent choices were not sufficient to recover nest-food-axis order under the unchanged sensing radius, non-decaying field, and transporter geometry. This fixed-seed ablation opposes the stated local-geometry mechanism hypothesis in its pre-registered form.

## Complete baseline comparison

| metric | Stage 2A | Stage 2B | delta |
|---|---:|---:|---:|
| `final_phi` | -0.0325781527731633 | -0.28014900700324724 | -0.24757085423008393 |
| `final_psi` | 0.6400746980766642 | 0.48370219675724085 | -0.15637250131942332 |
| `late_window_mean_phi` | -0.042959492045807186 | -0.3111830658012562 | -0.26822357375544903 |
| `late_window_mean_psi` | 0.6364427983712712 | 0.5059466682881061 | -0.13049613008316507 |
| `follower_final_phi` | -0.1222553688878661 | -0.31873906013250614 | -0.19648369124464005 |
| `follower_final_psi` | 0.6767627910037167 | 0.4907626610602512 | -0.18600012994346554 |
| `follower_late_window_mean_phi` | -0.1689576648179753 | -0.3072979497877524 | -0.13834028496977707 |
| `follower_late_window_mean_psi` | 0.6507816200978576 | 0.5065835675501528 | -0.1441980525477048 |
| `transporter_final_phi` | 0.3497299790842538 | 0.03207960467893833 | -0.31765037440531546 |
| `transporter_final_psi` | 0.5936239840907911 | 0.4995512801337273 | -0.0940727039570638 |
| `transporter_late_window_mean_phi` | 0.42996082428847787 | -0.3424921819717057 | -0.7724530062601835 |
| `transporter_late_window_mean_psi` | 0.7259694704212352 | 0.5421075812288899 | -0.18386188919234525 |
| `follower_hit_step_mean_axis_error_deg` | 43.01063219158909 | 43.147964231973724 | 0.13733204038463498 |
| `follower_local_continuity_mean_axis_change_deg` | 23.22367918099151 | 10.680749273046919 | -12.542929907944592 |
| `follower_sensing_miss_rate` | 0.02426044896965592 | 0.184335989214038 | 0.16007554024438206 |
| `cumulative_deliveries` | 363 | 40 | -323.0 |
| `first_food_discovery_time` | 913 | 913 | 0.0 |
| `first_successful_delivery_time` | 1583 | 1583 | 0.0 |
| `first_pheromone_recruitment_time` | 1168 | 1168 | 0.0 |
| `active_pheromone_cells` | 102737 | 64598 | -38139.0 |
| `active_pheromone_area_fraction` | 0.410948 | 0.258392 | -0.15255599999999997 |
| `main_channel_width_90` | 190.070302782944 | 249.46727240261396 | 59.39696961966996 |
| `completed_transporter_mean_path_efficiency` | 0.6171177090980704 | 0.15982748485631448 | -0.4572902242417559 |
| `completed_transporter_median_path_efficiency` | 0.7812853602540692 | 0.10973813226197801 | -0.6715472279920912 |

- final F/T/f: baseline `{'foragers': 0, 'transporters': 19, 'followers': 81}`; Stage 2B `{'foragers': 0, 'transporters': 11, 'followers': 89}`

## Acceptance details

### engineering

Overall: **PASS**

- all_tests_passed: True
- default_rule_full_replay_matches_frozen_stage2a: True
- configured_horizon_completed: True
- population_conserved: True
- finite_metrics: True
- finite_positions: True
- positions_within_bounds: True
- fixed_seed_reproducibility_test_passed: True
- protected_sha256_all_match: True
- only_follower_direction_rule_changed: True

### mechanism_improvement

Overall: **FAIL**

- late_window_psi_improvement_at_least_0_10: False
- follower_hit_step_mean_axis_error_at_most_35_deg: False
- deliveries_at_least_291: False
- no_food_or_nest_global_coordinate_dependency: True

### fig4_candidate

Overall: **FAIL**

- late_window_mean_psi_at_least_0_90: False
- late_window_mean_phi_within_0_15_rad_of_pi_over_4: False
- transport_and_role_cycle_not_collapsed: True

## Runtime and resources

- baseline default-rule replay: 95.031 s
- pilot simulation: 0.862 s
- paper-scale Stage 2B simulation: 147.111 s
- analysis and figures: 4.275 s
- total before final report: 252.096 s
- Mac CPU only; no GPU or AutoDL

## Scientific limitations

- This is one fixed seed and cannot establish robustness or uncertainty.
- PCA can use only anisotropy visible inside the unchanged sensing radius.
- The broad non-decaying historical field and transporter route remain unchanged upstream causes.
- Passing engineering checks does not establish the original unpublished rule.
- Even a candidate-gate pass would permit only the wording `fixed-seed Fig. 4-like candidate`.

## Awaiting professor confirmation

The original local follower inference, pheromone representation, equal-concentration handling, transporter memory/interpolation, coordinates/radii, initialisation, event timing, seed, and metric sampling remain unresolved.

No second rule was changed. No parameter scan, alternate seed, multi-seed validation, Stage 3, optimisation, or LLM experiment was run.

Stage 2B single-rule ablation — not an exact reproduction of Fig. 4.

# Stage 4 objective amendment: zero pre-relocation retrieval

Status: **accepted by master before any Stage 4 campaign, candidate evaluation, or external LLM call**. This document freezes the only change to Proposal Equation (2).

## Reason and rule

The original threshold is `0.8 * R_pre`. When `R_pre=0`, the threshold is zero, so even a replicate with no post-relocation retrieval satisfies it at the first eligible time, 600 steps after relocation. That is a zero-baseline degeneracy, not biological retrieval recovery.

**Amendment:** if a replicate has `R_pre=0`, record `non_recovery=true` and `tau_rec=T_post=12000`. All other replicates retain Equation (2) exactly. This rule applies identically to Random Search, TPE, LLM, every candidate, and every seed. It will not be changed in response to search results.

## Frozen discrete-time interpretation

The simulation has integer steps `0..17999`, relocation at `t_r=6000`, and `T_post=12000`. Only ledger records with `event="delivery"` count: pickup, discovery, and ant state do not. A source A delivery at integer time `d` contributes to the final 20% pre-relocation reference interval exactly when `4800 <= d < 6000`. Thus `R_pre = count_A / 1200` and zero means precisely `count_A=0`.

The post-relocation trailing window has width `w=600`. At integer `s`, its B-delivery count includes exactly `s-600 < d <= s`; its rate is this count divided by 600. A candidate recovery start `t` qualifies when the trailing rate is at least `0.8*R_pre` at **every integer** `s` in the inclusive range `[t,t+600]`. Starts are inspected in ascending order from `6600` to `17400`, inclusive; the last persistence check is at `18000`. The returned `tau_rec` is `t-6000`. If no start qualifies, return `tau_rec=12000` and `non_recovery=true`. The same representation is used for `R_pre=0`; a capped `tau_rec=12000` always carries the explicit non-recovery flag. The minimum possible recovery time is 600.

This is an endpoint amendment for the future Stage 4 benchmark. Retrospective evaluation of Stage 3C/3D events is an endpoint viability audit only; it does not revise their frozen scientific decisions.

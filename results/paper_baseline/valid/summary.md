# Five static checks: step `valid`

Medians over seeds. Each check cell: ✓/✗ = condition-level pass (median meets it and ≥ 80% of seeds meet it), followed by the number of seeds meeting it.

| condition | n | 1 first pickup | 2 recruit | 3 trail | 4 deliveries / R² | ψ | φ | foragers | ψ − ψ_off | checks passed (1,2,3,4,5full,5basic) | tier |
|---|---|---|---|---|---|---|---|---|---|---|---|
| a600 | 20 | 894 | 1.00 | 0.64 | 716 / 1.00 | 0.726 | 0.324 | 55 | 0.085 | ✓18 ✓20 ✓20 ✓19 ✗0 ✗0 | — |
| a600_off | 20 | 894 | 0.00 | 0.00 | 2 / 0.66 | 0.640 | -0.001 | 100 | nan | ✓18 ✗0 ✗0 ✗0 ✗0 ✗0 | — |
| base | 20 | 894 | 1.00 | 0.63 | 1684 / 1.00 | 0.940 | 0.704 | 6 | 0.300 | ✓20 ✓20 ✓20 ✓20 ✗14 ✗15 | — |
| base_off | 20 | 894 | 0.00 | 0.00 | 5 / 0.87 | 0.641 | 0.002 | 100 | nan | ✓20 ✗0 ✗0 ✗0 ✗0 ✗0 | — |
| paperlayout | 20 | 3166 | 1.00 | 0.63 | 768 / 1.00 | 0.969 | 0.747 | 2 | 0.328 | ✗13 ✓20 ✓20 ✓20 ✓20 ✓20 | — |
| paperlayout_off | 20 | 3166 | 0.00 | 0.00 | 5 / 0.83 | 0.641 | 0.005 | 100 | nan | ✗13 ✗0 ✗0 ✗0 ✗0 ✗0 | — |
| zw | 20 | 948 | 1.00 | 0.63 | 1717 / 1.00 | 0.948 | 0.715 | 5 | 0.308 | ✓18 ✓20 ✓20 ✓20 ✓16 ✓16 | FULL |
| zw_off | 20 | 948 | 0.00 | 0.00 | 6 / 0.87 | 0.640 | 0.002 | 100 | nan | ✓18 ✗0 ✗0 ✗0 ✗0 ✗0 | — |


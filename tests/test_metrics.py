from __future__ import annotations

import numpy as np

from ant_walks.metrics import cumulative_visited_sites, visited_cell_indices


def test_coverage_grid_is_centred_on_origin_and_counts_once() -> None:
    positions = np.array(
        [
            [0.0, 0.0],
            [0.49, 0.49],
            [0.51, 0.49],
            [1.51, 0.49],
            [0.49, 0.49],
        ]
    )
    cells = visited_cell_indices(positions, cell_size=1.0)
    np.testing.assert_array_equal(cells[0], [0, 0])
    np.testing.assert_array_equal(cumulative_visited_sites(positions, 1.0), [1, 1, 2, 3, 3])

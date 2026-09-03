"""Values two or more EXPLORATION panel modules need.

Not a utils/helpers grab-bag: everything here is layout-time (a
dropdown's `options=`, an empty-book guard's message), needed by more
than one panel module, and small enough that a single shared home beats
either duplicating the literal or inventing a false single-panel owner
for it. Imports nothing from ``design/`` — if this ever grows past a
handful of names, that is a signal a panel seam is wrong, not that this
module needs sections.

``_METRIC_OPTIONS`` is the ``spot_vol``/``time_price`` metric dropdowns'
shared option list. ``_EXPLORATION_EMPTY_BOOK_MSG`` is the message every
EXPLORATION panel but ``vega_term`` shows on an empty book — needed
inside each panel's own ``_render_*_panel_logic``, so it cannot be
supplied by composition the way a layout-time value can.
"""

from __future__ import annotations

from deltadewa.visualization.stress_charts_plotly import STRESS_METRICS

_METRIC_OPTIONS = [
    {"label": spec.label, "value": key} for key, spec in STRESS_METRICS.items()
]

_EXPLORATION_EMPTY_BOOK_MSG = (
    "Add a position in the BOOK zone to explore stress scenarios."
)

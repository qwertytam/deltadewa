"""The `/design` page's public surface: unchanged by the #308 split.

`deltadewa.app.pages.design` used to be a single 3,812-line module;
#308 splits its contents across this package (`page.py` plus per-panel
modules under `book.py`, `planning/`, and `exploration/`). Two consumers
constrain what stays visible at exactly this path:
`deltadewa.app.factory` imports `render` and `register_callbacks`, and
`tests/test_app/test_design.py` reaches 29 private `_..._logic`/helper
names as `design._name` attribute lookups. Every name below is
re-exported for that reason alone — not because it is meant as public
API. The redundant `as`-alias form is required so mypy's
`no_implicit_reexport` (implied by `strict = true`) treats each import
as an intentional re-export rather than an unused one.
"""

# pylint: disable=useless-import-alias
# Every `name as name` below is the mypy re-export idiom the docstring
# above describes, not an accidental redundant alias — pylint's C0414
# has no way to tell the two apart, so this file (and only this file)
# disables the check rather than silencing it 26 times inline.

from .book import _add_position_logic as _add_position_logic
from .book import _export_logic as _export_logic
from .book import _import_logic as _import_logic
from .book import _mark_inputs_reviewed_logic as _mark_inputs_reviewed_logic
from .book import _net_delta_readout as _net_delta_readout
from .book import _remove_position_logic as _remove_position_logic
from .book import _set_spot_price_logic as _set_spot_price_logic
from .book import (
    _set_underlying_quantity_logic as _set_underlying_quantity_logic,
)
from .book import (
    _total_underlying_value_readout as _total_underlying_value_readout,
)
from .exploration.monte_carlo import (
    _render_mc_panel_logic as _render_mc_panel_logic,
)
from .exploration.spot_vol import (
    _render_spot_vol_panel_logic as _render_spot_vol_panel_logic,
)
from .exploration.time_price import (
    _render_time_price_panel_logic as _render_time_price_panel_logic,
)
from .exploration.vega_term import (
    _render_vega_term_panel_logic as _render_vega_term_panel_logic,
)
from .exploration.volatility_profile import (
    _render_volatility_profile_panel_logic as _render_volatility_profile_panel_logic,  # ruff: ignore[line-too-long]
)
from .page import _BASIS_CRASH_SKEW as _BASIS_CRASH_SKEW
from .page import register_callbacks as register_callbacks
from .page import render as render
from .planning.convexity_cliff import (
    _render_convexity_cliff_panel_logic as _render_convexity_cliff_panel_logic,
)
from .planning.delta_drift import (
    _render_delta_drift_panel_logic as _render_delta_drift_panel_logic,
)
from .planning.hedge_triggers import (
    _render_hedge_triggers_panel_logic as _render_hedge_triggers_panel_logic,
)
from .planning.ladder import _ladder_maturities_text as _ladder_maturities_text
from .planning.ladder import (
    _render_ladder_panel_logic as _render_ladder_panel_logic,
)
from .planning.ladder import _sort_rungs as _sort_rungs
from .planning.ladder import _toggle_sort_state as _toggle_sort_state
from .planning.market_env import (
    _render_market_env_panel_logic as _render_market_env_panel_logic,
)
from .planning.monetization import (
    _render_monetization_panel_logic as _render_monetization_panel_logic,
)
from .planning.position_aging import _aging_calendar_row as _aging_calendar_row
from .planning.position_aging import _expiry_window_text as _expiry_window_text
from .planning.position_aging import (
    _render_position_aging_panel_logic as _render_position_aging_panel_logic,
)
from .planning.roll_plan import (
    _render_roll_plan_panel_logic as _render_roll_plan_panel_logic,
)
from .planning.roll_plan import _roll_plan_row as _roll_plan_row
from .planning.roll_status import (
    _render_roll_panel_logic as _render_roll_panel_logic,
)
from .planning.sizing import (
    _render_sizing_panel_logic as _render_sizing_panel_logic,
)

"""Guards on the shipped example configs (#249).

``examples/ips/ips_default.yaml`` shipped a byte-for-byte copy of this
program's live ``config/ips.yaml`` — real program name, carry budget,
convexity targets and roll/drift triggers — in a public repo until #249.
It was not written as an example; it was seeded from the real file and
then kept in sync with it as policy changed.

The fix was to give it the *same* placeholder numbers as
``config/ips.example.yaml``, so the repo carries one set of example policy
values rather than two that can drift back together. These tests pin that:
re-syncing the example against a real policy file breaks them.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from deltadewa.ips_config import load_ips_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLE_PRESET = _REPO_ROOT / "examples" / "ips" / "ips_default.yaml"
_CANONICAL_TEMPLATE = _REPO_ROOT / "config" / "ips.example.yaml"


def _load_raw(path: Path) -> dict[str, Any]:
    """Parse a YAML config to a plain dict, comments discarded."""
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return dict(loaded)


class TestIpsDefaultPreset:
    """``examples/ips/ips_default.yaml`` is example data, not policy."""

    def test_loads_as_a_valid_ips_config(self) -> None:
        """The preset is a complete, loadable file, not a fragment.

        It is documented as something an operator may copy over
        ``config/ips.yaml``, so it has to satisfy the same validation the
        real file does — including the fields the loader requires outright
        rather than defaulting.
        """
        config = load_ips_config(_EXAMPLE_PRESET)

        assert config.program.instrument == "SPX"

    def test_values_match_the_canonical_example_template(self) -> None:
        """One set of example numbers in the repo, not two (#249).

        The two files differ only in their header prose. If this fails
        because someone edited one of them, edit the other to match —
        do NOT resolve it by copying values out of a live
        ``config/ips.yaml``, which is the leak #249 closed.
        """
        preset = _load_raw(_EXAMPLE_PRESET)
        template = _load_raw(_CANONICAL_TEMPLATE)

        assert preset == template

    def test_program_name_is_visibly_an_example(self) -> None:
        """The real program name must not reappear here.

        ``program.name`` is the single most identifying field in the file
        and the one #249 called out first, so it gets its own guard rather
        than relying on the whole-file comparison above.
        """
        name = _load_raw(_EXAMPLE_PRESET)["program"]["name"]

        assert "example" in name.lower()
        assert "personal" not in name.lower()

    @pytest.mark.parametrize(
        ("section", "field", "leaked_value"),
        [
            ("convexity", "crash_scenario_pct", -25.0),
            ("convexity", "target_min_pct", 15.0),
            ("convexity", "target_max_pct", 25.0),
            ("triggers", "delta_drift_warn_pct", 5.0),
            ("triggers", "delta_drift_action_pct", 10.0),
            ("triggers", "theta_cost_acceptable_pct", 2.0),
            ("triggers", "roll_time_months", 9.0),
            ("triggers", "rally_rebalance_pct", 15.0),
            ("triggers", "strike_drift_max_otm_pct", 45.0),
        ],
    )
    def test_no_leaked_pre_245_policy_value(
        self,
        section: str,
        field: str,
        leaked_value: float,
    ) -> None:
        """None of the specific values #249 enumerated survive here.

        These are the pre-#245 real ``config/ips.yaml`` numbers quoted in
        the issue. Several are also `handbook
        <https://github.com/qwertytam/deltadewa-handbook>`_ defaults (the
        handbook's own roll-at-9-months and 45%-OTM lines, and the
        methodology's -25% crash), so any one of them alone is unremarkable
        — it is the whole
        file matching that identified the program. They are pinned
        individually anyway, because a partial re-sync is the realistic
        regression, not a wholesale file copy.
        """
        preset = _load_raw(_EXAMPLE_PRESET)

        assert preset[section][field] != leaked_value

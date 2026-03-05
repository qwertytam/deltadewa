"""Monte Carlo staleness check and re-run widget for the options dashboard."""

from __future__ import annotations

import datetime
from datetime import datetime as dt
from typing import TYPE_CHECKING

import ipywidgets as widgets  # type: ignore[import-untyped]
from IPython.display import display

from deltadewa.reporting import ConsoleReporter

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class MonteCarloStalenessWidget:
    """Check if MC results are stale and prompt for re-run if needed."""

    def __init__(
        self,
        portfolio: OptionPortfolio,
        num_simulations: int,
        include_underlying: bool,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize the widget with portfolio and MC parameters."""
        self.portfolio = portfolio
        self._num_simulations = num_simulations
        self._include_underlying = include_underlying
        self._reporter = reporter or ConsoleReporter()

    def check_and_warn(self) -> bool:
        """Display the stale-MC warning widget if results are stale.

        Returns:
            bool: True if the widget was displayed (MC is stale), False
            otherwise.

        """
        # Determine staleness from multiple signals:
        # - explicit `monte_carlo_stale` flag
        # - missing/None `_monte_carlo_results`
        # - missing `timestamp` in results
        # - timestamp older than threshold
        is_stale = False
        stale_reason = "unknown reason"

        # 1) explicit stale flag
        if getattr(self.portfolio, "monte_carlo_stale", False):
            is_stale = True
            stale_reason = "explicit flag"

        # 2) missing results -> consider stale
        results = getattr(self.portfolio, "_monte_carlo_results", None)
        if results is None and not is_stale:
            is_stale = True
            stale_reason = "missing results"

        # 3) prefer explicit portfolio timestamp, but fall back to any
        # `timestamp` embedded in the results dict. Only consider missing
        # timestamp stale if neither exists.
        ts = getattr(self.portfolio, "monte_carlo_timestamp", None)
        if ts is None and results is not None:
            # results may include a timestamp key (tests set this), so use it
            ts = results.get("timestamp")

        if ts is None and not is_stale:
            is_stale = True
            stale_reason = "missing timestamp"

        # 4) timestamp too old -> consider stale
        if ts and not is_stale:
            try:
                now = dt.now(tz=datetime.UTC)
                # threshold (hours) — keep in sync with tests which use 1 hour
                threshold = datetime.timedelta(hours=1)
                if now - ts > threshold:
                    is_stale = True
                    stale_reason = "timestamp too old"
            except Exception:  # pylint: disable=broad-except
                is_stale = True
                stale_reason = "timestamp parsing error"

        if is_stale:
            last_modified = getattr(
                self.portfolio, "monte_carlo_last_modified", None
            )
            if last_modified:
                last_modified_str = last_modified.strftime("%H:%M:%S")
            else:
                last_modified_str = "Unknown"

            warning_widget = widgets.HTML(
                value=f"""
                <div style="
                    background-color: #ff6b6b;
                    color: white;
                    padding: 20px;
                    border-radius: 8px;
                    border-left: 6px solid #c92a2a;
                    margin: 15px 0;
                    box-shadow: 0 3px 6px rgba(0,0,0,0.16);
                ">
                    <h3 style="margin: 0 0 10px 0; font-size: 18px;">
                    ⚠️  STALE MONTE CARLO RESULTS</h3>
                    <p style="margin: 5px 0; font-size: 14px;">
                        <strong>Portfolio has been modified since Monte Carlo
                        simulation ran.
                        </strong><br>
                        Last modified: {last_modified_str} ({stale_reason})
                    </p>
                    <p style="margin: 10px 0 0 0; font-size: 13px; opacity: 0.95;">
                        → Results below may not reflect your current portfolio<br>
                        → Re-run the Monte Carlo cell in MODE 0 or click the button
                        below
                    </p>
                </div>
                """,
            )

            rerun_button = widgets.Button(
                description="🔄 Re-run Monte Carlo Now",
                button_style="warning",
                layout=widgets.Layout(width="250px", height="45px"),
                style={"button_color": "#f59f00", "font_weight": "bold"},
            )

            output_area = widgets.Output()

            def on_rerun_click(b) -> None:  # noqa: ANN001
                with output_area:
                    output_area.clear_output()
                    b.description = "Running..."
                    b.disabled = True
                    try:
                        print(
                            f"Re-running Monte Carlo with {self._num_simulations:,}"
                            f" simulations...",
                        )
                        mc_results = self.portfolio.run_monte_carlo_simulation(
                            num_simulations=self._num_simulations,
                            include_underlying=self._include_underlying,
                        )
                        self.portfolio.monte_carlo_stale = False
                        self.portfolio.monte_carlo_timestamp = dt.now(
                            tz=datetime.UTC
                        )
                        self._reporter.success(
                            f"✓ Monte Carlo re-run complete! "
                            f"{mc_results['num_simulations']:,} scenarios",
                        )
                        print("\n💡 Scroll down to see updated results")
                        b.description = "✓ Complete - Refresh Results"
                        b.button_style = "success"
                    except Exception as e:  # pylint: disable=broad-except
                        self._reporter.error(
                            f"Error re-running Monte Carlo: {e}"
                        )
                        b.description = "❌ Error - Try Again"
                        b.button_style = "danger"
                        b.disabled = False

            rerun_button.on_click(on_rerun_click)
            display(widgets.VBox([warning_widget, rerun_button, output_area]))
            return True

        return False

"""Position Detail Table display for the deltadewa options dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pandas as pd
from IPython.display import display

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


def _fmt_enum_val(v) -> str:  # noqa: ANN001
    if hasattr(v, "name"):
        return v.name.capitalize()
    s = str(v)
    if "." in s:
        return s.rsplit(".", maxsplit=1)[-1].capitalize()
    return str(s).capitalize()


class PositionDetailDisplay:
    """Build and display the position detail table."""

    def __init__(self, portfolio: OptionPortfolio) -> None:
        """Initialize with the portfolio to display."""
        self._portfolio = portfolio

    def display(self) -> None:
        """Build and display the styled position detail table."""
        # Position Detail Table

        df_positions = self._portfolio.to_dataframe()

        if not df_positions.empty:
            # Create a copy for display with title case column names
            display_df = df_positions.copy()

            # Make the index 1-based for user-friendly display
            display_df.index = pd.Index(range(1, len(display_df) + 1))

            # Calculate days to maturity
            display_df["days_to_maturity"] = display_df["maturity"].apply(
                lambda x: (pd.to_datetime(x) - pd.Timestamp.now()).days,
            )

            # Normalize option `type` and `exercise_style` for user-friendly
            # display
            if "option_type" in display_df.columns:
                display_df["option_type"] = display_df["option_type"].apply(
                    _fmt_enum_val,
                )

            if "exercise_style" in display_df.columns:
                display_df["exercise_style"] = display_df["exercise_style"].apply(
                    _fmt_enum_val,
                )

            # Drop contract_size column if it exists
            if "contract_size" in display_df.columns:
                display_df = display_df.drop(columns=["contract_size"])

            # Drop custom_volatility column if it exists (internal field)
            if "custom_volatility" in display_df.columns:
                display_df = display_df.drop(columns=["custom_volatility"])

            # Reorder columns to put days_to_maturity after maturity
            cols = list(display_df.columns)
            if "maturity" in cols and "days_to_maturity" in cols:
                maturity_idx = cols.index("maturity")
                cols.remove("days_to_maturity")
                cols.insert(maturity_idx + 1, "days_to_maturity")
                display_df = display_df[cols]

            # Rename columns to title case with better formatting
            column_renames = {
                "symbol": "Symbol",
                "option_type": "Type",
                "strike": "Strike",
                "maturity": "Maturity",
                "days_to_maturity": "Days to Maturity",
                "quantity": "Quantity",
                "price": "Price",
                "volatility": "Volatility",
                "position_value": "Position Value",
                "delta": "Delta",
                "gamma": "Gamma",
                "vega": "Vega",
                "theta": "Theta",
                "rho": "Rho",
                "position_delta": "Position Delta",
                "position_gamma": "Position Gamma",
                "position_vega": "Position Vega",
                "position_theta": "Position Theta",
                "position_rho": "Position Rho",
                "exercise_style": "Exercise Style",
            }
            display_df = display_df.rename(columns=column_renames)

            # Define format specifications with explicit, typed formatter
            # functions so static type checkers (mypy) accept the mapping type.
            format_dict: dict[str, str | Callable[[object], str] | None] = {}

            def _fmt_currency(x: Any) -> str:  # noqa: ANN401
                try:
                    return f"${float(x):,.2f}"
                except Exception:  # pylint: disable=broad-except
                    return str(x)

            def _fmt_pct(x: Any) -> str:  # noqa: ANN401
                try:
                    return f"{float(x):.1%}"
                except Exception:  # pylint: disable=broad-except
                    return str(x)

            def _fmt_int(x: Any) -> str:  # noqa: ANN401
                try:
                    return f"{int(x):.0f}"
                except Exception:  # pylint: disable=broad-except
                    return str(x)

            def _fmt_greek(x: Any) -> str:  # noqa: ANN401
                try:
                    return f"{float(x):.5g}"
                except Exception:  # pylint: disable=broad-except
                    return str(x)

            # Currency columns
            currency_cols = [
                "Strike",
                "Price",
                "Position Value",
                "Theta",
                "Position Theta",
            ]
            for col in currency_cols:
                if col in display_df.columns:
                    format_dict[col] = _fmt_currency

            # Percentage columns
            if "Volatility" in display_df.columns:
                format_dict["Volatility"] = _fmt_pct

            # Integer columns
            int_cols = ["Quantity", "Days to Maturity"]
            for col in int_cols:
                if col in display_df.columns:
                    format_dict[col] = _fmt_int

            # Greeks with 5 significant figures (using .5g format)
            greek_cols = [
                "Delta",
                "Gamma",
                "Vega",
                "Rho",
                "Position Delta",
                "Position Gamma",
                "Position Vega",
                "Position Rho",
            ]
            for col in greek_cols:
                if col in display_df.columns:
                    format_dict[col] = _fmt_greek

            # Apply styling
            styled_df = display_df.style.format(format_dict)

            # Add table styles for better appearance
            styled_df = styled_df.set_table_styles(
                [
                    {
                        "selector": "th",
                        "props": [
                            ("background-color", DEFAULT_PALETTE.dark_background),
                            ("color", DEFAULT_PALETTE.white),
                            ("padding", "8px"),
                            ("text-align", "center"),
                            ("white-space", "nowrap"),
                        ],
                    },
                    {
                        "selector": "td",
                        "props": [("padding", "6px"), ("text-align", "right")],
                    },
                    # Ensure Maturity column doesn't wrap
                    {
                        "selector": "td:nth-child(5)",
                        "props": [("min-width", "80px"), ("white-space", "nowrap")],
                    },
                ],
            )

            # Also apply no-wrap to Maturity column specifically
            if "Maturity" in display_df.columns:
                _maturity_col_idx = list(display_df.columns).index("Maturity")
                styled_df = styled_df.set_properties(
                    subset=["Maturity"],
                    **{"white-space": "nowrap", "min-width": "100px"},
                )

            display(styled_df)
        else:
            print("No positions in portfolio yet.")

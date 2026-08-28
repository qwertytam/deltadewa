"""Portfolio persistence module for import/export operations.

This module provides utilities for saving and loading portfolio state
in multiple formats (JSON, CSV, YAML).
"""

import datetime
import json
from datetime import datetime as dt
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from deltadewa.clock import program_trading_date
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.stamps import MarketParameterStamps
from deltadewa.reporting import PortfolioLogger

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def _stamps_from_market_params(
    market_params: dict[str, Any],
) -> MarketParameterStamps:
    """Restore ``MarketParameterStamps`` from a parsed ``market_parameters``.

    A file predating #367 carries none of the three ``*_as_of`` keys;
    ``.get`` returning ``None`` for each is correct here, not a fallback —
    those inputs were never confirmed under this feature, so they must
    report ``None`` (later graded ``Freshness.UNKNOWN``), not "now".
    """
    return MarketParameterStamps(
        spot_as_of=(
            dt.fromisoformat(raw)
            if (raw := market_params.get("spot_as_of"))
            else None
        ),
        risk_free_rate_as_of=(
            dt.fromisoformat(raw)
            if (raw := market_params.get("risk_free_rate_as_of"))
            else None
        ),
        dividend_yield_as_of=(
            dt.fromisoformat(raw)
            if (raw := market_params.get("dividend_yield_as_of"))
            else None
        ),
    )


class PortfolioSerializer:
    """Handle portfolio export/import in multiple formats."""

    def __init__(
        self,
        export_dir: str | Path,
        examples_dir: str | Path | None = None,
        *,
        writer_label: str = "app",
    ) -> None:
        """Initialize the serializer.

        Args:
            export_dir: Directory path for exports (str or Path). If None, must
            be set later.
            examples_dir: Directory path for example portfolios (str or Path)
            If None, must be set later.
            writer_label: Identifies which process wrote a given export, in
                its ``metadata.written_by`` field (#355) — e.g. ``"app"``
                for the live worker, ``"import_portfolio_cli"`` for the
                importer. Never derived from ``sys.argv``: ``exports/`` is
                pushed to an offsite git remote nightly, and a raw command
                line is exactly the kind of operational value that must not
                land in a backed-up artifact.

        """
        self.export_dir = Path(export_dir)
        self.writer_label = writer_label
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # If creation fails, keep the path but it won't exist
            print(f"Export directory creation failed. {e}")

        self.examples_dir = (
            Path(examples_dir) if examples_dir is not None else None
        )
        if self.examples_dir is not None:
            self.examples_dir.mkdir(parents=True, exist_ok=True)

    # ========== Helper Functions ==========

    def list_available_files(self, d: Path) -> dict[str, list[Path]]:
        """List all available portfolio files in the given directory.

        Returns:
            dict with 'json' and 'yaml' keys containing lists of file paths

        """
        json_files = sorted(
            d.glob("*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        yaml_files = sorted(
            d.glob("*.yaml"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        yaml_files.extend(
            sorted(
                d.glob("*.yml"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            ),
        )
        return {"json": json_files, "yaml": yaml_files}

    @staticmethod
    def detect_file_format(filepath: str | Path) -> str | None:
        """Detect portfolio file format from extension.

        Args:
            filepath: Path to file

        Returns:
            str: 'yaml', 'json', or None if unsupported

        """
        suffix = Path(filepath).suffix.lower()
        if suffix in [".yaml", ".yml"]:
            return "yaml"
        if suffix == ".json":
            return "json"
        return None

    # ========== Export Functions ==========

    def _build_export_data(
        self,
        portfolio: OptionPortfolio,
        changelog: PortfolioLogger,
    ) -> dict[str, Any]:
        """Build a comprehensive data structure.

        Build a comprehensive data structure representing the portfolio state,
        including market parameters, positions, and risk metrics.

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
        Returns:
            dict with complete portfolio data for export

        """
        data: dict[str, Any] = {
            "metadata": {
                "exported_at": dt.now(tz=datetime.UTC).isoformat(),
                "version": "1.0",
                "written_by": self.writer_label,
            },
            "market_parameters": {
                "spot_price": portfolio.spot_price,
                "volatility": portfolio.volatility,
                "risk_free_rate": portfolio.risk_free_rate,
                "dividend_yield": portfolio.dividend_yield,
                "underlying_quantity": portfolio.underlying_quantity,
                "symbol": portfolio.get_symbol(),
                "contract_size": portfolio.contract_size,
                # #367: when each hand-entered book-level input was last
                # confirmed. None (rather than the export instant) for a
                # value never explicitly (re-)confirmed — see
                # deltadewa.portfolio.stamps.
                "spot_as_of": (
                    portfolio.stamps.spot_as_of.isoformat()
                    if portfolio.stamps.spot_as_of
                    else None
                ),
                "risk_free_rate_as_of": (
                    portfolio.stamps.risk_free_rate_as_of.isoformat()
                    if portfolio.stamps.risk_free_rate_as_of
                    else None
                ),
                "dividend_yield_as_of": (
                    portfolio.stamps.dividend_yield_as_of.isoformat()
                    if portfolio.stamps.dividend_yield_as_of
                    else None
                ),
            },
            "positions": [],
            "risk_metrics": portfolio.summary_stats(),
            "session_changelog": [],
        }

        for pos in portfolio.positions:
            position_data = {
                "position_id": pos.position_id,
                "option_type": pos.option.option_type.value,
                "strike_price": pos.option.strike_price,
                "maturity_date": pos.option.maturity_date.isoformat(),
                "quantity": pos.quantity,
                "contract_size": pos.contract_size,
                "exercise_style": pos.exercise_style.value,
                "volatility": pos.option.volatility,
                "custom_volatility": pos.custom_volatility,
                "volatility_as_of": (
                    pos.volatility_as_of.isoformat()
                    if pos.volatility_as_of
                    else None
                ),
                "greeks": {
                    "delta": pos.option.delta(),
                    "gamma": pos.option.gamma(),
                    "theta": pos.option.theta(),
                    "vega": pos.option.vega(),
                    "rho": pos.option.rho(),
                },
                "price": pos.option.price(),
                "position_value": pos.option.price()
                * pos.quantity
                * pos.contract_size,
                "entry_spot": pos.entry_spot,
                "entry_date": (
                    pos.entry_date.isoformat() if pos.entry_date else None
                ),
                "entry_premium": pos.entry_premium,
            }
            data["positions"].append(position_data)

        for entry in changelog.get_all_portfolio_snapshots():
            data["session_changelog"].append(
                {
                    "timestamp": entry["timestamp"].isoformat(),
                    "action": entry["action"].value,
                    "details": entry["details"],
                    "impact_delta": entry["impact_delta"],
                    "impact_cost": entry["impact_cost"],
                    "portfolio_snapshot": entry["portfolio_snapshot"],
                },
            )

        return data

    def export_to_json(
        self,
        portfolio: OptionPortfolio,
        changelog: PortfolioLogger,
        filename: str = "portfolio_book.json",
    ) -> Path:
        """Export complete portfolio state to JSON format.

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
            filename: output filename

        Returns:
            Path to saved file

        """
        portfolio_data = self._build_export_data(portfolio, changelog)

        # Write to a temp file and rename onto the destination, so a
        # concurrent reader (or a crash mid-write) never observes a
        # truncated file.
        output_path = self.export_dir / filename
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(portfolio_data, f, indent=2)
            tmp_path.replace(output_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        return output_path

    def export_to_csv(
        self,
        portfolio: OptionPortfolio,
        changelog: PortfolioLogger,
        filename: str = "portfolio.csv",
    ) -> dict[str, Path]:
        """Export portfolio to CSV files (positions and risk).

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
            filename: output filename

        Returns:
            dict with paths to saved files

        Note:
            No caller since #279 retired the Jupyter export controls. The
            live export path is ``export_to_json`` / ``import_from_json``
            (see ``state.py``); this is kept as a tested serializer with an
            obvious future "export" consumer on the Dash side.

        """
        filename_prefix = Path(filename).stem

        # Export positions
        positions_data = []
        for i, pos in enumerate(portfolio.positions):
            positions_data.append(
                {
                    "position_id": i,
                    "option_type": pos.option.option_type.value,
                    "strike": pos.option.strike_price,
                    "maturity": pos.option.maturity_date.isoformat(),
                    "quantity": pos.quantity,
                    "contract_size": pos.contract_size,
                    "volatility": pos.option.volatility,
                    "custom_volatility": pos.custom_volatility,
                    "price": pos.option.price(),
                    "value": pos.option.price()
                    * pos.quantity
                    * pos.contract_size,
                    "delta": pos.option.delta(),
                    "gamma": pos.option.gamma(),
                    "theta": pos.option.theta(),
                    "vega": pos.option.vega(),
                    "rho": pos.option.rho(),
                    "position_delta": pos.position_delta(),
                    "position_gamma": pos.position_gamma(),
                    "position_theta": pos.position_theta(),
                    "position_vega": pos.position_vega(),
                },
            )

        changelog_df = pd.DataFrame(
            [
                {
                    "timestamp": entry["timestamp"].isoformat(),
                    "action": entry["action"],
                    "details": entry["details"],
                    "impact_delta": entry["impact_delta"],
                    "impact_cost": entry["impact_cost"],
                    "resulting_positions": entry["portfolio_snapshot"][
                        "total_positions"
                    ],
                    "resulting_net_delta": entry["portfolio_snapshot"][
                        "net_delta"
                    ],
                }
                for entry in changelog.get_all_portfolio_snapshots()
            ],
        )

        df_positions_export = pd.DataFrame(positions_data)
        positions_file = self.export_dir / f"{filename_prefix}_positions.csv"
        df_positions_export.to_csv(positions_file, index=False)

        # Export risk metrics
        risk_stats = portfolio.summary_stats()
        risk_data = []
        for metric, value in risk_stats.items():
            risk_data.append({"metric": metric, "value": value})

        df_risk = pd.DataFrame(risk_data)
        risk_file = self.export_dir / f"{filename_prefix}_risk.csv"
        df_risk.to_csv(risk_file, index=False)

        changelog_path = self.export_dir / f"{filename_prefix}_changelog.csv"
        changelog_df.to_csv(changelog_path, index=False)

        return {"positions": positions_file, "risk": risk_file}

    def export_to_yaml(
        self,
        portfolio: OptionPortfolio,
        changelog: PortfolioLogger,
        filename: str = "portfolio_export.yaml",
    ) -> Path | None:
        """Export portfolio configuration to YAML format.

        The saved structure contains 'market_parameters' and a list of
        'positions' with option_type, strike_price, maturity_date (ISO
        YYYY-MM-DD), quantity and symbol.

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
            filename: output filename

        Note:
            No caller since #279 retired the Jupyter export controls; kept
            alongside ``export_to_csv`` for the same reason.

        Returns:
            Path to saved file, or None if YAML not available

        """
        if not YAML_AVAILABLE:
            print("⚠️  PyYAML not installed. Cannot export to YAML.")
            return None

        portfolio_data = self._build_export_data(portfolio, changelog)

        output_path = self.export_dir / filename
        with Path.open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(
                portfolio_data,
                f,
                default_flow_style=False,
                sort_keys=False,
            )

        return Path(output_path)

    # ========== Import Functions ==========

    def import_from_json(
        self,
        filepath: str | Path,
        create_portfolio: bool = True,
        default_exercise_style: ExerciseStyle | None = None,
        valuation_date: dt | None = None,
    ) -> dict[str, Any]:
        """Import portfolio from JSON file.

        Args:
            filepath: path to JSON file
            create_portfolio: if True, creates and returns portfolio object
            default_exercise_style: exercise style applied to positions whose
            entry has no explicit ``exercise_style`` (e.g. files predating
            exercise-style serialization).  Callers should pass the program's
            IPS style (``ips_config.pricing.exercise_style``). When None,
            the portfolio will have default_exercise_style=None and
            add_position() will raise ValueError for positions without an
            explicit style.
            valuation_date: as-of date for the load, mirroring
            ``import_from_yaml``.  Callers holding an ``IpsConfig`` should
            pass the program's trading date so the book is priced against
            the market's day rather than the server's (#182).  Defaults to
            the program trading date in the default timezone.

        Returns:
            dict with portfolio data (and 'portfolio' key if
            create_portfolio=True)

        """
        with Path.open(Path(filepath), encoding="utf-8") as f:
            data = json.load(f)

        if not create_portfolio:
            return dict(data)

        # Extract market parameters
        market_params = data["market_parameters"]

        # Create new portfolio
        underlying = data.get("risk_metrics", {}).get(
            "underlying_quantity",
            market_params.get("underlying_quantity", 0.0),
        )
        imported_portfolio = OptionPortfolio(
            underlying_quantity=underlying,
            spot_price=market_params["spot_price"],
            volatility=market_params["volatility"],
            risk_free_rate=market_params["risk_free_rate"],
            dividend_yield=market_params["dividend_yield"],
            valuation_date=valuation_date or program_trading_date(),
            symbol=market_params.get("symbol", "UNKNOWN"),
            default_exercise_style=default_exercise_style,
            contract_size=market_params["contract_size"],
            stamps=_stamps_from_market_params(market_params),
        )

        # Add positions (robust to variations in exported field names)
        for pos_data in data["positions"]:
            maturity_str = pos_data.get("maturity_date") or pos_data.get(
                "maturity",
            )
            if maturity_str is None:
                raise ValueError("Position entry missing maturity date")
            maturity = dt.fromisoformat(maturity_str)

            strike = pos_data.get("strike_price") or pos_data.get("strike")
            if strike is None:
                raise ValueError("Position entry missing strike price")

            # Coerce to the enum — a round-tripped file stores option_type as
            # its plain string .value, and a bare str compares equal to the
            # StrEnum member but lacks .value, which breaks a later re-export.
            raw_option_type = pos_data.get("option_type") or OptionType.CALL
            option_type = OptionType(str(raw_option_type).upper())
            quantity = pos_data.get("quantity", pos_data.get("qty", 1))

            # Handle volatility - check for both explicit flag and presence of
            # volatility data
            custom_volatility = pos_data.get("custom_volatility", False)
            # Use custom volatility if explicitly marked OR if volatility data
            # exists without flag
            position_volatility = (
                pos_data.get("volatility")
                if (custom_volatility or "volatility" in pos_data)
                else None
            )

            # Honor a serialized exercise_style; when absent (legacy files),
            # add_position falls back to the portfolio's default style.
            raw_style = pos_data.get("exercise_style")
            exercise_style: ExerciseStyle | None = None
            if raw_style is not None:
                try:
                    exercise_style = ExerciseStyle(str(raw_style).upper())
                except ValueError:
                    exercise_style = None

            imported_portfolio.add_position(
                strike_price=strike,
                maturity_date=maturity,
                option_type=option_type,
                quantity=quantity,
                volatility=position_volatility,
                exercise_style=exercise_style,
                # #365: a real historical or autosaved book can
                # legitimately hold a leg that expired after being
                # added — refusing the whole file over one such leg is
                # the wrong failure mode here. add_position()'s default
                # guard is for new entry (the /design form), not restore.
                reject_expired=False,
            )

            # Set entry tracking directly (not via add_position's kwargs)
            # so files predating this feature correctly default to None
            # instead of being back-filled with the import-time spot/date.
            new_position = imported_portfolio.positions[-1]
            new_position.entry_spot = pos_data.get("entry_spot")
            raw_entry_date = pos_data.get("entry_date")
            new_position.entry_date = (
                dt.fromisoformat(raw_entry_date) if raw_entry_date else None
            )
            new_position.entry_premium = pos_data.get("entry_premium")
            if pid := pos_data.get("position_id"):
                new_position.position_id = pid
            raw_volatility_as_of = pos_data.get("volatility_as_of")
            new_position.volatility_as_of = (
                dt.fromisoformat(raw_volatility_as_of)
                if raw_volatility_as_of
                else None
            )

        return {
            "portfolio": imported_portfolio,
            "market_params": market_params,
            "metadata": data.get("metadata", {}),
        }

    def import_from_yaml(
        self,
        filepath: str | Path,
        default_exercise_style: ExerciseStyle | None = None,
        *,
        valuation_date: dt | None = None,
    ) -> dict[str, Any]:
        """Import portfolio from YAML configuration file.

        Args:
            filepath: path to YAML file
            default_exercise_style: exercise style applied to positions whose
            config has no explicit ``exercise_style``.  Callers should pass the
            program's IPS style (``ips_config.pricing.exercise_style``).
            When None, the portfolio will have default_exercise_style=None and
            add_position() will raise ValueError for positions without an
            explicit style.
            valuation_date: as-of date for the load.  Sets the portfolio's
            ``valuation_date`` *and* anchors any relative ``maturity_days``
            entries, so a pinned load is reproducible in both.  Defaults to
            now, which is what production wants; tests asserting values that
            depend on time-to-expiry should pass an explicit date, or they
            will drift as the calendar moves.

        Returns:
            dict with 'portfolio', 'market_params', and 'metadata' keys

        """
        if not YAML_AVAILABLE:
            raise RuntimeError(
                "⚠️  PyYAML not installed. Cannot import from YAML.",
            )

        with Path.open(Path(filepath), encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Extract market parameters
        market_params = config["market_parameters"]

        # Determine underlying quantity
        underlying_qty = market_params.get("underlying_quantity", 0.0)

        # One as-of for the whole load: the portfolio's valuation date and the
        # anchor for relative maturities must agree, or a load straddling
        # midnight would price a 548-day tenor as 549/365. Since #182 this is
        # the program's trading date (midnight in the program timezone), which
        # removes the straddle entirely rather than just making it consistent.
        as_of = valuation_date or program_trading_date()

        # Create new portfolio
        imported_portfolio = OptionPortfolio(
            underlying_quantity=underlying_qty,
            spot_price=market_params["spot_price"],
            volatility=market_params["volatility"],
            risk_free_rate=market_params["risk_free_rate"],
            dividend_yield=market_params["dividend_yield"],
            valuation_date=as_of,
            symbol=market_params.get("symbol", "UNKNOWN"),
            default_exercise_style=default_exercise_style,
            contract_size=market_params["contract_size"],
            stamps=_stamps_from_market_params(market_params),
        )

        # Add positions
        for pos_config in config["positions"]:
            # Determine maturity date
            if "maturity_date" in pos_config:
                maturity = dt.fromisoformat(pos_config["maturity_date"])
            elif "maturity_days" in pos_config:
                maturity = as_of + timedelta(days=pos_config["maturity_days"])
            else:
                continue

            # Ensure maturity is timezone-aware. If the parsed datetime is
            # naive, assume UTC to avoid downstream timezone-related bugs.
            if maturity.tzinfo is None:
                maturity = maturity.replace(tzinfo=datetime.UTC)

            # Get optional position-specific volatility
            position_volatility = pos_config.get("volatility", None)

            raw_style = pos_config.get("exercise_style")
            exercise_style: ExerciseStyle | None = None
            if raw_style is not None:
                try:
                    exercise_style = ExerciseStyle(str(raw_style).upper())
                except ValueError:
                    exercise_style = None

            imported_portfolio.add_position(
                strike_price=pos_config["strike_price"],
                maturity_date=maturity,
                quantity=pos_config["quantity"],
                option_type=(
                    OptionType.CALL
                    if pos_config["option_type"].upper()
                    == OptionType.CALL.value
                    else OptionType.PUT
                ),
                volatility=position_volatility,
                exercise_style=exercise_style,
                # #365: see import_from_json's matching comment — a
                # restored book may legitimately hold an already-expired
                # leg, and refusing the whole file over one is wrong.
                reject_expired=False,
            )

            # See import_from_json for why this is set directly rather than
            # passed as an add_position kwarg.
            new_position = imported_portfolio.positions[-1]
            new_position.entry_spot = pos_config.get("entry_spot")
            raw_entry_date = pos_config.get("entry_date")
            new_position.entry_date = (
                dt.fromisoformat(raw_entry_date) if raw_entry_date else None
            )
            new_position.entry_premium = pos_config.get("entry_premium")
            if pid := pos_config.get("position_id"):
                new_position.position_id = pid
            raw_volatility_as_of = pos_config.get("volatility_as_of")
            new_position.volatility_as_of = (
                dt.fromisoformat(raw_volatility_as_of)
                if raw_volatility_as_of
                else None
            )

        return {
            "portfolio": imported_portfolio,
            "market_params": market_params,
            "metadata": {"source": "yaml", "filepath": str(filepath)},
        }

    def import_portfolio(
        self,
        filepath: str | Path,
        default_exercise_style: ExerciseStyle | None = None,
    ) -> dict[str, Any]:
        """Universal import function - auto-detects file format.

        Args:
            filepath: path to JSON or YAML file
            default_exercise_style: exercise style applied to positions with no
            explicit ``exercise_style``; forwarded to the format-specific
            importer.  Callers should pass the IPS style
            (``ips_config.pricing.exercise_style``). When None, the portfolio
            will have default_exercise_style=None.

        Returns:
            dict with 'portfolio', 'market_params', and 'metadata' keys

        """
        file_format = self.detect_file_format(filepath)

        if file_format == "yaml":
            return self.import_from_yaml(
                filepath,
                default_exercise_style=default_exercise_style,
            )
        if file_format == "json":
            return self.import_from_json(
                filepath,
                create_portfolio=True,
                default_exercise_style=default_exercise_style,
            )
        raise ValueError(f"Unsupported file format: {filepath}")

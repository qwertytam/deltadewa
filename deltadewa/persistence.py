"""
Portfolio persistence module for import/export operations.

This module provides utilities for saving and loading portfolio state
in multiple formats (JSON, CSV, YAML).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union
import pandas as pd
from deltadewa import OptionPortfolio
from deltadewa.reporting import ConsoleReporter
from deltadewa.constants import OptionType

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def load_config_yaml(filepath: Path = Path("portfolio_config_example.yaml")):
    """
    Load portfolio configuration from YAML file.
    Returns dict with 'market_parameters' and 'positions', or None if not available.
    """
    if not YAML_AVAILABLE:
        return None

    if not filepath.exists():
        return None

    reporter = ConsoleReporter(width=100)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Validate structure
        if not isinstance(config, dict):
            raise ValueError("YAML root must be a mapping/object")

        if "market_parameters" not in config or "positions" not in config:
            raise ValueError(
                "YAML must contain 'market_parameters' and 'positions' sections"
            )

        required_params = [
            "spot_price",
            "volatility",
            "risk_free_rate",
            "dividend_yield",
        ]
        for param in required_params:
            if param not in config["market_parameters"]:
                raise ValueError(f"Missing required market parameter: {param}")

        return config
    except Exception as e:  # pylint: disable=broad-except
        reporter.warning(f"Error loading YAML configuration: {e}")
        return None


class PortfolioSerializer:
    """Handle portfolio export/import in multiple formats."""

    def __init__(self, export_dir: Union[str, Path]):
        """
        Initialize the serializer.

        Args:
            export_dir: Directory path for exports (str or Path). If None, must be set later.
        """
        self.export_dir = Path(export_dir)
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # If creation fails, keep the path but it won't exist
            print(f"Export directory creation failed. {e}")

    # ========== Helper Functions ==========

    def list_available_files(self):
        """
        List all available portfolio files in the export directory.

        Returns:
            dict with 'json' and 'yaml' keys containing lists of file paths
        """
        json_files = sorted(
            self.export_dir.glob("*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        yaml_files = sorted(
            self.export_dir.glob("*.yaml"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        yaml_files.extend(
            sorted(
                self.export_dir.glob("*.yml"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
        )
        return {"json": json_files, "yaml": yaml_files}

    def update_export_dir(self, new_dir: Union[str, Path]) -> None:
        """
        Update the export directory and ensure it exists.

        Args:
            new_dir: New directory path for exports
        """
        self.export_dir = Path(new_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def detect_file_format(filepath):
        """
        Detect portfolio file format from extension.

        Args:
            filepath: Path to file

        Returns:
            str: 'yaml', 'json', or None if unsupported
        """
        suffix = Path(filepath).suffix.lower()
        if suffix in [".yaml", ".yml"]:
            return "yaml"
        elif suffix == ".json":
            return "json"
        else:
            return None

    # ========== Export Functions ==========

    def _build_export_data(self, portfolio, changelog) -> dict:
        """
        Build a comprehensive data structure representing the portfolio state,
        including market parameters, positions, and risk metrics.

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
        Returns:
            dict with complete portfolio data for export
        """

        data = {
            "metadata": {
                "exported_at": datetime.now(tz=timezone.utc).isoformat(),
                "version": "1.0",
            },
            "market_parameters": {
                "spot_price": portfolio.spot_price,
                "volatility": portfolio.volatility,
                "risk_free_rate": portfolio.risk_free_rate,
                "dividend_yield": portfolio.dividend_yield,
                "underlying_quantity": portfolio.underlying_quantity,
                "symbol": portfolio.get_symbol(),
            },
            "positions": [],
            "risk_metrics": portfolio.summary_stats(),
            "session_changelog": [],
        }

        for pos in portfolio.positions:
            position_data = {
                "option_type": pos.option.option_type.value,
                "strike_price": pos.option.strike_price,
                "maturity_date": pos.option.maturity_date.isoformat(),
                "quantity": pos.quantity,
                "contract_size": pos.contract_size,
                "volatility": pos.option.volatility,
                "custom_volatility": pos.custom_volatility,
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
                }
            )

        return data

    def export_to_json(
        self, portfolio, changelog, filename="portfolio_book.json"
    ) -> Path:
        """
        Export complete portfolio state to JSON format.

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
            filename: output filename

        Returns:
            Path to saved file
        """
        portfolio_data = self._build_export_data(portfolio, changelog)

        # Save to file
        output_path = self.export_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(portfolio_data, f, indent=2)

        return Path(output_path)

    def export_to_csv(self, portfolio, changelog, filename="portfolio.csv"):
        """
        Export portfolio to CSV files (positions and risk).

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
            filename: output filename

        Returns:
            dict with paths to saved files
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
                }
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
            ]
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
        self, portfolio, changelog, filename="portfolio_export.yaml"
    ) -> Path | None:
        """
        Export portfolio configuration to YAML format (useful for edits/versioning).

        The saved structure contains 'market_parameters' and a list of 'positions' with
        option_type, strike_price, maturity_date (ISO YYYY-MM-DD), quantity and symbol.

        Args:
            portfolio: OptionPortfolio instance
            changelog: PortfolioLogger instance
            filename: output filename

        Returns:
            Path to saved file, or None if YAML not available
        """
        if not YAML_AVAILABLE:
            print("⚠️  PyYAML not installed. Cannot export to YAML.")
            return None

        portfolio_data = self._build_export_data(portfolio, changelog)

        output_path = self.export_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(
                portfolio_data, f, default_flow_style=False, sort_keys=False
            )

        return Path(output_path)

    # ========== Import Functions ==========

    def import_from_json(self, filepath, create_portfolio=True) -> dict:
        """
        Import portfolio from JSON file.

        Args:
            filepath: path to JSON file
            create_portfolio: if True, creates and returns portfolio object

        Returns:
            dict with portfolio data (and 'portfolio' key if create_portfolio=True)
        """

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not create_portfolio:
            return data

        # Extract market parameters
        market_params = data["market_parameters"]

        # Create new portfolio
        underlying = data.get("risk_metrics", {}).get(
            "underlying_quantity", market_params.get("underlying_quantity", 0.0)
        )
        imported_portfolio = OptionPortfolio(
            underlying_quantity=underlying,
            spot_price=market_params["spot_price"],
            volatility=market_params["volatility"],
            risk_free_rate=market_params["risk_free_rate"],
            dividend_yield=market_params["dividend_yield"],
            symbol=market_params.get("symbol", "UNKNOWN"),
        )

        # Add positions (robust to variations in exported field names)
        for pos_data in data["positions"]:
            maturity_str = pos_data.get("maturity_date") or pos_data.get(
                "maturity"
            )
            if maturity_str is None:
                raise ValueError("Position entry missing maturity date")
            maturity = datetime.fromisoformat(maturity_str)

            strike = pos_data.get("strike_price") or pos_data.get("strike")
            if strike is None:
                raise ValueError("Position entry missing strike price")

            option_type = (
                pos_data.get("option_type")
                or pos_data.get("type")
                or OptionType.CALL
            )
            quantity = pos_data.get("quantity", pos_data.get("qty", 1))

            # Handle volatility - check for both explicit flag and presence of volatility data
            custom_volatility = pos_data.get("custom_volatility", False)
            # Use custom volatility if explicitly marked OR if volatility data exists without flag
            position_volatility = (
                pos_data.get("volatility")
                if (custom_volatility or "volatility" in pos_data)
                else None
            )

            imported_portfolio.add_position(
                strike_price=strike,
                maturity_date=maturity,
                option_type=option_type,
                quantity=quantity,
                volatility=position_volatility,
            )

        return {
            "portfolio": imported_portfolio,
            "market_params": market_params,
            "metadata": data.get("metadata", {}),
        }

    def import_from_yaml(self, filepath) -> dict:
        """
        Import portfolio from YAML configuration file.

        Args:
            filepath: path to YAML file

        Returns:
            dict with 'portfolio', 'market_params', and 'metadata' keys
        """

        if not YAML_AVAILABLE:
            raise RuntimeError(
                "⚠️  PyYAML not installed. Cannot import from YAML."
            )

        with open(filepath, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Extract market parameters
        market_params = config["market_parameters"]

        # Determine underlying quantity
        underlying_qty = market_params.get("underlying_quantity", 0.0)

        # Create new portfolio
        imported_portfolio = OptionPortfolio(
            underlying_quantity=underlying_qty,
            spot_price=market_params["spot_price"],
            volatility=market_params["volatility"],
            risk_free_rate=market_params["risk_free_rate"],
            dividend_yield=market_params["dividend_yield"],
            valuation_date=datetime.now(tz=timezone.utc),
            symbol=market_params.get("symbol", "UNKNOWN"),
        )

        # Add positions
        today = datetime.now(tz=timezone.utc)
        for pos_config in config["positions"]:
            # Determine maturity date
            if "maturity_date" in pos_config:
                maturity = datetime.fromisoformat(pos_config["maturity_date"])
            elif "maturity_days" in pos_config:
                maturity = today + timedelta(days=pos_config["maturity_days"])
            else:
                continue

            # Get optional position-specific volatility
            position_volatility = pos_config.get("volatility", None)

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
            )

        return {
            "portfolio": imported_portfolio,
            "market_params": market_params,
            "metadata": {"source": "yaml", "filepath": str(filepath)},
        }

    def import_portfolio(self, filepath) -> dict:
        """
        Universal import function - auto-detects file format.

        Args:
            filepath: path to JSON or YAML file

        Returns:
            dict with 'portfolio', 'market_params', and 'metadata' keys
        """
        file_format = self.detect_file_format(filepath)

        if file_format == "yaml":
            return self.import_from_yaml(filepath)
        elif file_format == "json":
            return self.import_from_json(filepath, create_portfolio=True)
        else:
            raise ValueError(f"Unsupported file format: {filepath}")

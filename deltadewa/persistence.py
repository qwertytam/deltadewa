"""
Portfolio persistence module for import/export operations.

This module provides utilities for saving and loading portfolio state
in multiple formats (JSON, CSV, YAML).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from deltadewa import OptionPortfolio

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class PortfolioSerializer:
    """Handle portfolio export/import in multiple formats."""

    def __init__(self, export_dir="exports"):
        """
        Initialize the serializer.

        Args:
            export_dir: Directory path for exports (str or Path)
        """
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(exist_ok=True)

    # ========== Helper Functions ==========

    def list_available_files(self):
        """
        List all available portfolio files in the export directory.

        Returns:
            dict with 'json' and 'yaml' keys containing lists of file paths
        """
        json_files = sorted(
            self.export_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True
        )
        yaml_files = sorted(
            self.export_dir.glob("*.yaml"), key=lambda x: x.stat().st_mtime, reverse=True
        )
        yaml_files.extend(
            sorted(self.export_dir.glob("*.yml"), key=lambda x: x.stat().st_mtime, reverse=True)
        )
        return {"json": json_files, "yaml": yaml_files}

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

    def export_to_json(self, portfolio, market_params, filename="portfolio_book.json"):
        """
        Export complete portfolio state to JSON format.

        Args:
            portfolio: OptionPortfolio instance
            market_params: dict with market parameters
            filename: output filename

        Returns:
            Path to saved file
        """
        # Build complete portfolio state
        portfolio_data = {
            "metadata": {"exported_at": datetime.now().isoformat(), "version": "1.0"},
            "market_parameters": market_params,
            "positions": [],
            "risk_metrics": portfolio.summary_stats(),
        }

        # Export each position
        for pos in portfolio.positions:
            position_data = {
                "option_type": pos.option.option_type,
                "strike_price": pos.option.strike_price,
                "maturity_date": pos.option.maturity_date.isoformat(),
                "quantity": pos.quantity,
                "contract_size": pos.contract_size,
                "greeks": {
                    "delta": pos.option.delta(),
                    "gamma": pos.option.gamma(),
                    "theta": pos.option.theta(),
                    "vega": pos.option.vega(),
                    "rho": pos.option.rho(),
                },
                "price": pos.option.price(),
                "position_value": pos.option.price() * pos.quantity * pos.contract_size,
            }
            portfolio_data["positions"].append(position_data)

        # Save to file
        output_path = self.export_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(portfolio_data, f, indent=2)

        return output_path

    def export_to_csv(self, portfolio, filename_prefix="portfolio"):
        """
        Export portfolio to CSV files (positions and risk).

        Args:
            portfolio: OptionPortfolio instance
            filename_prefix: prefix for output files

        Returns:
            dict with paths to saved files
        """
        # Export positions
        positions_data = []
        for i, pos in enumerate(portfolio.positions):
            positions_data.append(
                {
                    "position_id": i,
                    "option_type": pos.option.option_type,
                    "strike": pos.option.strike_price,
                    "maturity": pos.option.maturity_date.strftime("%Y-%m-%d"),
                    "quantity": pos.quantity,
                    "contract_size": pos.contract_size,
                    "price": pos.option.price(),
                    "value": pos.option.price() * pos.quantity * pos.contract_size,
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

        return {"positions": positions_file, "risk": risk_file}

    def export_to_yaml(self, portfolio, market_params, filename="portfolio_export.yaml"):
        """
        Export portfolio configuration to YAML format (useful for edits/versioning).

        The saved structure contains 'market_parameters' and a list of 'positions' with
        option_type, strike_price, maturity_date (ISO YYYY-MM-DD), quantity and symbol.

        Args:
            portfolio: OptionPortfolio instance
            market_params: dict with market parameters
            filename: output filename

        Returns:
            Path to saved file, or None if YAML not available
        """
        if not YAML_AVAILABLE:
            print("⚠️  PyYAML not installed. Cannot export to YAML.")
            return None

        # Build configuration structure
        config = {
            "market_parameters": {
                "spot_price": market_params["spot_price"],
                "volatility": market_params["volatility"],
                "risk_free_rate": market_params["risk_free_rate"],
                "dividend_yield": market_params["dividend_yield"],
                "underlying_quantity": getattr(
                    portfolio, "underlying_quantity", market_params.get("underlying_quantity", 0.0)
                ),
                "symbol": market_params.get("symbol", "UNKNOWN"),
            },
            "positions": [],
        }

        for pos in portfolio.positions:
            position_data = {
                "option_type": pos.option.option_type,
                "strike_price": float(pos.option.strike_price),
                "maturity_date": pos.option.maturity_date.date().isoformat(),
                "quantity": int(pos.quantity),
                "symbol": getattr(pos, "symbol", None),
            }
            config["positions"].append(position_data)

        output_path = self.export_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        return output_path

    # ========== Import Functions ==========

    def import_from_json(self, filepath, create_portfolio=True):
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
        )

        # Add positions (robust to variations in exported field names)
        for pos_data in data["positions"]:
            maturity_str = pos_data.get("maturity_date") or pos_data.get("maturity")
            if maturity_str is None:
                raise ValueError("Position entry missing maturity date")
            maturity = datetime.fromisoformat(maturity_str)

            strike = pos_data.get("strike_price") or pos_data.get("strike")
            if strike is None:
                raise ValueError("Position entry missing strike price")

            option_type = pos_data.get("option_type") or pos_data.get("type") or "call"
            quantity = pos_data.get("quantity", pos_data.get("qty", 1))

            imported_portfolio.add_position(
                strike_price=strike,
                maturity_date=maturity,
                option_type=option_type,
                quantity=quantity,
            )

        return {
            "portfolio": imported_portfolio,
            "market_params": market_params,
            "metadata": data.get("metadata", {}),
        }

    def import_from_yaml(self, filepath):
        """
        Import portfolio from YAML configuration file.

        Args:
            filepath: path to YAML file

        Returns:
            dict with 'portfolio', 'market_params', and 'metadata' keys
        """

        if not YAML_AVAILABLE:
            print("⚠️  PyYAML not installed. Cannot import from YAML.")
            return None

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
            valuation_date=datetime.now(),
        )

        # Add positions
        today = datetime.now()
        for pos_config in config["positions"]:
            # Determine maturity date
            if "maturity_date" in pos_config:
                maturity = datetime.fromisoformat(pos_config["maturity_date"])
            elif "maturity_days" in pos_config:
                maturity = today + timedelta(days=pos_config["maturity_days"])
            else:
                continue

            imported_portfolio.add_position(
                strike_price=pos_config["strike_price"],
                maturity_date=maturity,
                quantity=pos_config["quantity"],
                option_type=pos_config["option_type"].lower(),
                symbol=pos_config.get("symbol", market_params.get("symbol", "UNKNOWN")),
            )

        return {
            "portfolio": imported_portfolio,
            "market_params": market_params,
            "metadata": {"source": "yaml", "filepath": str(filepath)},
        }

    def import_portfolio(self, filepath):
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


# ========== Convenience Functions (for backward compatibility) ==========


def list_available_portfolio_files(export_dir="exports"):
    """List all available portfolio files in the export directory."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.list_available_files()


def detect_file_format(filepath):
    """Detect portfolio file format from extension."""
    return PortfolioSerializer.detect_file_format(filepath)


def export_portfolio_to_json(
    portfolio, market_params, filename="portfolio_book.json", export_dir="exports"
):
    """Export complete portfolio state to JSON format."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.export_to_json(portfolio, market_params, filename)


def export_portfolio_to_csv(portfolio, filename_prefix="portfolio", export_dir="exports"):
    """Export portfolio to CSV files (positions and risk)."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.export_to_csv(portfolio, filename_prefix)


def export_portfolio_to_yaml(
    portfolio, market_params, filename="portfolio_export.yaml", export_dir="exports"
):
    """Export portfolio configuration to YAML format."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.export_to_yaml(portfolio, market_params, filename)


def import_portfolio_from_json(filepath, create_portfolio=True, export_dir="exports"):
    """Import portfolio from JSON file."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.import_from_json(filepath, create_portfolio)


def import_from_yaml(filepath, export_dir="exports"):
    """Import portfolio from YAML configuration file."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.import_from_yaml(filepath)


def import_portfolio(filepath, export_dir="exports"):
    """Universal import function - auto-detects file format."""
    serializer = PortfolioSerializer(export_dir)
    return serializer.import_portfolio(filepath)

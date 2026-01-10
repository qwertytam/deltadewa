"""Portfolio serialization and I/O utilities for deltadewa.

This module provides functions for exporting and importing option portfolios
in multiple formats (JSON, CSV, YAML).
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union
import json

import pandas as pd

# Check for optional PyYAML dependency
try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# Default export directory
DEFAULT_EXPORT_DIR = Path("exports")


def list_available_portfolio_files(export_dir: Path = DEFAULT_EXPORT_DIR) -> Dict[str, List[Path]]:
    """
    List all available portfolio files in the export directory.

    Args:
        export_dir: Directory to search for portfolio files

    Returns:
        Dictionary with 'json' and 'yaml' keys containing lists of file paths,
        sorted by modification time (most recent first)
    """
    if not export_dir.exists():
        return {"json": [], "yaml": []}

    json_files = sorted(export_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    yaml_files = sorted(export_dir.glob("*.yaml"), key=lambda x: x.stat().st_mtime, reverse=True)
    yaml_files.extend(
        sorted(export_dir.glob("*.yml"), key=lambda x: x.stat().st_mtime, reverse=True)
    )
    return {"json": json_files, "yaml": yaml_files}


def detect_file_format(filepath: Union[str, Path]) -> Optional[str]:
    """
    Detect portfolio file format from extension.

    Args:
        filepath: Path to file

    Returns:
        'yaml', 'json', or None if format cannot be detected
    """
    suffix = Path(filepath).suffix.lower()
    if suffix in [".yaml", ".yml"]:
        return "yaml"
    elif suffix == ".json":
        return "json"
    else:
        return None


def export_portfolio_to_json(
    portfolio,
    market_params: Dict,
    filename: str = "portfolio_book.json",
    export_dir: Path = DEFAULT_EXPORT_DIR,
) -> Path:
    """
    Export complete portfolio state to JSON format.

    Args:
        portfolio: OptionPortfolio instance
        market_params: Dictionary with market parameters (spot_price, volatility, etc.)
        filename: Output filename
        export_dir: Directory to save the file

    Returns:
        Path to saved file
    """
    # Ensure export directory exists
    export_dir.mkdir(parents=True, exist_ok=True)

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
    output_path = export_dir / filename
    with open(output_path, "w") as f:
        json.dump(portfolio_data, f, indent=2)

    return output_path


def export_portfolio_to_csv(
    portfolio, filename_prefix: str = "portfolio", export_dir: Path = DEFAULT_EXPORT_DIR
) -> Dict[str, Path]:
    """
    Export portfolio to CSV files (positions and risk).

    Args:
        portfolio: OptionPortfolio instance
        filename_prefix: Prefix for output files
        export_dir: Directory to save the files

    Returns:
        Dictionary with 'positions' and 'risk' keys containing paths to saved files
    """
    # Ensure export directory exists
    export_dir.mkdir(parents=True, exist_ok=True)

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
    positions_file = export_dir / f"{filename_prefix}_positions.csv"
    df_positions_export.to_csv(positions_file, index=False)

    # Export risk metrics
    risk_stats = portfolio.summary_stats()
    risk_data = []
    for metric, value in risk_stats.items():
        risk_data.append({"metric": metric, "value": value})

    df_risk = pd.DataFrame(risk_data)
    risk_file = export_dir / f"{filename_prefix}_risk.csv"
    df_risk.to_csv(risk_file, index=False)

    return {"positions": positions_file, "risk": risk_file}


def export_portfolio_to_yaml(
    portfolio,
    market_params: Dict,
    filename: str = "portfolio_export.yaml",
    export_dir: Path = DEFAULT_EXPORT_DIR,
) -> Optional[Path]:
    """
    Export portfolio configuration to YAML format (useful for edits/versioning).

    The saved structure contains 'market_parameters' and a list of 'positions' with
    option_type, strike_price, maturity_date (ISO YYYY-MM-DD), quantity and symbol.

    Args:
        portfolio: OptionPortfolio instance
        market_params: Dictionary with market parameters
        filename: Output filename
        export_dir: Directory to save the file

    Returns:
        Path to saved file, or None if PyYAML is not available
    """
    if not YAML_AVAILABLE:
        print("⚠️  PyYAML not installed. Cannot export to YAML.")
        return None

    # Ensure export directory exists
    export_dir.mkdir(parents=True, exist_ok=True)

    # Build configuration structure
    config = {
        "market_parameters": {
            "spot_price": market_params["spot_price"],
            "volatility": market_params["volatility"],
            "risk_free_rate": market_params["risk_free_rate"],
            "dividend_yield": market_params["dividend_yield"],
            "underlying_quantity": portfolio.underlying_quantity,
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

    output_path = export_dir / filename
    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return output_path


def import_portfolio_from_json(filepath: Union[str, Path], create_portfolio: bool = True) -> Dict:
    """
    Import portfolio from JSON file.

    Args:
        filepath: Path to JSON file
        create_portfolio: If True, creates and returns OptionPortfolio object

    Returns:
        Dictionary with portfolio data. If create_portfolio=True, includes
        'portfolio' key with OptionPortfolio instance, 'market_params' with
        market parameters, and 'metadata' with file metadata.
    """
    from .portfolio import OptionPortfolio

    with open(filepath, "r") as f:
        data = json.load(f)

    if not create_portfolio:
        return data

    # Extract market parameters
    market_params = data["market_parameters"]

    # Create new portfolio
    underlying = data.get("risk_metrics", {}).get("underlying_quantity", 0.0)
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
            strike_price=strike, maturity_date=maturity, option_type=option_type, quantity=quantity
        )

    return {
        "portfolio": imported_portfolio,
        "market_params": market_params,
        "metadata": data.get("metadata", {}),
    }


def import_from_yaml(filepath: Union[str, Path]) -> Optional[Dict]:
    """
    Import portfolio from YAML configuration file.

    Args:
        filepath: Path to YAML file

    Returns:
        Dictionary with 'portfolio' (OptionPortfolio instance), 'market_params',
        and 'metadata' keys, or None if PyYAML is not available
    """
    from .portfolio import OptionPortfolio

    if not YAML_AVAILABLE:
        print("⚠️  PyYAML not installed. Cannot import from YAML.")
        return None

    with open(filepath, "r") as f:
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


def import_portfolio(filepath: Union[str, Path]) -> Dict:
    """
    Universal import function - auto-detects file format.

    Args:
        filepath: Path to JSON or YAML file

    Returns:
        Dictionary with 'portfolio', 'market_params', and 'metadata' keys

    Raises:
        ValueError: If file format is unsupported
    """
    file_format = detect_file_format(filepath)

    if file_format == "yaml":
        return import_from_yaml(filepath)
    elif file_format == "json":
        return import_portfolio_from_json(filepath, create_portfolio=True)
    else:
        raise ValueError(f"Unsupported file format: {filepath}")

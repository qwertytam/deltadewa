"""Configuration management for deltadewa portfolios.

This module provides functions for loading and validating portfolio
configurations from YAML files.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Union

# Check for optional PyYAML dependency
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def load_config_yaml(filepath: Union[str, Path] = Path('portfolio_config_example.yaml')) -> Optional[Dict]:
    """
    Load portfolio configuration from YAML file.
    
    Validates the configuration structure and required fields.
    
    Args:
        filepath: Path to YAML configuration file
        
    Returns:
        Dictionary with 'market_parameters' and 'positions' sections,
        or None if file doesn't exist, PyYAML is not available, or
        validation fails
    """
    if not YAML_AVAILABLE:
        return None
    
    filepath = Path(filepath)
    if not filepath.exists():
        return None
    
    try:
        with open(filepath, 'r') as f:
            config = yaml.safe_load(f)
        
        # Validate structure
        if not isinstance(config, dict):
            raise ValueError("YAML root must be a mapping/object")
        
        if 'market_parameters' not in config or 'positions' not in config:
            raise ValueError("YAML must contain 'market_parameters' and 'positions' sections")
        
        # Validate required market parameters
        required_params = ['spot_price', 'volatility', 'risk_free_rate', 'dividend_yield']
        for param in required_params:
            if param not in config['market_parameters']:
                raise ValueError(f"Missing required market parameter: {param}")
        
        return config
    except Exception as e:
        print(f"⚠️  Error loading YAML configuration: {e}")
        return None


def create_portfolio_from_config(
    config: Dict,
    valuation_date: Optional[datetime] = None
):
    """
    Create an OptionPortfolio instance from a configuration dictionary.
    
    Args:
        config: Configuration dictionary with 'market_parameters' and 'positions'
        valuation_date: Valuation date for the portfolio (defaults to now)
        
    Returns:
        Configured OptionPortfolio instance
        
    Raises:
        ValueError: If configuration is invalid
    """
    from .portfolio import OptionPortfolio
    
    if not config:
        raise ValueError("Configuration is None or empty")
    
    if 'market_parameters' not in config:
        raise ValueError("Configuration missing 'market_parameters' section")
    
    if 'positions' not in config:
        raise ValueError("Configuration missing 'positions' section")
    
    market_params = config['market_parameters']
    
    # Create portfolio with market parameters
    portfolio = OptionPortfolio(
        underlying_quantity=market_params.get('underlying_quantity', 0.0),
        spot_price=market_params['spot_price'],
        volatility=market_params['volatility'],
        risk_free_rate=market_params['risk_free_rate'],
        dividend_yield=market_params['dividend_yield'],
        valuation_date=valuation_date or datetime.now()
    )
    
    # Add positions from configuration
    today = valuation_date or datetime.now()
    for pos_config in config['positions']:
        # Determine maturity date (support both absolute and relative dates)
        if 'maturity_date' in pos_config:
            # Absolute date specified
            maturity = datetime.fromisoformat(pos_config['maturity_date'])
        elif 'maturity_days' in pos_config:
            # Relative days from today
            maturity = today + timedelta(days=pos_config['maturity_days'])
        else:
            print(f"⚠️  Skipping position: no maturity specified")
            continue
        
        # Add position to portfolio
        portfolio.add_position(
            strike_price=pos_config['strike_price'],
            maturity_date=maturity,
            quantity=pos_config['quantity'],
            option_type=pos_config['option_type'].lower(),
            symbol=pos_config.get('symbol', market_params.get('symbol', 'UNKNOWN'))
        )
    
    return portfolio

"""
Example script demonstrating the deltadewa American options portfolio management.

This script creates a sample portfolio and demonstrates key functionality.
"""

from datetime import datetime, timedelta
from deltadewa import AmericanOption, OptionPortfolio


def main():
    print("=" * 70)
    print("DELTADEWA - American Options Portfolio Management Example")
    print("=" * 70)
    print()

    # Market parameters
    spot_price = 100.0
    volatility = 0.25
    risk_free_rate = 0.05
    dividend_yield = 0.02
    notional_position = 1000.0  # Long 1000 shares

    print("Market Parameters:")
    print(f"  Spot Price: ${spot_price}")
    print(f"  Volatility: {volatility*100}%")
    print(f"  Risk-Free Rate: {risk_free_rate*100}%")
    print(f"  Dividend Yield: {dividend_yield*100}%")
    print(f"  Notional Position: {notional_position:,.0f} shares")
    print()

    # Create portfolio
    portfolio = OptionPortfolio(
        notional_position=notional_position,
        spot_price=spot_price,
        volatility=volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )

    # Add positions
    print("Adding Option Positions...")
    today = datetime.now()
    maturity_30d = today + timedelta(days=30)
    maturity_60d = today + timedelta(days=60)
    maturity_90d = today + timedelta(days=90)

    # Long puts for downside protection
    portfolio.add_position(95, maturity_30d, 5, "put")
    portfolio.add_position(95, maturity_60d, 5, "put")
    portfolio.add_position(100, maturity_60d, 10, "put")

    # Short calls for income
    portfolio.add_position(105, maturity_30d, -5, "call")
    portfolio.add_position(110, maturity_60d, -5, "call")

    print(f"  Added {len(portfolio.positions)} positions")
    print()

    # Display individual option example
    print("Sample Individual Option:")
    print("-" * 70)
    sample_option = portfolio.positions[0].option
    print(sample_option)
    greeks = sample_option.greeks()
    print(f"  Price: ${greeks['price']:.4f}")
    print(f"  Delta: {greeks['delta']:.4f}")
    print(f"  Gamma: {greeks['gamma']:.6f}")
    print(f"  Vega: {greeks['vega']:.4f}")
    print(f"  Theta: ${greeks['theta']:.4f}/day")
    print()

    # Portfolio summary
    print("Portfolio Summary:")
    print("-" * 70)
    stats = portfolio.summary_stats()
    
    print(f"Total Positions: {stats['total_positions']}")
    print(f"Total Portfolio Value: ${stats['total_value']:,.2f}")
    print()
    
    print("Delta Analysis:")
    print(f"  Portfolio Delta: {stats['total_delta']:,.2f}")
    print(f"  Notional Position: {stats['notional_position']:,.2f}")
    print(f"  Net Delta Exposure: {stats['net_delta']:,.2f}")
    print(f"  Hedge Ratio: {stats['hedge_ratio']:.2f}%")
    print(f"  Delta Adjustment Needed: {stats['delta_adjustment']:.2f} shares")
    print()
    
    print("Other Greeks:")
    print(f"  Total Gamma: {stats['total_gamma']:.4f}")
    print(f"  Total Vega: {stats['total_vega']:.2f}")
    print(f"  Total Theta: ${stats['total_theta']:.2f}/day")
    print(f"  Total Rho: {stats['total_rho']:.2f}")
    print()

    # Interpretation
    print("Hedge Analysis:")
    print("-" * 70)
    if abs(stats['net_delta']) < abs(stats['notional_position']) * 0.1:
        print("✓ Portfolio is well-hedged (net delta < 10% of notional)")
    elif stats['net_delta'] * stats['notional_position'] > 0:
        print("⚠ Portfolio is under-hedged (same direction as notional)")
    else:
        print("⚠ Portfolio may be over-hedged (opposite direction to notional)")
    
    if stats['delta_adjustment'] > 0:
        print(f"→ Consider BUYING {abs(stats['delta_adjustment']):.0f} shares for delta neutrality")
    elif stats['delta_adjustment'] < 0:
        print(f"→ Consider SELLING {abs(stats['delta_adjustment']):.0f} shares for delta neutrality")
    else:
        print("✓ Portfolio is delta neutral")
    print()

    # Position details
    print("Position Details:")
    print("-" * 70)
    df = portfolio.to_dataframe()
    print(df.to_string(index=False))
    print()

    # Scenario analysis
    print("Quick Scenario Analysis:")
    print("-" * 70)
    scenarios = [
        ("Down 10%", spot_price * 0.9),
        ("Current", spot_price),
        ("Up 10%", spot_price * 1.1),
    ]
    
    current_value = portfolio.total_value()
    
    for name, new_spot in scenarios:
        portfolio.update_market_conditions(spot_price=new_spot)
        new_value = portfolio.total_value()
        pnl = new_value - current_value
        underlying_pnl = (new_spot - spot_price) * notional_position
        total_pnl = pnl + underlying_pnl
        
        print(f"\n{name} (Spot = ${new_spot:.2f}):")
        print(f"  Options P&L: ${pnl:+,.2f}")
        print(f"  Underlying P&L: ${underlying_pnl:+,.2f}")
        print(f"  Total P&L: ${total_pnl:+,.2f}")
        print(f"  Net Delta: {portfolio.net_delta():.2f}")
    
    # Reset to original spot
    portfolio.update_market_conditions(spot_price=spot_price)
    
    print()
    print("=" * 70)
    print("For full interactive analysis, run: jupyter lab options_dashboard.ipynb")
    print("=" * 70)


if __name__ == "__main__":
    main()

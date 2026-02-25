"""Custom warning classes for deltadewa.

Import and use these instead of plain ``UserWarning`` so callers can
selectively filter them::

    import warnings
    from deltadewa.warnings import ClosedFormAccuracyWarning

    # Suppress for a whole sweep
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ClosedFormAccuracyWarning)
        result = pricer.portfolio_values_at(spots, date)
"""


class ClosedFormAccuracyWarning(UserWarning):
    """Closed Form Accuracy Warning.

    Raised when the Bjerksund-Stensland closed-form approximation is used
    in a regime where its accuracy is known to degrade.

    Known regimes:
    - Deep ITM options (moneyness > 15 %)
    - Short-dated puts (< 7 days to expiry)
    - Very high implied volatility (> 80 %)

    To suppress::

        import warnings
        from deltadewa.warnings import ClosedFormAccuracyWarning
        warnings.filterwarnings("ignore", category=ClosedFormAccuracyWarning)
    """

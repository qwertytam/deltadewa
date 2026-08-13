"""Formatting utilities for the DeltaDewa options dashboard.

This package provides consistent styling and formatting functions for:
- Scalar value formatting (currency, percentages, numbers, Greeks)
- DataFrame display formatting and styling

The HTML badge/metric builders (``html.py``) and the matplotlib gradient
helpers (``gradients.py``) were retired with the Jupyter layer in #279: they
emitted strings and Styler colourings for ``ipywidgets``, and the Dash pages
build ``html.Span`` components with CSS classes instead.

Re-exports have been removed — import from submodules directly, for example:

    from deltadewa.formatters.values import format_currency
    from deltadewa.formatters.dataframes import format_portfolio_dataframe

This file intentionally contains no re-exported symbols.
"""

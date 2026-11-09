"""Chart builders for the Dash pages.

Import from the submodules directly; this package re-exports nothing:

    from deltadewa.visualization.crash_charts_plotly import plot_scenario_curve
    from deltadewa.visualization.stress_charts_plotly import STRESS_METRICS

- ``crash_charts_plotly``: the crash scenario curve on ``/monitor``.
- ``distribution_charts_plotly``: the Monte Carlo distribution on ``/design``.
- ``stress_charts_plotly``: the spot/vol and time/price stress charts.

There was a second, matplotlib-backed generation of these builders
(``OptionCharts`` and its mixins). It was reached only from the retired
notebooks and was retired in #312, which is also what let ``matplotlib`` and
``pillow`` leave the dependency set. See ``docs/part-x-coverage.md``,
"The matplotlib half of visualization/ — retired (#312)".
"""

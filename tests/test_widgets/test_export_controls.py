"""Tests for deltadewa.widgets.export_controls import widget."""

from pathlib import Path
from unittest.mock import Mock

import ipywidgets as widgets  # type: ignore[import-untyped]
import pytest

from deltadewa.persistence import PortfolioSerializer
from deltadewa.widgets import export_controls
from deltadewa.widgets.portfolio_controls import PortfolioWidgets

# ruff: noqa: S101

PORTFOLIO_YAML = """
market_parameters:
  spot_price: 100.0
  volatility: 0.20
  risk_free_rate: 0.04
  dividend_yield: 0.015
  symbol: "SPY"

positions:
  - option_type: "put"
    strike_price: 95.0
    maturity_days: 30
    quantity: 50
"""


class _FakeFileChooser(widgets.HBox):
    """Stand-in for ipyfilechooser.FileChooser.

    A real Widget subclass (so it satisfies ipywidgets' Box.children
    type check) exposing just the bits ExportControlsMixin actually
    uses: .selected, .register_callback(), and .reset().
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Ignore FileChooser's constructor args; start unselected."""
        _ = args, kwargs
        super().__init__()
        self.selected: str | None = None
        self.callback: object = None
        self.reset_calls = 0

    def register_callback(self, callback: object) -> None:
        """Store the callback for the test to invoke manually."""
        self.callback = callback

    def reset(self, *args: object, **kwargs: object) -> None:
        """Clear the selection, matching the real widget's behavior."""
        _ = args, kwargs
        self.selected = None
        self.reset_calls += 1


@pytest.fixture
def mock_portfolio() -> Mock:
    """Create a mock portfolio to receive imported attributes."""
    portfolio = Mock()
    portfolio.positions = []
    return portfolio


@pytest.fixture
def mock_changelog() -> Mock:
    """Create a mock changelog for testing."""
    return Mock()


@pytest.fixture(autouse=True)
def fake_file_chooser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real FileChooser with a lightweight test double.

    The real widget renders fine headlessly, but these tests need to
    simulate a user picking a file - something only the real in-browser
    dialog can do - so every test in this module gets the fake instead.
    """
    monkeypatch.setattr(export_controls, "FileChooser", _FakeFileChooser)


def _make_widgets(
    export_dir: Path,
    examples_dir: Path,
    mock_portfolio: Mock,
    mock_changelog: Mock,
) -> PortfolioWidgets:
    serializer = PortfolioSerializer(export_dir, examples_dir)
    return PortfolioWidgets(mock_portfolio, serializer, mock_changelog)


class TestFileChooserSelection:
    """Tests for the FileChooser -> filename_input -> import/preview flow."""

    def test_selecting_a_file_updates_filename_input(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
    ) -> None:
        """Picking a file in the chooser writes its path to filename_input."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )
        portfolio_file = tmp_path / "portfolio.yaml"
        portfolio_file.write_text(PORTFOLIO_YAML)

        import_section = pw.display_import()
        file_chooser = import_section.children[1]
        filename_input = import_section.children[2]

        # Simulate the user picking a file in the chooser's dialog.
        file_chooser.selected = str(portfolio_file)
        file_chooser.callback(file_chooser)

        assert filename_input.value == str(portfolio_file)

    def test_selected_path_flows_through_to_import(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The chooser's selection is what Import Portfolio actually uses."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )
        portfolio_file = tmp_path / "portfolio.yaml"
        portfolio_file.write_text(PORTFOLIO_YAML)

        import_section = pw.display_import()
        file_chooser = import_section.children[1]
        file_chooser.selected = str(portfolio_file)
        file_chooser.callback(file_chooser)

        import_controls_box = import_section.children[3]
        import_button = import_controls_box.children[2]
        import_button.click()

        text = capsys.readouterr().out
        assert "Successfully imported" in text
        assert len(mock_portfolio.positions) == 1

    def test_clear_button_resets_chooser_and_filename(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
    ) -> None:
        """Clear empties filename_input and resets the chooser."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )
        portfolio_file = tmp_path / "portfolio.yaml"
        portfolio_file.write_text(PORTFOLIO_YAML)

        import_section = pw.display_import()
        file_chooser = import_section.children[1]
        filename_input = import_section.children[2]
        file_chooser.selected = str(portfolio_file)
        file_chooser.callback(file_chooser)
        assert filename_input.value == str(portfolio_file)

        import_controls_box = import_section.children[3]
        clear_button = import_controls_box.children[0]
        clear_button.click()

        assert filename_input.value == ""
        assert file_chooser.reset_calls == 1


class TestDisplayImportPathResolution:
    """Integration tests for the Import Portfolio widget's button handlers."""

    def test_import_full_path(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A full path (as FileChooser would supply) imports successfully."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )
        portfolio_file = tmp_path / "portfolio.yaml"
        portfolio_file.write_text(PORTFOLIO_YAML)

        import_section = pw.display_import()
        filename_input = import_section.children[2]
        filename_input.value = str(portfolio_file)

        import_controls_box = import_section.children[3]
        import_button = import_controls_box.children[2]
        import_button.click()

        text = capsys.readouterr().out
        assert "Successfully imported" in text
        assert len(mock_portfolio.positions) == 1

    def test_preview_full_path(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Preview reads the file without mutating the live portfolio."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )
        portfolio_file = tmp_path / "portfolio.yaml"
        portfolio_file.write_text(PORTFOLIO_YAML)

        import_section = pw.display_import()
        filename_input = import_section.children[2]
        filename_input.value = str(portfolio_file)

        import_controls_box = import_section.children[3]
        preview_button = import_controls_box.children[1]
        preview_button.click()

        text = capsys.readouterr().out
        assert "Previewing Portfolio" in text
        assert mock_portfolio.positions == []

    def test_import_missing_file(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A path that doesn't exist reports File not found, doesn't raise."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )

        import_section = pw.display_import()
        filename_input = import_section.children[2]
        filename_input.value = str(tmp_path / "missing.yaml")

        import_controls_box = import_section.children[3]
        import_button = import_controls_box.children[2]
        import_button.click()

        text = capsys.readouterr().out
        assert "File not found" in text

    def test_import_with_no_file_selected(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An empty filename_input guides the user to the file chooser."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )

        import_section = pw.display_import()
        import_controls_box = import_section.children[3]
        import_button = import_controls_box.children[2]
        import_button.click()

        text = capsys.readouterr().out
        assert "No file selected" in text

    def test_preview_with_no_file_selected(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An empty filename_input guides the user to the file chooser."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir,
            examples_dir,
            mock_portfolio,
            mock_changelog,
        )

        import_section = pw.display_import()
        import_controls_box = import_section.children[3]
        preview_button = import_controls_box.children[1]
        preview_button.click()

        text = capsys.readouterr().out
        assert "No file selected" in text

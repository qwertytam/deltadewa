"""Tests for deltadewa.widgets.export_controls import path resolution."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from deltadewa.persistence import PortfolioSerializer
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


def _make_widgets(
    export_dir: Path,
    examples_dir: Path,
    mock_portfolio: Mock,
    mock_changelog: Mock,
) -> PortfolioWidgets:
    serializer = PortfolioSerializer(export_dir, examples_dir)
    return PortfolioWidgets(mock_portfolio, serializer, mock_changelog)


class TestResolveImportPath:
    """Unit tests for ExportControlsMixin._resolve_import_path."""

    def test_existing_relative_path_wins_over_export_dir(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A path that exists as given is used, bypassing export_dir."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "external.yaml"
        outside_file.write_text(PORTFOLIO_YAML)

        monkeypatch.chdir(tmp_path)
        pw = _make_widgets(
            export_dir, examples_dir, mock_portfolio, mock_changelog
        )

        resolved = pw._resolve_import_path("outside/external.yaml")
        assert resolved == Path("outside/external.yaml")
        assert resolved.exists()

    def test_nonexistent_bare_name_falls_back_to_examples_dir(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
    ) -> None:
        """A bare name that doesn't exist anywhere still falls back."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir, examples_dir, mock_portfolio, mock_changelog
        )

        resolved = pw._resolve_import_path("missing.json")
        assert resolved == examples_dir / "missing.json"
        assert not resolved.exists()


class TestDisplayImportPathResolution:
    """Integration tests for the Import Portfolio widget's button handlers."""

    def test_import_bare_filename_inside_export_dir(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bare filenames continue to resolve against examples_dir."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        pw = _make_widgets(
            export_dir, examples_dir, mock_portfolio, mock_changelog
        )
        (examples_dir / "portfolio_book.yaml").write_text(PORTFOLIO_YAML)

        import_section = pw.display_import()
        import_controls_box = import_section.children[2]
        filename_input = import_section.children[1]
        filename_input.value = "portfolio_book.yaml"

        import_button = import_controls_box.children[2]
        import_button.click()

        text = capsys.readouterr().out
        assert "Successfully imported" in text
        assert len(mock_portfolio.positions) == 1

    def test_import_relative_path_outside_export_dir(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A relative path outside export_dir is now importable."""
        export_dir = tmp_path / "exports"
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "external.yaml").write_text(PORTFOLIO_YAML)

        examples_dir = tmp_path / "examples"
        monkeypatch.chdir(tmp_path)
        pw = _make_widgets(
            export_dir, examples_dir, mock_portfolio, mock_changelog
        )

        import_section = pw.display_import()
        import_controls_box = import_section.children[2]
        filename_input = import_section.children[1]
        filename_input.value = "outside/external.yaml"

        import_button = import_controls_box.children[2]
        import_button.click()

        text = capsys.readouterr().out
        assert "Successfully imported" in text
        assert len(mock_portfolio.positions) == 1

    def test_preview_relative_path_outside_export_dir(
        self,
        tmp_path: Path,
        mock_portfolio: Mock,
        mock_changelog: Mock,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The preview button gets the same path-resolution fix."""
        export_dir = tmp_path / "exports"
        examples_dir = tmp_path / "examples"
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "external.yaml").write_text(PORTFOLIO_YAML)

        monkeypatch.chdir(tmp_path)
        pw = _make_widgets(
            export_dir, examples_dir, mock_portfolio, mock_changelog
        )

        import_section = pw.display_import()
        import_controls_box = import_section.children[2]
        filename_input = import_section.children[1]
        filename_input.value = "outside/external.yaml"

        preview_button = import_controls_box.children[1]
        preview_button.click()

        text = capsys.readouterr().out
        assert "Previewing Portfolio" in text
        # Preview must not mutate the live portfolio.
        assert mock_portfolio.positions == []

"""Tests for deltadewa.persistence module - portfolio save/load operations."""

# pylint: disable=redefined-outer-name

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

from deltadewa import OptionPortfolio
from deltadewa.clock import program_trading_date
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.persistence import (
    YAML_AVAILABLE,
    PortfolioSerializer,
)
from deltadewa.reporting.audit import PortfolioLogger

# ========== Fixtures ==========


@pytest.fixture
def sample_portfolio() -> OptionPortfolio:
    """Create a test portfolio with 2 positions (call + put)."""
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.3,
        risk_free_rate=0.05,
        dividend_yield=0.02,
        underlying_quantity=100.0,
        symbol="TEST",
        default_exercise_style=ExerciseStyle.AMERICAN,
    )
    maturity = datetime.now(tz=UTC) + timedelta(days=30)
    portfolio.add_position(
        strike_price=100.0,
        maturity_date=maturity,
        quantity=1,
        option_type=OptionType.CALL,
    )
    portfolio.add_position(
        strike_price=95.0,
        maturity_date=maturity,
        quantity=-1,
        option_type=OptionType.PUT,
    )
    return portfolio


@pytest.fixture
def market_params() -> dict:
    """Create test market parameters dict."""
    return {
        "spot_price": 100.0,
        "volatility": 0.3,
        "risk_free_rate": 0.05,
        "dividend_yield": 0.02,
        "underlying_quantity": 100.0,
    }


# ========== PortfolioSerializer Tests ==========


class TestPortfolioSerializer:
    """Tests for PortfolioSerializer class."""

    def test_init_creates_export_dir(self, tmp_path) -> None:
        """Test that __init__ creates the export directory."""
        export_dir = tmp_path / "test_exports"
        assert not export_dir.exists()

        serializer = PortfolioSerializer(export_dir)

        assert export_dir.exists()
        assert serializer.export_dir == export_dir

    def test_detect_file_format_json(self) -> None:
        """Test format detection for .json files."""
        assert PortfolioSerializer.detect_file_format("test.json") == "json"
        assert (
            PortfolioSerializer.detect_file_format("/path/to/file.json")
            == "json"
        )
        assert (
            PortfolioSerializer.detect_file_format(Path("test.json")) == "json"
        )

    def test_detect_file_format_yaml(self) -> None:
        """Test format detection for .yaml and .yml files."""
        assert PortfolioSerializer.detect_file_format("test.yaml") == "yaml"
        assert PortfolioSerializer.detect_file_format("test.yml") == "yaml"
        assert (
            PortfolioSerializer.detect_file_format(Path("config.yaml"))
            == "yaml"
        )

    def test_detect_file_format_unsupported(self) -> None:
        """Test format detection returns None for unsupported extensions."""
        assert PortfolioSerializer.detect_file_format("test.txt") is None
        assert PortfolioSerializer.detect_file_format("test.csv") is None
        assert PortfolioSerializer.detect_file_format("test.pdf") is None
        assert PortfolioSerializer.detect_file_format("test") is None

    def test_list_available_files_empty(self, tmp_path) -> None:
        """Test listing files in empty directory."""
        serializer = PortfolioSerializer(tmp_path / "empty")
        files = serializer.list_available_files(serializer.export_dir)

        assert "json" in files
        assert "yaml" in files
        assert len(files["json"]) == 0
        assert len(files["yaml"]) == 0

    def test_list_available_files_with_files(self, tmp_path) -> None:
        """Test listing files when JSON and YAML files exist."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        # Create test files
        (export_dir / "portfolio1.json").write_text("{}")
        (export_dir / "portfolio2.json").write_text("{}")
        (export_dir / "config.yaml").write_text("")
        (export_dir / "config.yml").write_text("")
        (export_dir / "ignored.txt").write_text("")

        serializer = PortfolioSerializer(export_dir)
        files = serializer.list_available_files(export_dir)

        assert len(files["json"]) == 2
        assert len(files["yaml"]) == 2
        assert all(f.suffix == ".json" for f in files["json"])
        assert all(f.suffix in [".yaml", ".yml"] for f in files["yaml"])


# ========== JSON Roundtrip Tests ==========


class TestJsonRoundtrip:
    """Test JSON export/import roundtrip."""

    def test_export_to_json_creates_file(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Test that export_to_json creates the file."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        assert output_path.exists()
        assert output_path.suffix == ".json"
        assert output_path.name == "test.json"

    def test_export_to_json_leaves_no_partial_file_on_interruption(
        self,
        tmp_path,
        sample_portfolio,
        monkeypatch,
    ) -> None:
        """A write interrupted mid-dump must not corrupt or half-write.

        Simulates a crash inside ``json.dump`` — the destination must be
        left exactly as it was (absent, on a first write), and no stray
        temp file should remain.
        """
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = tmp_path / "test.json"

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated crash mid-write")

        monkeypatch.setattr(json, "dump", _boom)

        with pytest.raises(RuntimeError, match="simulated crash"):
            serializer.export_to_json(sample_portfolio, changelog, "test.json")

        assert not output_path.exists()
        assert not output_path.with_suffix(".json.tmp").exists()

    def test_json_roundtrip_preserves_market_params(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Export then import JSON — market params should match."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export
        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        # Import
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_params = result["market_params"]

        # Compare market parameters
        assert imported_params["spot_price"] == pytest.approx(
            sample_portfolio.spot_price,
        )
        assert imported_params["volatility"] == pytest.approx(
            sample_portfolio.volatility,
        )
        assert imported_params["risk_free_rate"] == pytest.approx(
            sample_portfolio.risk_free_rate,
        )
        assert imported_params["dividend_yield"] == pytest.approx(
            sample_portfolio.dividend_yield,
        )
        assert imported_params["symbol"] == sample_portfolio.symbol

    def test_json_roundtrip_preserves_positions(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Export then import JSON.

        Export/import — position count, strikes, types, quantities should match
        """
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export
        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        # Import
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]

        # Compare positions
        assert len(imported_portfolio.positions) == len(
            sample_portfolio.positions,
        )

        for orig_pos, imported_pos in zip(
            sample_portfolio.positions,
            imported_portfolio.positions,
            strict=False,
        ):
            assert imported_pos.option.strike_price == pytest.approx(
                orig_pos.option.strike_price,
            )
            assert (
                imported_pos.option.option_type == orig_pos.option.option_type
            )
            assert imported_pos.quantity == orig_pos.quantity

    def test_json_roundtrip_preserves_custom_volatility(self, tmp_path) -> None:
        """Export/import with custom per-position volatility."""
        # Create portfolio with custom volatility position
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.5,  # Custom volatility
        )

        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export
        output_path = serializer.export_to_json(
            portfolio,
            changelog,
            "test.json",
        )

        # Import
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]

        # Check custom volatility preserved
        assert len(imported_portfolio.positions) == 1
        assert imported_portfolio.positions[
            0
        ].option.volatility == pytest.approx(0.5)

    def test_json_roundtrip_preserves_entry_spot_and_date(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Export/import preserves each position's entry_spot/entry_date."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]

        for orig_pos, imported_pos in zip(
            sample_portfolio.positions,
            imported_portfolio.positions,
            strict=False,
        ):
            assert orig_pos.entry_spot is not None
            assert imported_pos.entry_spot == pytest.approx(orig_pos.entry_spot)
            assert imported_pos.entry_date == orig_pos.entry_date

    def test_json_import_legacy_file_defaults_entry_to_none(
        self,
        tmp_path,
    ) -> None:
        """Position dicts without entry_spot/entry_date import as None."""
        legacy_data = {
            "metadata": {"exported_at": "2020-01-01T00:00:00+00:00"},
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.2,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.0,
                "underlying_quantity": 0.0,
                "symbol": "TEST",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": "CALL",
                    "strike_price": 100.0,
                    "maturity_date": "2030-01-01T00:00:00+00:00",
                    "quantity": 1,
                    "contract_size": 100,
                    "volatility": 0.2,
                    "custom_volatility": False,
                    "exercise_style": "european",
                },
            ],
            "risk_metrics": {},
        }
        legacy_path = tmp_path / "legacy.json"
        legacy_path.write_text(json.dumps(legacy_data))

        serializer = PortfolioSerializer(tmp_path)
        result = serializer.import_from_json(legacy_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]

        assert len(imported_portfolio.positions) == 1
        assert imported_portfolio.positions[0].entry_spot is None
        assert imported_portfolio.positions[0].entry_date is None

    def test_json_roundtrip_preserves_exercise_style(self, tmp_path) -> None:
        """Regression (C2): a European book must reload European via JSON.

        The old export never wrote exercise_style and the import never read
        it, so a European (SPX) leg silently re-marked to American on reload.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=365),
            quantity=1,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        # Capture the European mark; an American re-mark would move the price
        # by the early-exercise premium, so this pins the style end-to-end.
        original_price = portfolio.positions[0].option.price()

        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = serializer.export_to_json(portfolio, changelog, "eu.json")
        imported = serializer.import_from_json(output_path)["portfolio"]

        pos = imported.positions[0]
        assert pos.exercise_style == ExerciseStyle.EUROPEAN
        assert pos.option.exercise_style == ExerciseStyle.EUROPEAN
        assert pos.option.price() == pytest.approx(original_price)

    def test_json_import_defaults_missing_exercise_style_from_arg(
        self,
        tmp_path,
    ) -> None:
        """Regression (C2): legacy legs honor the import default exercise style.

        A file lacking per-position exercise_style must adopt the caller's
        default (the program's IPS style) instead of the hardcoded American.
        """
        legacy_data = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.2,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.0,
                "underlying_quantity": 0.0,
                "symbol": "SPX",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": "PUT",
                    "strike_price": 90.0,
                    "maturity_date": "2030-01-01T00:00:00+00:00",
                    "quantity": 1,
                    "contract_size": 100,
                    "volatility": 0.2,
                    "custom_volatility": False,
                },
            ],
            "risk_metrics": {},
        }
        legacy_path = tmp_path / "legacy_spx.json"
        legacy_path.write_text(json.dumps(legacy_data))

        serializer = PortfolioSerializer(tmp_path)
        result = serializer.import_from_json(
            legacy_path,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        pos = result["portfolio"].positions[0]
        assert pos.exercise_style == ExerciseStyle.EUROPEAN
        assert pos.option.exercise_style == ExerciseStyle.EUROPEAN

    def test_import_from_json_without_portfolio_creation(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Test import_from_json with create_portfolio=False returns raw dict.

        Export a portfolio, then import with create_portfolio=False. Should
        return raw data dict without 'portfolio' key.
        """
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export
        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        # Import without creating portfolio
        result = serializer.import_from_json(
            output_path,
            create_portfolio=False,
        )

        # Should return raw data dict without 'portfolio' key
        assert "portfolio" not in result
        assert "market_parameters" in result
        assert "positions" in result
        assert isinstance(result, dict)
        assert "symbol" in result["market_parameters"]

    def test_import_from_json_missing_maturity_raises(self, tmp_path) -> None:
        """Test importing JSON.

        Test that importing JSON with missing maturity_date raises
        ValueError.
        """
        serializer = PortfolioSerializer(tmp_path)

        # Create invalid JSON file
        invalid_data = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": OptionType.CALL.value,
                    "strike_price": 100.0,
                    # Missing maturity_date
                    "quantity": 1,
                },
            ],
        }

        json_path = tmp_path / "invalid.json"
        with Path.open(json_path, "w", encoding="utf-8") as f:
            json.dump(invalid_data, f)

        with pytest.raises(ValueError, match="missing maturity date"):
            serializer.import_from_json(json_path, create_portfolio=True)

    def test_import_from_json_missing_strike_raises(self, tmp_path) -> None:
        """Test that importing JSON with missing strike_price raises ValueError.

        Importing the JSON should raise ValueError with message about missing
        strike price.
        """
        serializer = PortfolioSerializer(tmp_path)

        # Create invalid JSON file
        invalid_data = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": OptionType.CALL,
                    # Missing strike_price
                    "maturity_date": (
                        datetime.now(tz=UTC) + timedelta(days=30)
                    ).isoformat(),
                    "quantity": 1,
                },
            ],
        }

        json_path = tmp_path / "invalid.json"
        with Path.open(json_path, "w", encoding="utf-8") as f:
            json.dump(invalid_data, f)

        with pytest.raises(ValueError, match="missing strike price"):
            serializer.import_from_json(json_path, create_portfolio=True)

    def test_json_roundtrip_preserves_position_id(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Export then import JSON — position_id must survive the round-trip."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        original_ids = [p.position_id for p in sample_portfolio.positions]

        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]

        imported_ids = [p.position_id for p in imported_portfolio.positions]
        assert imported_ids == original_ids


# ========== YAML Roundtrip Tests ==========


@pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
class TestYamlRoundtrip:
    """Test YAML export/import roundtrip."""

    def test_export_to_yaml_creates_file(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Test that export_to_yaml creates the file."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = serializer.export_to_yaml(
            sample_portfolio,
            changelog,
            "test.yaml",
        )

        assert output_path is not None
        assert output_path.exists()
        assert output_path.suffix == ".yaml"
        assert output_path.name == "test.yaml"

    def test_yaml_roundtrip_preserves_market_params(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Export then import YAML — market params should match."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export
        output_path = serializer.export_to_yaml(
            sample_portfolio,
            changelog,
            "test.yaml",
        )

        # Import
        assert output_path is not None
        result = serializer.import_from_yaml(output_path)
        imported_params = result["market_params"]

        # Compare market parameters
        assert imported_params["spot_price"] == pytest.approx(
            sample_portfolio.spot_price,
        )
        assert imported_params["volatility"] == pytest.approx(
            sample_portfolio.volatility,
        )
        assert imported_params["risk_free_rate"] == pytest.approx(
            sample_portfolio.risk_free_rate,
        )
        assert imported_params["dividend_yield"] == pytest.approx(
            sample_portfolio.dividend_yield,
        )
        assert imported_params["symbol"] == sample_portfolio.symbol

    def test_yaml_roundtrip_preserves_positions(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Export then import YAML — positions should match."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export
        output_path = serializer.export_to_yaml(
            sample_portfolio,
            changelog,
            "test.yaml",
        )

        # Import
        assert output_path is not None
        result = serializer.import_from_yaml(output_path)
        imported_portfolio = result["portfolio"]

        # Compare positions
        assert len(imported_portfolio.positions) == len(
            sample_portfolio.positions,
        )

        for orig_pos, imported_pos in zip(
            sample_portfolio.positions,
            imported_portfolio.positions,
            strict=False,
        ):
            assert imported_pos.option.strike_price == pytest.approx(
                orig_pos.option.strike_price,
            )
            assert (
                imported_pos.option.option_type == orig_pos.option.option_type
            )
            assert imported_pos.quantity == orig_pos.quantity

    def test_yaml_roundtrip_preserves_exercise_style(self, tmp_path) -> None:
        """Regression (C2): European legs must reload European via YAML.

        YAML import already parsed exercise_style, but the shared export
        builder never wrote it, so the round-trip still lost the style.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=365),
            quantity=1,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        # Capture the European mark; an American re-mark would move the price
        # by the early-exercise premium, so this pins the style end-to-end.
        original_price = portfolio.positions[0].option.price()

        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = serializer.export_to_yaml(portfolio, changelog, "eu.yaml")

        assert output_path is not None
        imported = serializer.import_from_yaml(output_path)["portfolio"]

        pos = imported.positions[0]
        assert pos.exercise_style == ExerciseStyle.EUROPEAN
        assert pos.option.exercise_style == ExerciseStyle.EUROPEAN
        assert pos.option.price() == pytest.approx(original_price)

    def test_yaml_roundtrip_with_maturity_days(self, tmp_path) -> None:
        """Test YAML import with maturity_days instead of maturity_date."""
        # Create YAML with maturity_days
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "underlying_quantity": 100.0,
                "symbol": "TEST",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": OptionType.CALL.value,
                    "strike_price": 100.0,
                    "maturity_days": 30,
                    "quantity": 1,
                    "exercise_style": "european",
                },
            ],
        }

        yaml_path = tmp_path / "maturity_days.yaml"
        with Path.open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        serializer = PortfolioSerializer(tmp_path)
        result = serializer.import_from_yaml(yaml_path)
        imported_portfolio = result["portfolio"]

        # Verify portfolio created with correct maturity
        assert len(imported_portfolio.positions) == 1
        position = imported_portfolio.positions[0]

        # Check that maturity is approximately 30 days from now
        time_to_maturity = (
            position.option.maturity_date - datetime.now(tz=UTC)
        ).total_seconds() / 86400
        assert time_to_maturity == pytest.approx(30, abs=1)

    def test_yaml_valuation_date_pins_portfolio_and_relative_maturity(
        self,
        tmp_path,
    ) -> None:
        """An explicit as-of sets the valuation date *and* anchors maturities.

        Both halves matter: pinning only the portfolio's valuation date would
        leave ``maturity_days`` anchored on wall-clock now, so a fixture's
        time-to-expiry would still stretch by a day per day.
        """
        as_of = datetime(2026, 7, 26, tzinfo=UTC)
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "underlying_quantity": 100.0,
                "symbol": "TEST",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": OptionType.PUT.value,
                    "strike_price": 90.0,
                    "maturity_days": 548,
                    "quantity": 1,
                    "exercise_style": "european",
                },
                {
                    "option_type": OptionType.PUT.value,
                    "strike_price": 80.0,
                    "maturity_date": "2027-06-17",
                    "quantity": 1,
                    "exercise_style": "european",
                },
            ],
        }
        yaml_path = tmp_path / "pinned.yaml"
        with Path.open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        portfolio = PortfolioSerializer(tmp_path).import_from_yaml(
            yaml_path,
            valuation_date=as_of,
        )["portfolio"]

        assert portfolio.valuation_date == as_of
        relative, absolute = portfolio.positions
        # Relative maturity is anchored on the pin, not on today.
        assert relative.option.maturity_date == as_of + timedelta(days=548)
        # Absolute maturities are untouched by the pin.
        assert absolute.option.maturity_date == datetime(
            2027,
            6,
            17,
            tzinfo=UTC,
        )

    def test_yaml_valuation_date_defaults_to_program_date(
        self,
        tmp_path,
    ) -> None:
        """Omitting the as-of loads as of the program's trading date.

        Was ``datetime.now(tz=UTC)`` before #182, asserted to within 60
        seconds. The default is now midnight in the program timezone, so
        the assertion is on the date rather than the instant — a load at
        21:00 New York must still be the New York trading day, not the
        UTC one that has already rolled over.
        """
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "underlying_quantity": 100.0,
                "symbol": "TEST",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": OptionType.PUT.value,
                    "strike_price": 90.0,
                    "maturity_days": 30,
                    "quantity": 1,
                    "exercise_style": "european",
                },
            ],
        }
        yaml_path = tmp_path / "unpinned.yaml"
        with Path.open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        portfolio = PortfolioSerializer(tmp_path).import_from_yaml(yaml_path)[
            "portfolio"
        ]

        assert portfolio.valuation_date == program_trading_date()
        # And the relative maturity is anchored on that same as-of.
        assert portfolio.positions[
            0
        ].option.maturity_date == portfolio.valuation_date + timedelta(days=30)

    def test_yaml_import_without_position_id_gets_fresh_uuid(
        self,
        tmp_path,
    ) -> None:
        """Hand-authored YAML without position_id → auto-generated UUID."""
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "underlying_quantity": 0.0,
                "symbol": "TEST",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": OptionType.CALL.value,
                    "strike_price": 100.0,
                    "maturity_days": 30,
                    "quantity": 1,
                    "exercise_style": "european",
                    # deliberately no position_id key
                },
            ],
        }
        yaml_path = tmp_path / "no_id.yaml"
        with Path.open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        serializer = PortfolioSerializer(tmp_path)
        result = serializer.import_from_yaml(yaml_path)
        pos = result["portfolio"].positions[0]
        assert isinstance(pos.position_id, str)
        assert pos.position_id != ""


# ========== CSV Export Tests ==========


class TestCsvExport:
    """Test CSV export functionality."""

    def test_export_to_csv_creates_files(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Test that export creates both positions and risk CSV files."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        result = serializer.export_to_csv(sample_portfolio, changelog, "test")

        assert "positions" in result
        assert "risk" in result
        assert result["positions"].exists()
        assert result["risk"].exists()
        assert result["positions"].suffix == ".csv"
        assert result["risk"].suffix == ".csv"

    def test_csv_positions_content(self, tmp_path, sample_portfolio) -> None:
        """Test that positions CSV contains correct columns and data."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        result = serializer.export_to_csv(sample_portfolio, changelog, "test")

        # Read positions CSV
        df = pd.read_csv(result["positions"])

        # Check columns exist
        expected_columns = [
            "position_id",
            "option_type",
            "strike",
            "maturity",
            "quantity",
            "price",
            "delta",
            "gamma",
        ]
        for col in expected_columns:
            assert col in df.columns

        # Check row count matches positions
        assert len(df) == len(sample_portfolio.positions)

        # Check data types
        assert df["option_type"].iloc[0] in [OptionType.CALL, OptionType.PUT]
        assert df["quantity"].iloc[0] in [1, -1]

    def test_csv_risk_content(self, tmp_path, sample_portfolio) -> None:
        """Test that risk CSV contains summary stats."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        result = serializer.export_to_csv(sample_portfolio, changelog, "test")

        # Read risk CSV
        df = pd.read_csv(result["risk"])

        # Check structure
        assert "metric" in df.columns
        assert "value" in df.columns
        assert len(df) > 0

        # Check that common metrics are present
        metrics = df["metric"].tolist()
        assert "total_delta" in metrics or "portfolio_delta" in metrics


# ========== Universal Import Tests ==========


class TestUniversalImport:
    """Test import_portfolio auto-detection."""

    def test_import_portfolio_json(self, tmp_path, sample_portfolio) -> None:
        """Test auto-detection for JSON files."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export as JSON
        json_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        # Import using universal function
        result = serializer.import_portfolio(json_path)

        assert "portfolio" in result
        assert isinstance(result["portfolio"], OptionPortfolio)

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_import_portfolio_yaml(self, tmp_path, sample_portfolio) -> None:
        """Test auto-detection for YAML files."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()

        # Export as YAML
        yaml_path = serializer.export_to_yaml(
            sample_portfolio,
            changelog,
            "test.yaml",
        )

        # Import using universal function
        assert yaml_path is not None
        result = serializer.import_portfolio(yaml_path)

        assert "portfolio" in result
        assert isinstance(result["portfolio"], OptionPortfolio)

    def test_import_portfolio_unsupported_raises(self, tmp_path) -> None:
        """Test that unsupported format raises ValueError."""
        serializer = PortfolioSerializer(tmp_path)

        # Create a .txt file
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("not a portfolio")

        with pytest.raises(ValueError, match="Unsupported file format"):
            serializer.import_portfolio(txt_path)


# ========== Convenience Function Tests ==========


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_export_portfolio_to_json(self, tmp_path, sample_portfolio) -> None:
        """Test the convenience wrapper for JSON export."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            filename="convenience.json",
        )

        assert output_path.exists()
        assert output_path.name == "convenience.json"

    def test_export_portfolio_to_csv(self, tmp_path, sample_portfolio) -> None:
        """Test the convenience wrapper for CSV export."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        result = serializer.export_to_csv(
            sample_portfolio,
            changelog,
            filename="convenience.csv",
        )

        assert result["positions"].exists()
        assert result["risk"].exists()

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_export_portfolio_to_yaml(self, tmp_path, sample_portfolio) -> None:
        """Test the convenience wrapper for YAML export."""
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        output_path = serializer.export_to_yaml(
            sample_portfolio,
            changelog,
            filename="convenience.yaml",
        )

        assert output_path is not None
        assert output_path.exists()
        assert output_path.name == "convenience.yaml"

    def test_import_portfolio_from_json(
        self,
        tmp_path,
        sample_portfolio,
    ) -> None:
        """Test the convenience wrapper for JSON import."""
        # First export
        serializer = PortfolioSerializer(tmp_path)
        changelog = PortfolioLogger()
        json_path = serializer.export_to_json(
            sample_portfolio,
            changelog,
            "test.json",
        )

        # Import using convenience function
        result = serializer.import_from_json(
            json_path,
            create_portfolio=True,
        )

        assert "portfolio" in result
        assert isinstance(result["portfolio"], OptionPortfolio)


# ========== entry_premium Round-Trip Tests ==========


class TestEntryPremiumPersistence:
    """entry_premium survives JSON and YAML export/import round-trips."""

    def _make_portfolio_with_entry_premium(
        self,
        entry_premium: float | None = 3.75,
    ) -> OptionPortfolio:
        from datetime import UTC, datetime, timedelta

        from deltadewa.constants import ExerciseStyle, OptionType

        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            risk_free_rate=0.04,
            dividend_yield=0.0,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
            quantity=5,
            option_type=OptionType.PUT,
        )
        portfolio.positions[-1].entry_premium = entry_premium
        return portfolio

    def test_json_export_includes_entry_premium(
        self,
        tmp_path: Path,
    ) -> None:
        """entry_premium appears in the JSON output."""
        portfolio = self._make_portfolio_with_entry_premium(3.75)
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(
            portfolio,
            PortfolioLogger(),
            "ep.json",
        )
        data = json.loads(path.read_text())
        assert data["positions"][0]["entry_premium"] == pytest.approx(3.75)

    def test_json_export_entry_premium_null_for_legacy(
        self,
        tmp_path: Path,
    ) -> None:
        """entry_premium exports as null when not set."""
        portfolio = self._make_portfolio_with_entry_premium(None)
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(
            portfolio,
            PortfolioLogger(),
            "ep_null.json",
        )
        data = json.loads(path.read_text())
        assert data["positions"][0]["entry_premium"] is None

    def test_json_import_restores_entry_premium(
        self,
        tmp_path: Path,
    ) -> None:
        """Import restores entry_premium from JSON."""
        portfolio = self._make_portfolio_with_entry_premium(3.75)
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(
            portfolio,
            PortfolioLogger(),
            "ep_rt.json",
        )
        result = serializer.import_from_json(path)
        assert result["portfolio"].positions[0].entry_premium == pytest.approx(
            3.75,
        )

    def test_json_import_missing_key_is_none(self, tmp_path: Path) -> None:
        """Files without entry_premium key import with entry_premium=None."""
        from datetime import UTC, datetime, timedelta

        path = tmp_path / "legacy.json"
        maturity = (datetime.now(tz=UTC) + timedelta(days=60)).isoformat()
        legacy = {
            "metadata": {"version": "1.0"},
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.2,
                "risk_free_rate": 0.04,
                "dividend_yield": 0.0,
                "underlying_quantity": 0.0,
                "symbol": "SPX",
                "contract_size": 100,
            },
            "positions": [
                {
                    "option_type": "put",
                    "strike_price": 100.0,
                    "maturity_date": maturity,
                    "quantity": 5,
                    "contract_size": 100,
                    "volatility": 0.2,
                    "custom_volatility": False,
                    "exercise_style": "european",
                },
            ],
            "session_changelog": [],
        }
        path.write_text(json.dumps(legacy))
        serializer = PortfolioSerializer(tmp_path)
        result = serializer.import_from_json(path)
        assert result["portfolio"].positions[0].entry_premium is None

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_yaml_round_trip_entry_premium(self, tmp_path: Path) -> None:
        """entry_premium survives a YAML export/import round-trip."""
        portfolio = self._make_portfolio_with_entry_premium(2.10)
        serializer = PortfolioSerializer(tmp_path)
        yaml_path = serializer.export_to_yaml(
            portfolio,
            PortfolioLogger(),
            "ep_yaml.yaml",
        )
        assert yaml_path is not None
        result = serializer.import_from_yaml(yaml_path)
        assert result["portfolio"].positions[0].entry_premium == pytest.approx(
            2.10,
        )


# ========== contract_size round-trip ==========


class TestContractSizeRoundtrip:
    """contract_size is a required market_parameters field and survives I/O."""

    def _make_portfolio(self, contract_size: int) -> OptionPortfolio:
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        p = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            symbol="TEST",
            contract_size=contract_size,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        p.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        # Position with explicit override
        p.add_position(
            strike_price=90.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.PUT,
            contract_size=200,
        )
        return p

    def test_json_roundtrip_preserves_contract_size(
        self,
        tmp_path: Path,
    ) -> None:
        """JSON export/import preserves portfolio-level contract_size."""
        p = self._make_portfolio(50)
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(p, PortfolioLogger(), "cs.json")
        result = serializer.import_from_json(path)
        imported = result["portfolio"]
        assert imported.contract_size == 50
        # Position added without explicit cs inherits portfolio default
        assert imported.positions[0].contract_size == 50

    def test_json_explicit_position_contract_size_honoured(
        self,
        tmp_path: Path,
    ) -> None:
        """A per-position contract_size overriding the portfolio default.

        The override is written and read back correctly in per-position data.
        """
        p = self._make_portfolio(50)
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(p, PortfolioLogger(), "cs2.json")
        with Path.open(path, encoding="utf-8") as f:
            raw = json.load(f)
        # The per-position export should record 200 for the second position
        assert raw["positions"][1]["contract_size"] == 200

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_yaml_roundtrip_preserves_contract_size(
        self,
        tmp_path: Path,
    ) -> None:
        """YAML export/import preserves portfolio-level contract_size."""
        p = self._make_portfolio(50)
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_yaml(p, PortfolioLogger(), "cs.yaml")
        assert path is not None
        result = serializer.import_from_yaml(path)
        imported = result["portfolio"]
        assert imported.contract_size == 50
        assert imported.positions[0].contract_size == 50

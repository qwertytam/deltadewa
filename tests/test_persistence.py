"""Tests for deltadewa.persistence module - portfolio save/load operations."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from deltadewa import OptionPortfolio
from deltadewa.persistence import (
    PortfolioSerializer,
    load_config_yaml,
    detect_file_format,
    export_portfolio_to_json,
    export_portfolio_to_csv,
    export_portfolio_to_yaml,
    import_portfolio_from_json,
    import_from_yaml,
    list_available_portfolio_files,
    YAML_AVAILABLE,
)


# ========== Fixtures ==========


@pytest.fixture
def sample_portfolio():
    """Create a test portfolio with 2 positions (call + put)."""
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.3,
        risk_free_rate=0.05,
        dividend_yield=0.02,
        underlying_quantity=100.0,
    )
    maturity = datetime.now() + timedelta(days=30)
    portfolio.add_position(
        strike_price=100.0,
        maturity_date=maturity,
        quantity=1,
        option_type="call",
    )
    portfolio.add_position(
        strike_price=95.0,
        maturity_date=maturity,
        quantity=-1,
        option_type="put",
    )
    return portfolio


@pytest.fixture
def market_params():
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

    def test_init_creates_export_dir(self, tmp_path):
        """Test that __init__ creates the export directory."""
        export_dir = tmp_path / "test_exports"
        assert not export_dir.exists()
        
        serializer = PortfolioSerializer(export_dir)
        
        assert export_dir.exists()
        assert serializer.export_dir == export_dir

    def test_detect_file_format_json(self):
        """Test format detection for .json files."""
        assert PortfolioSerializer.detect_file_format("test.json") == "json"
        assert PortfolioSerializer.detect_file_format("/path/to/file.json") == "json"
        assert PortfolioSerializer.detect_file_format(Path("test.json")) == "json"

    def test_detect_file_format_yaml(self):
        """Test format detection for .yaml and .yml files."""
        assert PortfolioSerializer.detect_file_format("test.yaml") == "yaml"
        assert PortfolioSerializer.detect_file_format("test.yml") == "yaml"
        assert PortfolioSerializer.detect_file_format(Path("config.yaml")) == "yaml"

    def test_detect_file_format_unsupported(self):
        """Test format detection returns None for unsupported extensions."""
        assert PortfolioSerializer.detect_file_format("test.txt") is None
        assert PortfolioSerializer.detect_file_format("test.csv") is None
        assert PortfolioSerializer.detect_file_format("test.pdf") is None
        assert PortfolioSerializer.detect_file_format("test") is None

    def test_list_available_files_empty(self, tmp_path):
        """Test listing files in empty directory."""
        serializer = PortfolioSerializer(tmp_path / "empty")
        files = serializer.list_available_files()
        
        assert "json" in files
        assert "yaml" in files
        assert len(files["json"]) == 0
        assert len(files["yaml"]) == 0

    def test_list_available_files_with_files(self, tmp_path):
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
        files = serializer.list_available_files()
        
        assert len(files["json"]) == 2
        assert len(files["yaml"]) == 2
        assert all(f.suffix == ".json" for f in files["json"])
        assert all(f.suffix in [".yaml", ".yml"] for f in files["yaml"])


# ========== JSON Roundtrip Tests ==========


class TestJsonRoundtrip:
    """Test JSON export/import roundtrip."""

    def test_export_to_json_creates_file(self, tmp_path, sample_portfolio, market_params):
        """Test that export_to_json creates the file."""
        serializer = PortfolioSerializer(tmp_path)
        output_path = serializer.export_to_json(
            sample_portfolio, market_params, "test.json"
        )
        
        assert output_path.exists()
        assert output_path.suffix == ".json"
        assert output_path.name == "test.json"

    def test_json_roundtrip_preserves_market_params(
        self, tmp_path, sample_portfolio, market_params
    ):
        """Export then import JSON — market params should match."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export
        output_path = serializer.export_to_json(
            sample_portfolio, market_params, "test.json"
        )
        
        # Import
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_params = result["market_params"]
        
        # Compare market parameters
        assert imported_params["spot_price"] == pytest.approx(market_params["spot_price"])
        assert imported_params["volatility"] == pytest.approx(market_params["volatility"])
        assert imported_params["risk_free_rate"] == pytest.approx(market_params["risk_free_rate"])
        assert imported_params["dividend_yield"] == pytest.approx(market_params["dividend_yield"])

    def test_json_roundtrip_preserves_positions(
        self, tmp_path, sample_portfolio, market_params
    ):
        """Export then import JSON — position count, strikes, types, quantities should match."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export
        output_path = serializer.export_to_json(
            sample_portfolio, market_params, "test.json"
        )
        
        # Import
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]
        
        # Compare positions
        assert len(imported_portfolio.positions) == len(sample_portfolio.positions)
        
        for orig_pos, imported_pos in zip(
            sample_portfolio.positions, imported_portfolio.positions
        ):
            assert imported_pos.option.strike_price == pytest.approx(
                orig_pos.option.strike_price
            )
            assert imported_pos.option.option_type == orig_pos.option.option_type
            assert imported_pos.quantity == orig_pos.quantity

    def test_json_roundtrip_preserves_custom_volatility(self, tmp_path, market_params):
        """Export/import with custom per-position volatility."""
        # Create portfolio with custom volatility position
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.02,
        )
        maturity = datetime.now() + timedelta(days=30)
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type="call",
            volatility=0.5,  # Custom volatility
        )
        
        serializer = PortfolioSerializer(tmp_path)
        
        # Export
        output_path = serializer.export_to_json(portfolio, market_params, "test.json")
        
        # Import
        result = serializer.import_from_json(output_path, create_portfolio=True)
        imported_portfolio = result["portfolio"]
        
        # Check custom volatility preserved
        assert len(imported_portfolio.positions) == 1
        assert imported_portfolio.positions[0].option.volatility == pytest.approx(0.5)

    def test_import_from_json_without_portfolio_creation(
        self, tmp_path, sample_portfolio, market_params
    ):
        """Test import_from_json with create_portfolio=False returns raw dict."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export
        output_path = serializer.export_to_json(
            sample_portfolio, market_params, "test.json"
        )
        
        # Import without creating portfolio
        result = serializer.import_from_json(output_path, create_portfolio=False)
        
        # Should return raw data dict without 'portfolio' key
        assert "portfolio" not in result
        assert "market_parameters" in result
        assert "positions" in result
        assert isinstance(result, dict)

    def test_import_from_json_missing_maturity_raises(self, tmp_path):
        """Test that importing JSON with missing maturity_date raises ValueError."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Create invalid JSON file
        invalid_data = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
            },
            "positions": [
                {
                    "option_type": "call",
                    "strike_price": 100.0,
                    # Missing maturity_date
                    "quantity": 1,
                }
            ],
        }
        
        json_path = tmp_path / "invalid.json"
        with open(json_path, "w") as f:
            json.dump(invalid_data, f)
        
        with pytest.raises(ValueError, match="missing maturity date"):
            serializer.import_from_json(json_path, create_portfolio=True)

    def test_import_from_json_missing_strike_raises(self, tmp_path):
        """Test that importing JSON with missing strike_price raises ValueError."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Create invalid JSON file
        invalid_data = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
            },
            "positions": [
                {
                    "option_type": "call",
                    # Missing strike_price
                    "maturity_date": (datetime.now() + timedelta(days=30)).isoformat(),
                    "quantity": 1,
                }
            ],
        }
        
        json_path = tmp_path / "invalid.json"
        with open(json_path, "w") as f:
            json.dump(invalid_data, f)
        
        with pytest.raises(ValueError, match="missing strike price"):
            serializer.import_from_json(json_path, create_portfolio=True)


# ========== YAML Roundtrip Tests ==========


@pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
class TestYamlRoundtrip:
    """Test YAML export/import roundtrip."""

    def test_export_to_yaml_creates_file(self, tmp_path, sample_portfolio, market_params):
        """Test that export_to_yaml creates the file."""
        serializer = PortfolioSerializer(tmp_path)
        output_path = serializer.export_to_yaml(
            sample_portfolio, market_params, "test.yaml"
        )
        
        assert output_path.exists()
        assert output_path.suffix == ".yaml"
        assert output_path.name == "test.yaml"

    def test_yaml_roundtrip_preserves_market_params(
        self, tmp_path, sample_portfolio, market_params
    ):
        """Export then import YAML — market params should match."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export
        output_path = serializer.export_to_yaml(
            sample_portfolio, market_params, "test.yaml"
        )
        
        # Import
        result = serializer.import_from_yaml(output_path)
        imported_params = result["market_params"]
        
        # Compare market parameters
        assert imported_params["spot_price"] == pytest.approx(market_params["spot_price"])
        assert imported_params["volatility"] == pytest.approx(market_params["volatility"])
        assert imported_params["risk_free_rate"] == pytest.approx(market_params["risk_free_rate"])
        assert imported_params["dividend_yield"] == pytest.approx(market_params["dividend_yield"])

    def test_yaml_roundtrip_preserves_positions(
        self, tmp_path, sample_portfolio, market_params
    ):
        """Export then import YAML — positions should match."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export
        output_path = serializer.export_to_yaml(
            sample_portfolio, market_params, "test.yaml"
        )
        
        # Import
        result = serializer.import_from_yaml(output_path)
        imported_portfolio = result["portfolio"]
        
        # Compare positions
        assert len(imported_portfolio.positions) == len(sample_portfolio.positions)
        
        for orig_pos, imported_pos in zip(
            sample_portfolio.positions, imported_portfolio.positions
        ):
            assert imported_pos.option.strike_price == pytest.approx(
                orig_pos.option.strike_price
            )
            assert imported_pos.option.option_type == orig_pos.option.option_type
            assert imported_pos.quantity == orig_pos.quantity

    def test_yaml_roundtrip_with_maturity_days(self, tmp_path):
        """Test YAML import with maturity_days instead of maturity_date."""
        import yaml
        
        # Create YAML with maturity_days
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "underlying_quantity": 100.0,
                "symbol": "TEST",
            },
            "positions": [
                {
                    "option_type": "call",
                    "strike_price": 100.0,
                    "maturity_days": 30,
                    "quantity": 1,
                }
            ],
        }
        
        yaml_path = tmp_path / "maturity_days.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        serializer = PortfolioSerializer(tmp_path)
        result = serializer.import_from_yaml(yaml_path)
        imported_portfolio = result["portfolio"]
        
        # Verify portfolio created with correct maturity
        assert len(imported_portfolio.positions) == 1
        position = imported_portfolio.positions[0]
        
        # Check that maturity is approximately 30 days from now
        time_to_maturity = (
            position.option.maturity_date - datetime.now()
        ).total_seconds() / 86400
        assert time_to_maturity == pytest.approx(30, abs=1)


# ========== CSV Export Tests ==========


class TestCsvExport:
    """Test CSV export functionality."""

    def test_export_to_csv_creates_files(self, tmp_path, sample_portfolio):
        """Test that export creates both positions and risk CSV files."""
        serializer = PortfolioSerializer(tmp_path)
        result = serializer.export_to_csv(sample_portfolio, "test")
        
        assert "positions" in result
        assert "risk" in result
        assert result["positions"].exists()
        assert result["risk"].exists()
        assert result["positions"].suffix == ".csv"
        assert result["risk"].suffix == ".csv"

    def test_csv_positions_content(self, tmp_path, sample_portfolio):
        """Test that positions CSV contains correct columns and data."""
        import pandas as pd
        
        serializer = PortfolioSerializer(tmp_path)
        result = serializer.export_to_csv(sample_portfolio, "test")
        
        # Read positions CSV
        df = pd.read_csv(result["positions"])
        
        # Check columns exist
        expected_columns = [
            "position_id", "option_type", "strike", "maturity",
            "quantity", "price", "delta", "gamma"
        ]
        for col in expected_columns:
            assert col in df.columns
        
        # Check row count matches positions
        assert len(df) == len(sample_portfolio.positions)
        
        # Check data types
        assert df["option_type"].iloc[0] in ["call", "put"]
        assert df["quantity"].iloc[0] in [1, -1]

    def test_csv_risk_content(self, tmp_path, sample_portfolio):
        """Test that risk CSV contains summary stats."""
        import pandas as pd
        
        serializer = PortfolioSerializer(tmp_path)
        result = serializer.export_to_csv(sample_portfolio, "test")
        
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

    def test_import_portfolio_json(self, tmp_path, sample_portfolio, market_params):
        """Test auto-detection for JSON files."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export as JSON
        json_path = serializer.export_to_json(
            sample_portfolio, market_params, "test.json"
        )
        
        # Import using universal function
        result = serializer.import_portfolio(json_path)
        
        assert "portfolio" in result
        assert isinstance(result["portfolio"], OptionPortfolio)

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_import_portfolio_yaml(self, tmp_path, sample_portfolio, market_params):
        """Test auto-detection for YAML files."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Export as YAML
        yaml_path = serializer.export_to_yaml(
            sample_portfolio, market_params, "test.yaml"
        )
        
        # Import using universal function
        result = serializer.import_portfolio(yaml_path)
        
        assert "portfolio" in result
        assert isinstance(result["portfolio"], OptionPortfolio)

    def test_import_portfolio_unsupported_raises(self, tmp_path):
        """Test that unsupported format raises ValueError."""
        serializer = PortfolioSerializer(tmp_path)
        
        # Create a .txt file
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("not a portfolio")
        
        with pytest.raises(ValueError, match="Unsupported file format"):
            serializer.import_portfolio(txt_path)


# ========== load_config_yaml Tests ==========


@pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
class TestLoadConfigYaml:
    """Test the standalone load_config_yaml function."""

    def test_load_valid_config(self, tmp_path):
        """Test loading a valid YAML config with all required fields."""
        import yaml
        
        # Create valid YAML config
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
            },
            "positions": [
                {
                    "option_type": "call",
                    "strike_price": 100.0,
                    "maturity_date": "2024-12-31",
                    "quantity": 1,
                }
            ],
        }
        
        yaml_path = tmp_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        result = load_config_yaml(yaml_path)
        
        assert result is not None
        assert "market_parameters" in result
        assert "positions" in result
        assert result["market_parameters"]["spot_price"] == 100.0

    def test_load_missing_file_returns_none(self, tmp_path):
        """Test that a missing file returns None."""
        result = load_config_yaml(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_load_missing_required_param_returns_none(self, tmp_path):
        """Test that missing required market parameter returns None."""
        import yaml
        
        # Create YAML with missing volatility
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                # Missing volatility
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
            },
            "positions": [],
        }
        
        yaml_path = tmp_path / "invalid.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        result = load_config_yaml(yaml_path)
        assert result is None

    def test_load_invalid_structure_returns_none(self, tmp_path):
        """Test that a non-dict YAML returns None."""
        # Create YAML that's a list instead of dict
        yaml_path = tmp_path / "invalid.yaml"
        yaml_path.write_text("- item1\n- item2\n")
        
        result = load_config_yaml(yaml_path)
        assert result is None

    def test_load_missing_sections_returns_none(self, tmp_path):
        """Test that missing market_parameters or positions section returns None."""
        import yaml
        
        # Create YAML with missing positions section
        config = {
            "market_parameters": {
                "spot_price": 100.0,
                "volatility": 0.3,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
            }
            # Missing positions section
        }
        
        yaml_path = tmp_path / "incomplete.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        result = load_config_yaml(yaml_path)
        assert result is None


# ========== Convenience Function Tests ==========


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_export_portfolio_to_json(self, tmp_path, sample_portfolio, market_params):
        """Test the convenience wrapper for JSON export."""
        output_path = export_portfolio_to_json(
            sample_portfolio,
            market_params,
            filename="convenience.json",
            export_dir=str(tmp_path),
        )
        
        assert output_path.exists()
        assert output_path.name == "convenience.json"

    def test_export_portfolio_to_csv(self, tmp_path, sample_portfolio):
        """Test the convenience wrapper for CSV export."""
        result = export_portfolio_to_csv(
            sample_portfolio,
            filename_prefix="convenience",
            export_dir=str(tmp_path),
        )
        
        assert result["positions"].exists()
        assert result["risk"].exists()

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_export_portfolio_to_yaml(self, tmp_path, sample_portfolio, market_params):
        """Test the convenience wrapper for YAML export."""
        output_path = export_portfolio_to_yaml(
            sample_portfolio,
            market_params,
            filename="convenience.yaml",
            export_dir=str(tmp_path),
        )
        
        assert output_path.exists()
        assert output_path.name == "convenience.yaml"

    def test_import_portfolio_from_json(self, tmp_path, sample_portfolio, market_params):
        """Test the convenience wrapper for JSON import."""
        # First export
        serializer = PortfolioSerializer(tmp_path)
        json_path = serializer.export_to_json(
            sample_portfolio, market_params, "test.json"
        )
        
        # Import using convenience function
        result = import_portfolio_from_json(
            json_path,
            create_portfolio=True,
            export_dir=str(tmp_path),
        )
        
        assert "portfolio" in result
        assert isinstance(result["portfolio"], OptionPortfolio)

    def test_detect_file_format_convenience(self):
        """Test the module-level detect_file_format function."""
        assert detect_file_format("test.json") == "json"
        assert detect_file_format("test.yaml") == "yaml"
        assert detect_file_format("test.txt") is None

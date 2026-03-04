"""Tests for deltadewa.utils module - print and formatting utilities."""

from deltadewa.reporting.console import ConsoleReporter

# ruff: noqa: S101, ANN001


class TestPrintFormatting:
    """Tests for print formatting utilities."""

    def test_print_header(self, capsys) -> None:
        """Test print_header outputs border-title-border pattern."""
        reporter = ConsoleReporter(width=20)
        reporter.header("TEST", char="=")
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "=" * 20
        assert lines[1] == "TEST"
        assert lines[2] == "=" * 20

    def test_print_header_custom_char(self, capsys) -> None:
        """Test print_header with custom character."""
        reporter = ConsoleReporter(width=10)
        reporter.header("HEADER", char="*")
        captured = capsys.readouterr()
        assert "*" * 10 in captured.out

    def test_print_subheader(self, capsys) -> None:
        """Test print_subheader uses dashes."""
        reporter = ConsoleReporter(width=20)
        reporter.subheader("SUB")
        captured = capsys.readouterr()
        assert "-" * 20 in captured.out

    def test_print_divider(self, capsys) -> None:
        """Test print_divider outputs a single line."""
        reporter = ConsoleReporter(width=30)
        reporter.divider("-")
        captured = capsys.readouterr()
        assert captured.out.strip() == "-" * 30

    def test_print_section_with_content(self, capsys) -> None:
        """Test print_section with header and content."""
        reporter = ConsoleReporter(width=20)
        reporter.section("RESULTS", "Total: $100")
        captured = capsys.readouterr()
        assert "RESULTS" in captured.out
        assert "Total: $100" in captured.out

    def test_print_section_without_content(self, capsys) -> None:
        """Test print_section without content doesn't print None."""
        reporter = ConsoleReporter(width=20)
        reporter.section("RESULTS")
        captured = capsys.readouterr()
        assert "None" not in captured.out

    def test_print_key_value_left_align(self, capsys) -> None:
        """Test print_key_value with left alignment (default)."""
        reporter = ConsoleReporter()
        reporter.key_value("Spot", "$100.00")
        captured = capsys.readouterr()
        assert "Spot: $100.00" in captured.out

    def test_print_key_value_right_align(self, capsys) -> None:
        """Test print_key_value with right alignment."""
        reporter = ConsoleReporter()
        reporter.key_value("Spot", "$100", width=20, align="right")
        captured = capsys.readouterr()
        assert "Spot:" in captured.out
        assert "$100" in captured.out


class TestStatusAlerts:
    """Tests for status/alert print functions."""

    def test_print_success(self, capsys) -> None:
        """Test print_success outputs checkmark prefix."""
        reporter = ConsoleReporter()
        reporter.success("Done")
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "Done" in captured.out

    def test_print_warning(self, capsys) -> None:
        """Test print_warning outputs warning prefix."""
        reporter = ConsoleReporter()
        reporter.warning("Caution")
        captured = capsys.readouterr()
        assert "⚠" in captured.out
        assert "Caution" in captured.out

    def test_print_error(self, capsys) -> None:
        """Test print_error outputs error prefix."""
        reporter = ConsoleReporter()
        reporter.error("Failed")
        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "Failed" in captured.out

    def test_print_info(self, capsys) -> None:
        """Test print_info outputs info prefix."""
        reporter = ConsoleReporter()
        reporter.info("Note")
        captured = capsys.readouterr()
        assert "Note" in captured.out

    def test_custom_prefix(self, capsys) -> None:
        """Test that custom prefix overrides default."""
        reporter = ConsoleReporter()
        reporter.success("OK", prefix=">>")
        captured = capsys.readouterr()
        assert ">>" in captured.out
        assert "✓" not in captured.out


class TestTableUtilities:
    """Tests for table formatting functions."""

    def test_print_table_row(self, capsys) -> None:
        """Test print_table_row formats columns with widths."""
        reporter = ConsoleReporter()
        reporter.table_row(["A", "B", "C"], [10, 10, 10])
        captured = capsys.readouterr()
        assert "A" in captured.out
        assert "B" in captured.out
        assert "C" in captured.out

    def test_print_table_with_headers(self, capsys) -> None:
        """Test print_table outputs headers and data rows."""
        headers = ["Name", "Value"]
        data = [["Delta", "0.5"], ["Gamma", "0.01"]]
        reporter = ConsoleReporter()
        reporter.table(data, headers)
        captured = capsys.readouterr()
        assert "Name" in captured.out
        assert "Delta" in captured.out
        assert "Gamma" in captured.out

    def test_print_table_auto_width(self, capsys) -> None:
        """Test print_table auto-calculates column widths."""
        headers = ["X", "LongColumnName"]
        data = [["1", "value"]]
        reporter = ConsoleReporter()
        reporter.table(data, headers)
        captured = capsys.readouterr()
        assert "LongColumnName" in captured.out

    def test_print_table_custom_widths(self, capsys) -> None:
        """Test print_table with explicit widths."""
        headers = ["A", "B"]
        data = [["1", "2"]]
        reporter = ConsoleReporter()
        reporter.table(data, headers, widths=[15, 15])
        captured = capsys.readouterr()
        assert "A" in captured.out


class TestMetricSummary:
    """Tests for print_metric_summary."""

    def test_metric_summary_with_title(self, capsys) -> None:
        """Test print_metric_summary with title shows header and footer."""
        metrics = {"Delta": 125.5, "Gamma": 0.0045}
        reporter = ConsoleReporter(width=40)
        reporter.metric_summary(metrics, title="GREEKS")
        captured = capsys.readouterr()
        assert "GREEKS" in captured.out
        assert "Delta" in captured.out
        assert "Gamma" in captured.out

    def test_metric_summary_without_title(self, capsys) -> None:
        """Test print_metric_summary without title omits borders."""
        metrics = {"Delta": 125.5}
        reporter = ConsoleReporter()
        reporter.metric_summary(metrics)
        captured = capsys.readouterr()
        assert "Delta" in captured.out
        # Should NOT have the = border
        assert "=" * 80 not in captured.out

    def test_metric_summary_non_float(self, capsys) -> None:
        """Test that non-float values are printed as-is."""
        metrics = {"Status": "OK", "Count": 42}
        reporter = ConsoleReporter()
        reporter.metric_summary(metrics)
        captured = capsys.readouterr()
        assert "Status: OK" in captured.out
        assert "Count: 42" in captured.out


class TestProgressBar:
    """Tests for print_progress."""

    def test_progress_bar_output(self, capsys) -> None:
        """Test that progress bar outputs percentage."""
        reporter = ConsoleReporter()
        reporter.progress(50, 100, prefix="Test:", suffix="Done")
        captured = capsys.readouterr()
        assert "50.0%" in captured.out
        assert "Test:" in captured.out

    def test_progress_bar_complete(self, capsys) -> None:
        """Test that 100% progress prints newline."""
        reporter = ConsoleReporter()
        reporter.progress(100, 100)
        captured = capsys.readouterr()
        assert "100.0%" in captured.out

    def test_progress_bar_zero(self, capsys) -> None:
        """Test progress at 0%."""
        reporter = ConsoleReporter()
        reporter.progress(0, 100)
        captured = capsys.readouterr()
        assert "0.0%" in captured.out

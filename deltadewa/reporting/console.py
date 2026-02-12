"""
Console reporting utilities for DeltaDewa.

Handles formatted output to stdout/stderr with support for headers,
tables, status messages, and progress bars.
"""

from typing import Optional, Any, List, Dict
from IPython.display import clear_output
from deltadewa.formatters.values import format_number_auto_precision


class ConsoleReporter:
    """
    Builder for formatted console output.

    Encapsulates printing logic to allow for consistent formatting,
    configuration (e.g. width), and potential redirection of output.
    """

    def __init__(self, width: int = 80):
        self.width = width

    def header(self, title: str, char: str = "=") -> None:
        """Print a formatted section header."""
        print(char * self.width)
        print(title)
        print(char * self.width)

    def subheader(self, title: str) -> None:
        """Print a formatted subsection header."""
        self.header(title, char="-")

    def divider(self, char: str = "-") -> None:
        """Print a simple divider line."""
        print(char * self.width)

    def section(self, title: str, content: Optional[str] = None) -> None:
        """Print a complete section with header and optional content."""
        self.header(title)
        if content:
            print(content)

    def key_value(
        self, key: str, value: Any, width: int = 40, align: str = "left"
    ) -> None:
        """Print a key-value pair with aligned formatting."""
        if align == "right":
            print(f"{key}:{value:>{width - len(key) - 1}}")
        else:
            print(f"{key}: {value}")

    def metric_summary(
        self, metrics: Dict[str, Any], title: Optional[str] = None
    ) -> None:
        """Print a formatted summary of metrics."""
        if title:
            self.header(title)

        for key, value in metrics.items():
            if isinstance(value, float):
                print(f"{key}: {format_number_auto_precision(value)}")
            else:
                print(f"{key}: {value}")

        if title:
            self.divider(char="=")

    def success(self, message: str, prefix: str = "✓") -> None:
        """
        Print a success message.

        Args:
            message: Success message text
            prefix: Prefix symbol (default: '✓')
        """
        print(f"{prefix} {message}")

    def warning(self, message: str, prefix: str = "⚠") -> None:
        """
        Print a warning message.

        Args:
            message: Warning message text
            prefix: Prefix symbol (default: '⚠')
        """
        print(f"{prefix} {message}")

    def error(self, message: str, prefix: str = "✗") -> None:
        """
        Print an error message.

        Args:
            message: Error message text
            prefix: Prefix symbol (default: '✗')
        """
        print(f"{prefix} {message}")

    def info(self, message: str, prefix: str = "ℹ️") -> None:
        """
        Print an informational message.

        Args:
            message: Informational message text
            prefix: Prefix symbol (default: 'ℹ️')
        """
        print(f"{prefix}  {message}")

    def table_row(
        self, columns: List[Any], widths: List[int], separator: str = "|"
    ) -> None:
        """Print a formatted table row."""
        row = separator.join(
            f" {str(col):<{w-2}} " for col, w in zip(columns, widths)
        )
        print(row)

    def table(
        self,
        data: List[List[Any]],
        headers: List[str],
        widths: Optional[List[int]] = None,
    ) -> None:
        """Print a simple formatted table."""
        # Auto-calculate widths if not provided
        if widths is None:
            widths = []
            for i, header in enumerate(headers):
                max_width = len(str(header))
                for row in data:
                    if i < len(row):
                        max_width = max(max_width, len(str(row[i])))
                widths.append(max_width + 4)  # Add padding

        # Print header
        self.table_row(headers, widths)
        # Custom divider logic for tables (based on sum of widths)
        table_width = sum(widths) + len(widths) - 1
        print("-" * table_width)

        # Print data rows
        for row in data:
            self.table_row(row, widths)

    def clear_and_print(self, message: str, wait: bool = True) -> None:
        """Clear output and print a new message (useful in widgets)."""
        clear_output(wait=wait)
        print(message)

    def progress(
        self,
        current: int,
        total: int,
        prefix: str = "",
        suffix: str = "",
        length: int = 50,
    ) -> None:
        """
        Print a progress bar.

        Args:
            current: Current progress value
            total: Total value (progress will be current/total)
            prefix: Prefix text before progress bar (default: '')
            suffix: Suffix text after progress bar (default: '')
            length: Length of the progress bar in characters (default: 50)
        """
        percent = f"{100 * (current / float(total)):.1f}"
        filled_length = int(length * current // total)
        fill = "█"
        progress_bar = fill * filled_length + "-" * (length - filled_length)
        print(f"\r{prefix} |{progress_bar}| {percent}% {suffix}", end="")
        if current == total:
            print()

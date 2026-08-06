"""Console reporting utilities for DeltaDewa.

Handles formatted output to stdout/stderr with support for headers,
tables, status messages, and progress bars.

IPython is a notebook-only dependency (not in the production/`jobs`
image — see the M2.6 close-out) and is only needed by
``clear_and_print``, used from notebook widgets. The import is deferred
into that method, guarded like ``formatters.values``' matplotlib import,
so the rest of ``ConsoleReporter`` — and everything that transitively
imports this module via ``deltadewa.reporting``'s package ``__init__``,
including production code that only wants ``PortfolioLogger`` — stays
importable without it.
"""

from typing import Any

from deltadewa.formatters.values import format_number_auto_precision


class ConsoleReporter:
    """Builder for formatted console output.

    Encapsulates printing logic to allow for consistent formatting,
    configuration (e.g. width), and potential redirection of output.
    """

    def __init__(self, width: int = 80) -> None:
        """Initialize."""
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

    def section(self, title: str, content: str | None = None) -> None:
        """Print a complete section with header and optional content."""
        self.header(title)
        if content:
            print(content)

    def key_value(
        self,
        key: str,
        value: Any,  # ruff: ignore[any-type]  # {value:>N} format spec depends on runtime type; object won't work
        width: int = 40,
        align: str = "left",
    ) -> None:
        """Print a key-value pair with aligned formatting."""
        if align == "right":
            print(f"{key}:{value:>{width - len(key) - 1}}")
        else:
            print(f"{key}: {value}")

    def metric_summary(
        self,
        metrics: dict[str, Any],
        title: str | None = None,
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
        """Print a success message.

        Args:
            message: Success message text
            prefix: Prefix symbol (default: '✓')

        """
        print(f"{prefix} {message}")

    def warning(self, message: str, prefix: str = "⚠") -> None:
        """Print a warning message.

        Args:
            message: Warning message text
            prefix: Prefix symbol (default: '⚠')

        """
        print(f"{prefix} {message}")

    def error(self, message: str, prefix: str = "✗") -> None:
        """Print an error message.

        Args:
            message: Error message text
            prefix: Prefix symbol (default: '✗')

        """
        print(f"{prefix} {message}")

    def info(self, message: str, prefix: str = "ℹ️") -> None:  # ruff: ignore[ambiguous-unicode-character-string]
        """Print an informational message.

        Args:
            message: Informational message text
            prefix: Prefix symbol (default: 'ℹ️')

        """  # ruff: ignore[ambiguous-unicode-character-docstring]
        print(f"{prefix}  {message}")

    def table_row(
        self,
        columns: list[Any],
        widths: list[int],
        separator: str = "|",
    ) -> None:
        """Print a formatted table row."""
        row = separator.join(
            f" {col!s:<{w - 2}} "
            for col, w in zip(columns, widths, strict=False)
        )
        print(row)

    def table(
        self,
        data: list[list[Any]],
        headers: list[str],
        widths: list[int] | None = None,
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
        """Clear output and print a new message (useful in widgets).

        Notebook-only: imports IPython on call, not on module load, so
        the rest of this class stays usable without it.
        """
        try:
            # pylint: disable-next=import-outside-toplevel
            from IPython.display import clear_output  # deferred: notebook-only
        except ImportError as exc:
            raise ImportError(
                "IPython is required for ConsoleReporter.clear_and_print "
                "(notebook-only; not installed in the production image)",
            ) from exc
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
        """Print a progress bar.

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

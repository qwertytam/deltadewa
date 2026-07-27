# Convenience targets that are deliberately NOT part of the commit gate.
# The gate is: pytest / mypy deltadewa / ruff check . / pylint deltadewa.

# Shift matrix for the clock-shift determinism probe.
#
# DO NOT REMOVE the leading 0 or reorder it away from the front. +0 is the
# CONTROL run: the probe still substitutes datetime.datetime there, so a green
# +0 is what distinguishes real date drift from type-identity breakage in the
# shifted runs. Running the shifted entries without it makes every failure
# ambiguous.
CLOCK_SHIFT_MATRIX ?= 0 90 1000 3000

.PHONY: test-clockshift
test-clockshift:  ## Run the suite under the clock-shift matrix (slow, not in the gate)
	@for d in $(CLOCK_SHIFT_MATRIX); do \
		echo "=== clock shift +$$d days ==="; \
		CLOCK_SHIFT_DAYS=$$d poetry run pytest -q \
			-p tests.clockshift_plugin || exit 1; \
	done
	@echo "=== clock-shift matrix green: $(CLOCK_SHIFT_MATRIX) ==="

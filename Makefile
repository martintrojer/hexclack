.PHONY: gate install uninstall

# Formatting, lint, types and the full test suite.
gate:
	uv run ruff format --check . && uv run ruff check . && uv run ty check && uv run pytest

# Put hexclack and sd-music in ~/.local/bin (editable: source changes apply at once), then load the agent.
install:
	uv tool install --editable --force .
	hexclack install-agent

uninstall:
	hexclack uninstall-agent

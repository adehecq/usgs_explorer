# Contribute to project

First step clone the repo or fork it to create a pull request.
Next setup the development environnement :
```bash
# install hatch if you don't have it
pip install hatch

# you need to be in the usgs_explorer repo
hatch env create dev

# install the pre-commit hooks
hatch run dev:pre-commit install
```

## VSCode configuration (optional)

If you use VSCode, you can add the following to your `.vscode/settings.json` to enable format on save with Ruff (requires the [`charliermarsh.ruff`](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff) extension):

```json
{
    "[python]": {
        "editor.formatOnSave": true,
        "editor.defaultFormatter": "charliermarsh.ruff"
    }
}
```

The line length is set to 120 characters via `[tool.ruff]` in `pyproject.toml`.

## Before committing

Make sure the linter and all tests pass:
```bash
hatch run dev:ruff check .
hatch run dev:ruff format .

# tests run against the real USGS API and are skipped without credentials
export USGS_USERNAME=<your_username>
export USGS_TOKEN=<your_token>
hatch run dev:pytest
```

The pre-commit hooks also run `ruff --fix` and `ruff format` on staged files.

# Hermes Plugin Requirements

This repository must expose a Hermes plugin that can be installed from Git:

```sh
hermes plugins install Bandwidth/smartnumbers-hermes --enable
```

The repository is currently private. Users must have GitHub access to clone it.
For SSH-authenticated access, use:

```sh
hermes plugins install git@github.com:Bandwidth/smartnumbers-hermes.git --enable
```

## Repository Layout

Keep the plugin at the repository root for the most broadly compatible Git
install command:

```text
smartnumbers-hermes/
├── plugin.yaml
├── __init__.py
├── schemas.py          # If the plugin exposes tools
├── tools.py            # If the plugin exposes tools
├── after-install.md    # Recommended
├── README.md
└── tests/
```

## Required Plugin Contract

`plugin.yaml` must be at the plugin root and should include:

- `manifest_version: 1`
- A stable `name`, currently `smartnumbers`
- A semantic `version`
- A `description`
- `author`, when applicable
- `requires_env` for required environment variables or secrets
- `provides_tools` and `provides_hooks` for the capabilities registered by the plugin

`__init__.py` must define `register(ctx)`. The function registers the plugin's
tools, hooks, commands, or provider integration through the Hermes plugin API.

## Install And Enable Behavior

`hermes plugins install` shallow-clones the repository into:

```text
~/.hermes/plugins/<plugin-name>/
```

Third-party plugins are discovered but do not run until enabled. `--enable`
enables the plugin during installation; without it, Hermes prompts an
interactive user or requires a later command:

```sh
hermes plugins enable smartnumbers
```

Restart the Hermes gateway after enabling the plugin:

```sh
hermes gateway restart
```

## Configuration And Secrets

Declare required secrets in `plugin.yaml` using `requires_env`. During an
interactive install, Hermes prompts for missing values and writes them to:

```text
~/.hermes/.env
```

Use `after-install.md` to document configuration, environment variables,
verification, and restart steps. Hermes renders this file after installation.

## Dependencies

Git installation only clones plugin source. It does not run `pip`, `uv`, or
arbitrary setup scripts.

The plugin must either:

- Depend only on Python's standard library and dependencies already supplied by Hermes, or
- Document explicit installation of third-party dependencies into Hermes's Python environment in `after-install.md`.

A `pyproject.toml` with a `hermes_agent.plugins` entry point supports separate
pip distribution. It is not required for Git installation and does not cause
`hermes plugins install` to install dependencies.

## Validation

Before publishing, validate the plugin from a clean Hermes home:

```sh
hermes plugins install file:///absolute/path/to/smartnumbers-hermes --force --enable
hermes plugins list
```

Verify its declared tools, hooks, commands, or provider integration work, then
test installation from the GitHub repository using an account with access.

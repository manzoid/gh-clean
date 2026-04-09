# Releasing

`gh-clean` is currently intended to be released manually.

## Before releasing

Run the local verification steps:

```bash
python3 -m unittest discover -s tests -v
uv run gh-clean report --repo gh-clean-sandbox/sandbox --format table
```

If you also want a real-world validation pass, make sure the current
`gh` token is authorized for any SAML-protected organizations you plan to
test against.

## Build the package

Create source and wheel distributions:

```bash
python3 -m build
```

If `build` is not installed yet:

```bash
python3 -m pip install build
```

This will create artifacts in `dist/`.

## Smoke-test the built package

From a clean shell or virtual environment:

```bash
uvx --from dist/gh_clean-0.1.0-py3-none-any.whl gh-clean report --repo gh-clean-sandbox/sandbox
```

Or install the wheel locally:

```bash
python3 -m pip install dist/*.whl
gh-clean report --repo gh-clean-sandbox/sandbox
```

## Publish

If publishing to PyPI manually:

```bash
python3 -m pip install twine
python3 -m twine upload dist/*
```

## Suggested release checklist

1. Update version in `pyproject.toml`
2. Run tests
3. Run the sandbox report
4. Build distributions
5. Smoke-test the built package
6. Upload to PyPI
7. Create a GitHub release if desired

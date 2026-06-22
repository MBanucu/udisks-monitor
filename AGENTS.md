# AGENTS.md

Instructions for AI agents working on this repository.

## Commands

### Nix (recommended)

```bash
# Enter dev shell with all build and test dependencies
nix develop

# Run all tests inside the dev shell (107 tests, includes integration tests)
nix develop --command python -m unittest discover -s tests -v

# Build the package and run unit tests in sandbox
# Integration tests are skipped (no udisksctl in sandbox)
nix build --no-link --print-build-logs

# Run only parser/unit tests (no loop device operations needed)
nix develop --command python -m unittest discover -s tests -v \
  -k 'test_parser or test_pubsub or test_backend or test_dbus_backend'
```

### Non-Nix

With a venv that has the project installed in editable mode:

```bash
# Install (dbus-fast is a hard dependency)
python -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e .
pip install coverage

# Run all tests
python -m unittest discover -s tests -v

# Run tests with coverage
python -m coverage run -m unittest discover -s tests -v
python -m coverage report --skip-covered
```

## Release process

When creating a new release, the version number must be updated in all of
these files:

- `pyproject.toml` — `version = "X.Y.Z"`
- `default.nix` — `version = "X.Y.Z";`

Then:

1. Move the `[Unreleased]` changelog entries to a new `[X.Y.Z]` section in
   `CHANGELOG.md` with the release date.
2. Update the reference links at the bottom of `CHANGELOG.md`.
3. Commit the changes.
4. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`
5. Push the tag: `git push origin vX.Y.Z`
6. Create a GitHub Release from the tag, with the changelog entries as the
   release notes.

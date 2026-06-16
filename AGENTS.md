# AGENTS.md

Instructions for AI agents working on this repository.

## Commands

```bash
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

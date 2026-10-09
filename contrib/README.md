# contrib/

Community-contributed places, one directory per place: `contrib/OM-<ulid>/` holding `place.geojson` and `meta.json`
(the place id is `OM:<ulid>`). Add one with a pull request; how to make the id, the file formats, the licence rules and
what CI checks are in [CONTRIBUTING.md](../CONTRIBUTING.md).

- Every pull request touching `contrib/` is checked by `scripts/validate_contribution.py`
  (`.github/workflows/validate-contribution.yml`).
- Merged contributions are validated and stored here; publishing them as a `contributions` collection is future work.
- [`OM-01EXAMPE000000000000000000/`](OM-01EXAMPE000000000000000000) is the worked example (a made-up box off Point
  Conception, `"example": true`): documentation only, never published. Copy it as a starting point, give your copy a
  new id and drop the `example` key.

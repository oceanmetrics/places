"""the CLI degrades gracefully on a bare checkout (no catalog/staging)."""
import pytest

from gazetteer.cli import main


def test_check_without_staging_is_ok(tmp_path, capsys):
  """regression: `build.py check` on a fresh clone reports 'not built' and exits 0."""
  rc = main(["check", "--staging", str(tmp_path / "nope")])
  assert rc == 0
  assert "not built" in capsys.readouterr().out


def test_check_named_slug_without_staging_fails(tmp_path, capsys):
  """asking for one collection by name that was never built is an error."""
  rc = main(["check", "--slug", "boem_wind_leases", "--staging", str(tmp_path / "nope")])
  assert rc == 1
  assert "not built" in capsys.readouterr().out


def test_check_unknown_slug_exits(tmp_path):
  with pytest.raises(SystemExit):
    main(["check", "--slug", "no_such_layer", "--staging", str(tmp_path)])

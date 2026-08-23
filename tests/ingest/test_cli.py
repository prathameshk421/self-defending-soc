import pytest

from ingest.cli import build_parser, main
from ingest.schema_gen import SCHEMA_MODELS, generate_schema_text


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_schema_export_writes_generated_files(tmp_path, capsys):
    exit_code = main(["schema", "export", "--out", str(tmp_path)])
    assert exit_code == 0
    for filename, model in SCHEMA_MODELS.items():
        assert (tmp_path / filename).read_text("utf-8") == generate_schema_text(model)


def test_check_without_env_exits_1(monkeypatch, capsys):
    for var in list(__import__("os").environ):
        if var.startswith("INGEST_"):
            monkeypatch.delenv(var)
    exit_code = main(["check"])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_run_without_env_exits_1(monkeypatch, capsys):
    for var in list(__import__("os").environ):
        if var.startswith("INGEST_"):
            monkeypatch.delenv(var)
    exit_code = main(["run"])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err

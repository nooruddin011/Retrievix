import os

import pytest

from ahsr.config import ConfigError, Settings, load_dotenv


def test_dotenv_parsing_quotes_comments_and_no_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text(
        "# a comment\n"
        "AHSR_T_PLAIN=value   # inline comment\n"
        "AHSR_T_QUOTED=\"keeps # hash and trailing space \"\n"
        "export AHSR_T_EXPORT='single'\n"
        "AHSR_T_EMPTY=\n"
        "AHSR_T_EXISTING=from_file\n"
        "not a valid line\n")
    monkeypatch.setenv("AHSR_T_EXISTING", "from_env")
    for k in ("AHSR_T_PLAIN", "AHSR_T_QUOTED", "AHSR_T_EXPORT", "AHSR_T_EMPTY"):
        monkeypatch.delenv(k, raising=False)
    load_dotenv(f)
    assert os.environ["AHSR_T_PLAIN"] == "value"
    assert os.environ["AHSR_T_QUOTED"] == "keeps # hash and trailing space "
    assert os.environ["AHSR_T_EXPORT"] == "single" and os.environ["AHSR_T_EMPTY"] == ""
    assert os.environ["AHSR_T_EXISTING"] == "from_env"          # real environment always wins
    for k in ("AHSR_T_PLAIN", "AHSR_T_QUOTED", "AHSR_T_EXPORT", "AHSR_T_EMPTY"):
        os.environ.pop(k, None)


def test_invalid_numbers_name_the_variable(monkeypatch):
    monkeypatch.setenv("TOP_K", "lots")
    with pytest.raises(ConfigError, match="TOP_K"):
        Settings()
    monkeypatch.setenv("TOP_K", "0")
    with pytest.raises(ConfigError, match="between"):
        Settings()
    monkeypatch.setenv("TOP_K", "5")


def test_lists_and_bools(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example ,")
    monkeypatch.setenv("READ_ONLY", "yes")
    s = Settings()
    assert s.cors_origins == ["https://a.example", "https://b.example"] and s.read_only is True
    monkeypatch.setenv("READ_ONLY", "0")

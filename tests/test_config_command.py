from pathlib import Path

from commands import config


def test_write_keys_preserves_unowned_values_and_updates_owned(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_MODEL=demo\nJQ_USERNAME=old\n", encoding="utf-8")
    monkeypatch.setattr(config, "_env_path", lambda: env_path)

    config._write_keys({"JQ_USERNAME": "new", "JQ_PASSWORD": "secret"})

    content = env_path.read_text(encoding="utf-8")
    assert "LLM_MODEL=demo" in content
    assert "JQ_USERNAME=new" in content
    assert "JQ_PASSWORD=secret" in content
    assert oct(env_path.stat().st_mode & 0o777) == "0o600"

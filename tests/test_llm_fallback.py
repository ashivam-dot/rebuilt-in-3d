import pytest

from studio import llm


def test_a_model_that_will_not_start_falls_back_to_the_next(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "DIR", tmp_path)
    (tmp_path / "half.gguf.part").write_bytes(b"x")
    tried = []

    def start(self, name):
        tried.append(name)
        if name == "gemma-4-12b":
            raise RuntimeError("404 Not Found")

    monkeypatch.setattr(llm.Model, "_start", start)
    with llm.Model("gemma-4-12b") as m:
        assert m.name == "qwen3.5-35b-a3b"
    assert tried == ["gemma-4-12b", "qwen3.5-35b-a3b"] and not list(tmp_path.glob("*.part"))


def test_no_local_model_names_every_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "DIR", tmp_path)
    monkeypatch.setattr(llm.Model, "_start", lambda self, name: (_ for _ in ()).throw(OSError("No space left")))
    with pytest.raises(RuntimeError, match="gemma-4-12b: No space left.*qwen3.5-35b-a3b: No space left"):
        llm.Model("gemma-4-12b").__enter__()

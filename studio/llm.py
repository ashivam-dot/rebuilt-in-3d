"""A local open model (Gemma 4, Apache-2.0) served by llama.cpp on the runner: no account, no key, no quota.

Binaries and weights are downloaded once into work/cache/llm (kept by the Actions cache).
"""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import tarfile
import time
from pathlib import Path

import requests

from . import net

DIR = Path(__file__).resolve().parents[1] / "work" / "cache" / "llm"
RELEASE = "b11517"
MODELS = {
    "gemma-4-12b": ("google/gemma-4-12B-it-qat-q4_0-gguf", "gemma-4-12b-it-qat-q4_0.gguf"),
    "gemma-4-e4b": ("google/gemma-4-E4B-it-qat-q4_0-gguf", "gemma-4-E4B_q4_0-it.gguf"),
}
DEFAULT = os.environ.get("STUDIO_LLM", "gemma-4-12b")


def _download(url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": net.USER_AGENT}) as r:
        r.raise_for_status()
        with part.open("wb") as fh:
            for chunk in r.iter_content(1 << 22):
                fh.write(chunk)
    part.rename(path)
    return path


def server_binary() -> Path:
    folder = DIR / f"llama-{RELEASE}"
    exe = folder / "llama-server"
    if exe.exists():
        return exe
    arch = "macos-arm64" if platform.system() == "Darwin" else "ubuntu-x64"
    tgz = _download(f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/llama-{RELEASE}-bin-{arch}.tar.gz",
                    DIR / f"llama-{RELEASE}-{arch}.tar.gz")
    with tarfile.open(tgz) as t:
        t.extractall(DIR, filter="data")
    tgz.unlink()
    if not exe.exists():
        found = next(DIR.rglob("llama-server"), None)
        if found is None:
            raise RuntimeError("llama.cpp release has no llama-server")
        return found
    exe.chmod(0o755)
    return exe


def model_file(name: str = DEFAULT) -> Path:
    repo, file = MODELS[name]
    path = DIR / file
    if not path.exists():
        _download(f"https://huggingface.co/{repo}/resolve/main/{file}", path)
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Model:
    """with Model() as m: m.chat(messages, schema) -> parsed JSON."""

    def __init__(self, name: str = DEFAULT, ctx: int = 12288):
        self.name, self.ctx = name, ctx
        self.proc = None
        self.port = _free_port()

    def __enter__(self) -> "Model":
        exe, weights = server_binary(), model_file(self.name)
        threads = str(os.cpu_count() or 4)
        env = dict(os.environ, LD_LIBRARY_PATH=str(exe.parent))
        self.proc = subprocess.Popen(
            [str(exe), "-m", str(weights), "--port", str(self.port), "--host", "127.0.0.1", "-c", str(self.ctx),
             "-t", threads, "--jinja", "--no-webui"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("llama-server exited: " + (self.proc.stderr.read() or b"").decode()[-800:])
            try:
                if requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    return self
            except requests.RequestException:
                pass
            time.sleep(1)
        raise RuntimeError("llama-server did not become ready")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def chat(self, messages: list[dict], schema: dict | None = None, temperature: float = 0.7,
             max_tokens: int = 1200, think: bool = False) -> dict | str:
        # Gemma 4 thinks by default; on a CPU runner that costs minutes and can eat the whole token budget.
        body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "top_p": 0.95,
                "chat_template_kwargs": {"enable_thinking": think}}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema,
                                                                              "strict": True}}
        r = requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=body, timeout=1800)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        return json.loads(text) if schema else text

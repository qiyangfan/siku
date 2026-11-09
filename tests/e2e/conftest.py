"""E2E 夹具：fake 三通道端点 + 真实 `siku serve` 子进程（五段接线回归）。

进程卫生：serve 以独立进程组启动，teardown 先 SIGTERM 后 SIGKILL，失败路径同样
不留孤儿（复用 scripts/smoke_clean_env.py 的先例模式）。通道经 serve 既有
`--*-base-url` CLI 契约注入 fake 端点，零新机制。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fake_channels import EMBEDDING_DIMENSIONS, FakeChannelServer

SEED_MARKER = "E2E-SEED-FACT-c41d7a"
SEED_MD_NAME = "seed-note.md"
SEED_PDF_NAME = "seed-report.pdf"
SEED_QUERY = "墨丘山的灵晶脉由谁开采"
SEED_QUESTION = "灵晶脉的开采权归属？"
API_KEY_ENV = "SIKU_E2E_PLACEHOLDER_KEY"
BOOT_TIMEOUT_SECS = 60.0
# 端口选号与 serve 实际绑定之间隔着进程启动空窗（import siku.cli 秒级），
# 临时端口可能被无关连接占用——提前退出时换端口重试，绑定冲突类 flake 自愈。
BOOT_ATTEMPTS = 3

SEED_MD_TEXT = f"""# 锡库星考察笔记

{SEED_MARKER}：锡库星北麓的墨丘山藏有罕见的灵晶脉，开采权归垦务局所有。

## 备注

本文件是 CI E2E 冒烟的种子事实唯一来源，断言全部锚定上述标记。
"""

SEED_PDF_PAGES = ("墨丘山地质勘察报告。本页记录锡库星北麓岩层样本的初步观察，供后续钻探参考。",)


@pytest.fixture(scope="session")
def fake_server() -> FakeChannelServer:
    server = FakeChannelServer(seed_marker=SEED_MARKER)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def seed_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """种子语料：markdown（种子事实唯一来源）+ 小 PDF（钉住 pypdf 路径）。"""
    from tests.document_fixtures import make_text_pdf

    root = tmp_path_factory.mktemp("seed-corpus")
    markdown_path = root / SEED_MD_NAME
    markdown_path.write_text(SEED_MD_TEXT, encoding="utf-8")
    pdf_path = make_text_pdf(root / SEED_PDF_NAME, SEED_PDF_PAGES)
    return {"markdown": markdown_path, "pdf": pdf_path}


class ServeProcess:
    """已就绪的 serve 子进程句柄：base_url 供编排断言，日志供失败诊断。"""

    def __init__(self, base_url: str, process: subprocess.Popen[bytes], log_path: Path) -> None:
        self.base_url = base_url
        self._process = process
        self._log_path = log_path

    def log_tail(self, limit: int = 2000) -> str:
        try:
            return self._log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return "<日志文件不可读>"


@pytest.fixture(scope="module")
def serve(
    fake_server: FakeChannelServer,
    tmp_path_factory: pytest.TempPathFactory,
) -> ServeProcess:
    vault = tmp_path_factory.mktemp("vault")
    data_dir = tmp_path_factory.mktemp("data")
    env = _clean_env(tmp_path_factory)
    failures: list[str] = []
    for attempt in range(1, BOOT_ATTEMPTS + 1):
        log_path = tmp_path_factory.mktemp("serve-logs") / f"serve-attempt-{attempt}.log"
        port = _free_port()
        command = _serve_command(port, vault, data_dir, fake_server.base_url)
        with log_path.open("wb") as log_file:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=Path(__file__).resolve().parent.parent.parent,
                env=env,
                start_new_session=True,
            )
            serve_handle = ServeProcess(f"http://127.0.0.1:{port}", process, log_path)
            try:
                _wait_until_ready(serve_handle)
            except ServeBootError as exc:
                _terminate(process)
                failures.append(
                    f"第 {attempt} 次启动失败（{exc}）\n日志尾：\n{serve_handle.log_tail()}"
                )
                continue
            try:
                yield serve_handle
            finally:
                _terminate(process)
            return
    pytest.fail(f"siku serve 连续 {BOOT_ATTEMPTS} 次启动失败。\n" + "\n".join(failures))


class ServeBootError(Exception):
    """serve 启动失败（提前退出或就绪超时）；日志尾由夹具统一附上。"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve_command(port: int, vault: Path, data_dir: Path, fake_base_url: str) -> list[str]:
    """经既有 CLI 契约启动 serve；三通道全部显式指向 fake 端点。"""
    return [
        sys.executable,
        "-c",
        "from siku.cli import app; app()",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--vault",
        str(vault),
        "--data-dir",
        str(data_dir),
        "--llm-base-url",
        fake_base_url,
        "--llm-model",
        "fake-llm",
        "--api-key-env",
        API_KEY_ENV,
        "--embedding-base-url",
        fake_base_url,
        "--embedding-model",
        "fake-embed",
        "--embedding-api-key-env",
        API_KEY_ENV,
        "--embedding-dimensions",
        str(EMBEDDING_DIMENSIONS),
        "--rerank-base-url",
        fake_base_url,
        "--rerank-model",
        "fake-rerank",
        "--rerank-api-key-env",
        API_KEY_ENV,
    ]


def _clean_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """干净环境：剥掉 DASHSCOPE_API_KEY（假红源）与一切 SIKU_* 注入，并把平台配置
    目录指进临时区——分层配置路径派生自 HOME/XDG/APPDATA（model_supply.py），不指
    的话 serve 会读到宿主真实 config.toml，环境不密封。"""
    home = tmp_path_factory.mktemp("hermetic-home")
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "DASHSCOPE_API_KEY" and not key.startswith("SIKU_")
    }
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home)
    env["APPDATA"] = str(home)
    env[API_KEY_ENV] = "e2e-placeholder-key"
    return env


def _wait_until_ready(serve_handle: ServeProcess) -> None:
    deadline = time.monotonic() + BOOT_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if serve_handle._process.poll() is not None:
            raise ServeBootError(f"提前退出(exit={serve_handle._process.returncode})")
        try:
            response = httpx.get(f"{serve_handle.base_url}/api/health", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    _force_kill(serve_handle._process)
    raise ServeBootError(f"{BOOT_TIMEOUT_SECS}s 内未就绪")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        _force_kill(process)


def _force_kill(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass

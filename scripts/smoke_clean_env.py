"""冻结 sidecar 的干净环境摄取冒烟（ADR-0013 验收证据）。

在「干净 PATH、无模型缓存、网络指向黑洞代理」的环境中启动真实冻结 sidecar，
经 HTTP 摄取四类现代文档并核对投影/锚点，同时验证扫描件 PDF 与旧二进制
Office 的可行动失败。索引/图谱/Wiki 属 BYOK 阶段，不在本冒烟范围。

用法：

    uv run python scripts/smoke_clean_env.py [sidecar-dir]
"""

from __future__ import annotations

import io
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIDECAR = REPO_ROOT / "ui" / "src-tauri" / "binaries" / "siku-sidecar"
# 网络黑洞：任何意外的运行期下载/联网尝试都会立即失败并暴露
BLACKHOLE_PROXY = "http://127.0.0.1:9"
PORT = 8765
HEALTH_TIMEOUT_SECS = 60.0


class SmokeFailureError(RuntimeError):
    """冒烟断言失败。"""


def build_fixtures(fixtures_dir: Path) -> dict[str, Path]:
    """用开发环境生成四类结构真实文档（生成工具不进被测环境）。"""
    from openpyxl import Workbook
    from pptx import Presentation
    from pptx.util import Inches
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, Path] = {}

    pdf_buffer = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    renderer = canvas.Canvas(pdf_buffer)
    for text in ("冒烟第一页：中文与 English", None, "冒烟第三页"):
        if text is not None:
            renderer.setFont("STSong-Light", 12)
            renderer.drawString(72, 720, text)
        renderer.showPage()
    renderer.save()
    fixtures["pdf"] = fixtures_dir / "冒烟报告.pdf"
    fixtures["pdf"].write_bytes(pdf_buffer.getvalue())

    scanned_buffer = io.BytesIO()
    scanned = canvas.Canvas(scanned_buffer)
    scanned.showPage()
    scanned.save()
    scanned_pdf = fixtures_dir / "扫描件.pdf"
    source = PdfReader(io.BytesIO(scanned_buffer.getvalue()))
    writer = PdfWriter()
    for page in source.pages:
        writer.add_page(page)
    with scanned_pdf.open("wb") as handle:
        writer.write(handle)
    fixtures["scanned_pdf"] = scanned_pdf

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2))
    box.text_frame.text = "冒烟幻灯片要点"
    fixtures["pptx"] = fixtures_dir / "冒烟演示.pptx"
    presentation.save(fixtures["pptx"])

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "冒烟数据"
    worksheet.append(["列一", "列二"])
    worksheet.append(["值", 2])
    fixtures["xlsx"] = fixtures_dir / "冒烟工作簿.xlsx"
    workbook.save(fixtures["xlsx"])

    legacy = fixtures_dir / "旧文档.doc"
    legacy.write_bytes(b"legacy binary placeholder")
    fixtures["legacy_doc"] = legacy

    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise SmokeFailureError("dev environment needs pandoc to generate the DOCX fixture")
    docx = fixtures_dir / "冒烟文档.docx"
    result = subprocess.run(
        [pandoc, "-f", "gfm", "-t", "docx", "-o", str(docx)],
        input="# 冒烟标题\n\n正文段落",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not docx.exists():
        raise SmokeFailureError(f"failed to generate DOCX fixture: {result.stderr}")
    fixtures["docx"] = docx
    return fixtures


def request_json(
    method: str, path: str, payload: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_for_health(deadline: float) -> None:
    while time.time() < deadline:
        try:
            status, _ = request_json("GET", "/api/health")
            if status == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    raise SmokeFailureError("sidecar did not become healthy in time")


def main() -> None:
    sidecar_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SIDECAR
    exe = sidecar_dir / "siku-sidecar"
    if not exe.is_file():
        raise SystemExit(f"sidecar executable not found: {exe}")
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="siku-clean-smoke-") as workdir_raw:
        work = Path(workdir_raw)
        fixtures = build_fixtures(work / "fixtures")
        vault = work / "vault"
        data_dir = work / "data"
        home = work / "home"
        home.mkdir()
        # 干净环境：PATH 只有系统底线（无 brew/无 pandoc），HOME 隔离配置文件，
        # 代理指向黑洞使任何意外联网立即失败
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "TMPDIR": tempfile.gettempdir(),
            "HTTP_PROXY": BLACKHOLE_PROXY,
            "HTTPS_PROXY": BLACKHOLE_PROXY,
            "http_proxy": BLACKHOLE_PROXY,
            "https_proxy": BLACKHOLE_PROXY,
        }
        process = subprocess.Popen(
            [
                str(exe),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
                "--vault",
                str(vault),
                "--data-dir",
                str(data_dir),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for_health(time.time() + HEALTH_TIMEOUT_SECS)
            print("[smoke] sidecar healthy in clean environment (PATH=/usr/bin:/bin, no config)")
            expected_anchors = {
                "pdf": ("page:1", "page:3"),
                "docx": ("content",),
                "pptx": ("slide:1",),
                "xlsx": ("sheet:冒烟数据",),
            }
            for kind in ("pdf", "docx", "pptx", "xlsx"):
                status, payload = request_json(
                    "POST", "/api/ingest", {"source": str(fixtures[kind])}
                )
                if status != 200 or payload.get("created") != 1:
                    failures.append(f"{kind} ingest failed: {status} {payload}")
                    continue
                notes = sorted((vault / "notes").glob("*.md"))
                note_text = "\n".join(path.read_text(encoding="utf-8") for path in notes)
                anchors = expected_anchors[kind]
                # 每类单独核对：重置 notes 目录（冒烟逐类重建 vault）
                if not all(anchor in note_text for anchor in anchors):
                    failures.append(f"{kind} projection missing anchors {anchors}")
                shutil.rmtree(vault, ignore_errors=True)
                print(f"[smoke] {kind}: ingested, projection anchors {anchors} verified")

            status, payload = request_json(
                "POST", "/api/ingest", {"source": str(fixtures["scanned_pdf"])}
            )
            if status != 422 or payload.get("code") != "scanned_pdf_no_text":
                failures.append(f"scanned pdf not rejected actionably: {status} {payload}")
            else:
                print("[smoke] scanned pdf rejected with scanned_pdf_no_text (actionable)")

            status, payload = request_json(
                "POST", "/api/ingest", {"source": str(fixtures["legacy_doc"])}
            )
            if status != 422 or payload.get("code") != "legacy_office_format":
                failures.append(f"legacy .doc not rejected actionably: {status} {payload}")
            else:
                print("[smoke] legacy .doc rejected with legacy_office_format (actionable)")
        finally:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if failures:
        for failure in failures:
            print(f"[smoke] FAIL: {failure}")
        raise SystemExit(1)
    print("[smoke] clean-environment sidecar smoke PASSED")


if __name__ == "__main__":
    main()

"""siku 命令行入口。"""

from pathlib import Path
from typing import Annotated

import typer

from siku import __version__
from siku.ingest import IngestError, ingest_path

app = typer.Typer(
    name="siku",
    help="siku（四库）—— 本地优先的个人知识库：万能摄取、知识图谱、LLM wiki、自然语言问答。",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """siku 命令行入口。"""


@app.command()
def version() -> None:
    """显示版本号。"""
    typer.echo(f"siku {__version__}")


@app.command()
def ingest(
    source: Annotated[Path, typer.Argument(..., help="待摄取的文件或目录。")],
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = Path("vault"),
) -> None:
    """将文档摄取为本地 Markdown 事实层。"""
    try:
        report = ingest_path(source, vault)
    except IngestError as exc:
        typer.echo(f"摄取失败: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        "摄取完成: "
        f"created={report.created} updated={report.updated} "
        f"skipped={report.skipped} ignored={report.ignored}"
    )


if __name__ == "__main__":
    app()

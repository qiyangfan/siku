"""siku 命令行入口。"""

import typer

from siku import __version__

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


if __name__ == "__main__":
    app()

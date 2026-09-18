"""从 Release 资产生成 Homebrew Cask 定义（siku.rb）。

产物 URL、版本与 checksum 全部来自已上传的 Release 资产文件本身，保证三者
同源一致；macOS 双架构 DMG 各自提供 sha256（cask 的 arm/intel 分支）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CAVEATS = """\
    本安装包为未签名（unsigned）构建：首次打开可能被 macOS Gatekeeper 拦截，\\
    需在"系统设置 → 隐私与安全性"中手动放行。签名、公证与自动更新属于 Phase 6。"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_dmg(assets: Path, *patterns: str) -> Path:
    for pattern in patterns:
        matches = sorted(assets.glob(pattern))
        if matches:
            return matches[0]
    raise SystemExit(f"Release 资产缺少 DMG（{patterns}）：{sorted(assets.glob('*.dmg'))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True, help="Release 资产目录")
    parser.add_argument("--version", required=True, help="与 tag 一致的版本号")
    parser.add_argument(
        "--repo",
        default="qiyangfan/siku",
        help="Release 所在 GitHub 仓库（owner/name）",
    )
    parser.add_argument("--out", type=Path, required=True, help="Cask 输出文件路径")
    args = parser.parse_args()

    # Tauri macOS DMG 命名：siku_<版本>_aarch64.dmg / siku_<版本>_x64.dmg
    # （兼容带完整 triple 的命名变体）
    arm = find_dmg(args.assets, "*aarch64*.dmg", "*aarch64-apple-darwin*.dmg")
    intel = find_dmg(args.assets, "*x64*.dmg", "*x86_64*.dmg")

    cask = f"""\
cask "siku" do
  version "{args.version}"

  sha256 arm:   "{sha256(arm)}",
         intel: "{sha256(intel)}"

  url "https://github.com/{args.repo}/releases/download/v#{{version}}/{arm.name}"
  name "siku"
  desc "本地优先的个人知识库：万能摄取、知识图谱、LLM wiki、自然语言问答"
  homepage "https://github.com/{args.repo}"

  app "siku.app"

  caveats <<~EOS
{CAVEATS}
  EOS
end
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(cask, encoding="utf-8")
    print(json.dumps({"cask": str(args.out), "arm": arm.name, "intel": intel.name}))


if __name__ == "__main__":
    main()

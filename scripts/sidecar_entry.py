"""PyInstaller 构建入口：仅做一层转发，业务语义见 siku.sidecar。"""

from __future__ import annotations

from siku.sidecar import main

if __name__ == "__main__":
    main()

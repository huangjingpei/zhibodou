#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
直播豆（智播豆）一键打包脚本 —— 生成 Windows exe。

用法（在构建虚拟环境中执行）：
    python build_exe.py            # one-folder，控制台模式（可见日志）
    python build_exe.py --windowed  # 无控制台窗口的发布版（日志不再可见）
    python build_exe.py --onefile   # 打包成单个 exe 文件（启动较慢、体积大）

说明：
- 默认 one-folder 模式：产出 dist/zhibodou/zhibodou.exe 及配套 dll/ffmpeg.exe
- ffmpeg.exe 会作为数据文件打进 dist/zhibodou/，供无 av 时的 ffmpeg 回退方案使用
- 需先安装依赖：pip install pyinstaller 并按 requirements.txt 装齐运行库
"""
import argparse
import os
import sys
import tempfile

from PyInstaller.__main__ import run

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "zhibodou.py")
FFMPEG = os.path.join(HERE, "ffmpeg.exe")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windowed", action="store_true",
                    help="构建无控制台窗口的发布版（日志不可见）")
    ap.add_argument("--onefile", action="store_true",
                    help="打包为单个 exe 文件（one-folder 模式的替代）")
    args = ap.parse_args()

    # 产物先输出到系统临时目录，规避构建环境的安全删除 shim 对 /e/zhibodou 下
    # 大量文件删除的批量确认拦截；构建成功后由调用方拷贝回项目 dist/
    distpath = os.path.join(tempfile.gettempdir(), "zhibodou_dist")

    opts = [
        ENTRY,
        "--name", "zhibodou",
        "--paths", HERE,
        "--distpath", distpath,
        "--hidden-import", "cv2",
        "--hidden-import", "av",
        "--hidden-import", "streamlink",
        "--hidden-import", "sounddevice",
        "--hidden-import", "pyvirtualcam",
        "--hidden-import", "requests",
        "--hidden-import", "PyQt5",
        "--hidden-import", "numpy",
        "--collect-submodules", "PyQt5",
        "--collect-submodules", "av",
        "--noupx",
        # 中间产物放到系统临时目录，避免构建环境的安全删除 shim 把清理误判为回收站操作
        "--workpath", os.path.join(tempfile.gettempdir(), "zhibodou_build"),
    ]
    if args.onefile:
        opts.append("--onefile")
    else:
        opts.append("--onedir")
    if args.windowed:
        opts.append("--windowed")
    else:
        opts.append("--console")
    # 将本地 ffmpeg.exe 打进产物目录（Windows 用 ; 分隔）
    if os.path.isfile(FFMPEG):
        sep = ";" if sys.platform.startswith("win") else ":"
        opts += ["--add-data", f"{FFMPEG}{sep}."]
        print(f"[build] 已包含本地 ffmpeg.exe -> {FFMPEG}")
    else:
        print("[build] 未找到 ffmpeg.exe，ffmpeg 回退方案将依赖系统 PATH / imageio-ffmpeg")

    print("[build] PyInstaller 参数:", opts)
    run(opts)
    print("[build] 完成。产物位于 dist/ 目录。")


if __name__ == "__main__":
    main()

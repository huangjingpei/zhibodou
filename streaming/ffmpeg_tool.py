# -*- coding: utf-8 -*-
"""ffmpeg 可执行文件查找与 DirectShow 设备枚举（仅 ffmpeg 回退后端需要）。"""
import os
import re
import shutil
import subprocess
import sys

from core.runtime import app_dir, CREATE_NO_WINDOW

# 项目根目录（streaming/ 的上一级）
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_ffmpeg():
    """查找可用的 ffmpeg 可执行文件：
       1) 系统 PATH
       2) 打包后 exe 同目录 / PyInstaller 临时目录(sys._MEIPASS)
       3) 脚本/工作目录下的本地 ffmpeg(.exe)
       4) imageio-ffmpeg 自带二进制
    """
    # 1) 系统 PATH
    try:
        p = shutil.which("ffmpeg")
        if p:
            return p
    except Exception:
        pass
    # 2) 候选目录：打包环境优先用 exe 所在目录与 _MEIPASS，其次脚本目录/工作目录
    candidate_dirs = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate_dirs.append(exe_dir)
        # PyInstaller 6.x 的 one-folder 新布局会把依赖放在 _internal 子目录
        candidate_dirs.append(os.path.join(exe_dir, "_internal"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate_dirs.append(meipass)
    candidate_dirs.append(_PACKAGE_ROOT)
    candidate_dirs.append(os.getcwd())
    for d in candidate_dirs:
        for cand in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                return p
    # 3) imageio-ffmpeg 自带
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def list_dshow_devices():
    """列出 Windows DirectShow 的视频/音频设备名称（仅 ffmpeg 回退方案使用）。"""
    exe = find_ffmpeg()
    if not exe:
        return [], []
    try:
        # 注意：不能用 text=True —— 中文 Windows 上默认按 GBK 解码，而 ffmpeg
        # 设备名可能含 GBK 无法表示的字节，会触发 UnicodeDecodeError 且 .stderr 变 None。
        # 改为先拿字节、再手动 utf-8 容错解码。
        proc = subprocess.run([exe, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=20, creationflags=CREATE_NO_WINDOW)
        out = (proc.stderr or b"").decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[dshow] 列举设备失败: {e}")
        return [], []
    vids, auds = [], []
    cur = None
    for line in out.splitlines():
        if "DirectShow video devices" in line:
            cur = vids
        elif "DirectShow audio devices" in line:
            cur = auds
        elif cur is not None:
            m = re.search(r'"([^"]+)"', line)
            if m:
                cur.append(m.group(1))
    return vids, auds

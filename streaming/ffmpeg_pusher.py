# -*- coding: utf-8 -*-
"""ffmpeg 推流后端（PyAV 不可用时的回退方案）。

视频帧由 Python 处理好后通过 stdin 管道喂给 ffmpeg 编码，因此不再依赖
DirectShow 视频设备名（早期版本正是因此报「未找到可用的 DirectShow 视频
设备」）。ffmpeg 的 stderr 落盘到 ffmpeg_last.log，broken pipe 时能读到它
真正的退出原因。
"""
import os
import subprocess
import threading
import time
from urllib.parse import urlparse

import cv2
import numpy as np

from core.config import RTMP_VIDEO_BITRATE, RTMP_AUDIO_BITRATE, RTMP_PRESET
from core.runtime import app_dir, CREATE_NO_WINDOW
from streaming.ffmpeg_tool import find_ffmpeg


def _redact_rtmp_url(url):
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/***"
    except Exception:
        return "rtmp://***/***"


class FFmpegRtmpPusher:
    """回退方案：由 ffmpeg 直接采集摄像头+麦克风（Windows dshow）并推流 RTMP。
    Python 负责选择设备、构造命令、应用美颜/裁切滤镜。"""

    def __init__(self, url, width, height, fps, audio_rate, audio_channels,
                 video_bitrate=RTMP_VIDEO_BITRATE, audio_bitrate=RTMP_AUDIO_BITRATE,
                 preset=RTMP_PRESET):
        self.url = url
        self.width = width
        self.height = height
        self.fps = fps
        self.audio_rate = audio_rate
        self.audio_channels = audio_channels
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.preset = preset
        self.proc = None
        self.running = False
        self.error = None
        self.video_device = None
        self.audio_device = None
        self.beauty = None  # (bright, contrast, sat) 0-100，默认50
        self._ff_err_path = None

    def configure_devices(self, video_device, audio_device, beauty=None):
        self.video_device = video_device
        self.audio_device = audio_device
        self.beauty = beauty

    def start(self, video_getter=None, audio_getter=None):
        """ffmpeg 回退方案：从 stdin 接收 Python 已处理好的视频帧(BGR)并编码推流。

        与 PyAV 后端一致，视频帧由调用方 produce_push_frame() 提供（已做美颜/裁竖屏/缩放），
        因此这里不再用 dshow 采集视频，只需原样编码；音频若无设备则用静音轨道占位。
        这样彻底摆脱对 DirectShow 视频设备名的依赖——之前正是因为没有可用 dshow
        视频设备而直接启动失败（"未找到可用的 DirectShow 视频设备"）。
        """
        self.running = True
        exe = find_ffmpeg()
        if not exe:
            self.error = "未找到 ffmpeg（请安装 ffmpeg 或 imageio-ffmpeg）"
            return False
        if video_getter is None:
            self.error = "ffmpeg 回退方案需要 Python 提供的视频帧"
            return False
        cmd = [
            exe, "-hide_banner", "-loglevel", "warning", "-y",
            # 视频：从 stdin 接收 rawvideo（BGR24，尺寸即目标分辨率）
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}", "-r", str(self.fps),
            "-i", "-",
        ]
        # 音频：优先用解析到的 dshow 设备名；否则补一条静音轨道，避免纯视频流被服务器拒收
        if self.audio_device:
            cmd += ["-f", "dshow", "-i", f"audio={self.audio_device}"]
        else:
            cmd += ["-f", "lavfi", "-i", f"anullsrc=r={self.audio_rate}:cl=mono"]
        cmd += [
            "-c:v", "libx264", "-preset", self.preset, "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-b:v", str(self.video_bitrate),
            "-g", str(self.fps * 2), "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", str(self.audio_bitrate),
            "-f", "flv", self.url,
        ]
        # 把 ffmpeg 的 stderr 落盘到 ffmpeg_last.log，broken pipe 时可看到它真正的退出原因
        self._ff_err_path = os.path.join(app_dir(), "ffmpeg_last.log")
        try:
            ff_err = open(self._ff_err_path, "wb")
        except Exception:
            ff_err = subprocess.DEVNULL
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=ff_err,
                                         creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.error = str(e)
            print(f"[ffmpeg推流] 启动失败: {e}")
            self.running = False
            return False
        # 启动喂帧线程：按帧率把 produce_push_frame 的帧写进 ffmpeg stdin
        self._feed_thread = threading.Thread(target=self._feed_loop,
                                             args=(video_getter,), daemon=True)
        self._feed_thread.start()
        audio_mode = "dshow音频" if self.audio_device else "静音音频"
        print(f"[ffmpeg推流] 已启动（视频走管道/{audio_mode}）-> {_redact_rtmp_url(self.url)}")
        return True

    def _feed_loop(self, video_getter):
        """按目标帧率持续把视频帧写入 ffmpeg stdin；无新帧时复用上一帧保持时间轴连续。"""
        expected = self.width * self.height * 3
        last = None
        next_t = time.perf_counter()
        interval = 1.0 / self.fps
        while self.running and self.proc is not None and self.proc.poll() is None:
            try:
                frame = video_getter()
            except Exception as e:
                self.error = f"取帧失败: {e}"
                print(f"[ffmpeg推流] 取帧异常: {e}")
                break
            if frame is None:
                frame = last
            if frame is None:
                time.sleep(0.01)
                continue
            try:
                h, w = frame.shape[0], frame.shape[1]
                if w != self.width or h != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))
                if frame.dtype != np.uint8:
                    frame = frame.astype(np.uint8)
                if frame.shape[2] != 3:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                data = frame.tobytes()
                if len(data) == expected:
                    self.proc.stdin.write(data)
                else:
                    print(f"[ffmpeg推流] 帧字节数异常({len(data)}/{expected})，已跳过")
            except (BrokenPipeError, ValueError) as e:
                self.error = f"写入 ffmpeg 失败: {e}"
                rc = self.proc.poll() if self.proc else None
                print(f"[ffmpeg推流] 管道写入失败（ffmpeg 已退出, returncode={rc}）: {e}")
                tail = self._read_ffmpeg_stderr_tail()
                if tail:
                    print(f"[ffmpeg推流] ffmpeg 退出前日志（详见 ffmpeg_last.log）:\n{tail}")
                break
            except Exception as e:
                self.error = f"写入 ffmpeg 失败: {e}"
                print(f"[ffmpeg推流] 管道写入异常: {e}")
                break
            last = frame
            next_t += interval
            sleep_t = next_t - time.perf_counter()
            if sleep_t > 0:
                time.sleep(sleep_t)
        # 收尾：关闭 stdin 让 ffmpeg 完成编码并正常退出
        try:
            if self.proc is not None and self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:
            pass

    def _read_ffmpeg_stderr_tail(self, max_bytes=3000):
        """读取 ffmpeg 日志尾部，用于 broken pipe 时定位 ffmpeg 真正退出原因。"""
        try:
            with open(self._ff_err_path, "rb") as f:
                data = f.read()
            text = data.decode("utf-8", errors="ignore")
            return text[-max_bytes:] if text else ""
        except Exception:
            return ""

    def stop(self):
        self.running = False
        if self.proc is not None:
            try:
                if self.proc.stdin is not None:
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        feed = getattr(self, "_feed_thread", None)
        if feed is not None and feed.is_alive():
            feed.join(timeout=2)

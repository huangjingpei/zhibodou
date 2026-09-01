# -*- coding: utf-8 -*-
"""PyAV 推流后端（首选方案）。

由调用方持续提供视频帧(BGR)与音频块(int16)，本类用 PyAV 编码并推 RTMP。
关键工程点：
  * rw_timeout 限制单次读写，避免 TCP 发送缓冲塞满后永久卡死在 mux 里；
  * VBV(maxrate/bufsize) 限制瞬时码率峰值，防止把上行带宽打爆；
  * 墙钟节流严格按 fps 推送，而不是以 CPU 全速灌数据；
  * 识别网络类错误后走退避重连，而不是原地重试。
"""
import threading
import time
from fractions import Fraction

import cv2
import numpy as np

from core.config import (RTMP_VIDEO_BITRATE, RTMP_AUDIO_BITRATE, RTMP_PRESET,
                         RTMP_OPEN_TIMEOUT, RTMP_RW_TIMEOUT, RTMP_MAX_RECONNECT,
                         AUDIO_BLOCK)
from core.runtime import av


class PyAVRtmpPusher:
    """纯 Python 推流：由调用方持续提供视频帧(BGR)与音频块(int16)，本类用 PyAV 编码并推 RTMP。"""

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
        self.container = None
        self.vstream = None
        self.astream = None
        self.running = False
        self.thread = None
        self.video_getter = None
        self.audio_getter = None
        self.frame_count = 0
        self.sample_count = 0
        self.error = None
        # 断流/重连状态
        self.fatal = False            # True 表示已彻底放弃（重连次数用尽）
        self.reconnecting = False
        self.reconnect_count = 0
        self.max_reconnect = RTMP_MAX_RECONNECT
        self.on_state = None          # 可选回调：on_state(state:str, detail:str)
        self._last_frame = None       # 摄像头暂时无帧时复用，保持时间轴连续
        self._log_ts = {}             # 日志限频： key -> [上次打印时间, 累计次数]
        self._slow_ticks = 0          # 连续「发送慢于实时」的次数（上行带宽不足信号）

    # ---------- 工具 ----------
    def _log(self, key, msg, interval=5.0):
        """同类日志限频打印，避免刷屏；重复次数在下一次打印时带出。"""
        now = time.time()
        rec = self._log_ts.get(key)
        if rec is None:
            self._log_ts[key] = [now, 0]
            print(msg)
            return
        rec[1] += 1
        if now - rec[0] >= interval:
            extra = f"（{interval:.0f}s 内重复 {rec[1]} 次）" if rec[1] else ""
            print(msg + extra)
            rec[0] = now
            rec[1] = 0

    def _notify(self, state, detail=""):
        if self.on_state:
            try:
                self.on_state(state, detail)
            except Exception:
                pass

    @staticmethod
    def _is_network_error(exc):
        """判断是否为「连接已废」类错误：需要重建连接而不是原地重试。
        Windows 下 ETIMEDOUT=138 / ECONNRESET=10054 / EPIPE=32；FFmpeg 会映射成负 errno。"""
        errno_val = getattr(exc, "errno", None)
        if errno_val is not None and abs(int(errno_val)) in (
                5, 32, 104, 138, 10053, 10054, 10060, 32104):
            return True
        text = str(exc).lower()
        for kw in ("broken pipe", "connection reset", "timed out", "timeout",
                   "end of file", "-138", "i/o error", "errno 138", "errno 32"):
            if kw in text:
                return True
        return isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError, OSError))

    # ---------- 连接管理 ----------
    def _open_container(self):
        """建立 RTMP 连接并创建音视频流。失败抛异常。"""
        options = {
            "flvflags": "no_duration_filesize",
            # 写超时（微秒）：避免 TCP 发送缓冲塞满后一直卡死在 mux 里
            "rw_timeout": str(int(RTMP_RW_TIMEOUT * 1_000_000)),
            "tcp_nodelay": "1",
        }
        try:
            self.container = av.open(self.url, mode="w", format="flv",
                                     options=options,
                                     timeout=(RTMP_OPEN_TIMEOUT, RTMP_RW_TIMEOUT))
        except TypeError:
            # 老版本 PyAV 不支持 timeout 参数
            self.container = av.open(self.url, mode="w", format="flv", options=options)
        # 视频流：限制 VBV，避免瞬时码率峰值把上行打爆
        self.vstream = self.container.add_stream("libx264", rate=self.fps)
        self.vstream.width = self.width
        self.vstream.height = self.height
        self.vstream.pix_fmt = "yuv420p"
        self.vstream.bit_rate = self.video_bitrate
        try:
            self.vstream.codec_context.gop_size = self.fps * 2
        except Exception:
            pass
        self.vstream.codec_context.options = {
            "preset": self.preset,
            "tune": "zerolatency",
            "profile": "main",
            "maxrate": str(self.video_bitrate),
            "bufsize": str(self.video_bitrate * 2),
            "sc_threshold": "0",
        }
        # 音频流（仅在提供了音频源时创建）
        if self.audio_getter is not None:
            self.astream = self.container.add_stream("aac", rate=self.audio_rate)
            self.astream.layout = "mono" if self.audio_channels == 1 else "stereo"
            self.astream.bit_rate = self.audio_bitrate
            self.astream.codec_context.options = {"strict": "experimental"}
        else:
            self.astream = None

    def _close_container(self, flush=False):
        try:
            if flush and self.container is not None:
                if self.vstream is not None:
                    for pkt in self.vstream.encode(None):
                        self.container.mux(pkt)
                if self.astream is not None:
                    for pkt in self.astream.encode(None):
                        self.container.mux(pkt)
        except Exception:
            pass
        try:
            if self.container is not None:
                self.container.close()
        except Exception:
            pass
        self.container = None
        self.vstream = None
        self.astream = None

    def _reconnect(self):
        """连接已废时重建：退避重试，重置时间轴。返回 True 表示重连成功。"""
        self.reconnecting = True
        self._close_container(flush=False)
        while self.running and self.reconnect_count < self.max_reconnect:
            self.reconnect_count += 1
            delay = min(2 ** self.reconnect_count, 10)
            print(f"[PyAV推流] 连接中断，{delay}s 后第 {self.reconnect_count}/{self.max_reconnect} 次重连…")
            self._notify("reconnecting", f"第 {self.reconnect_count} 次重连")
            for _ in range(int(delay * 10)):
                if not self.running:
                    self.reconnecting = False
                    return False
                time.sleep(0.1)
            try:
                self._open_container()
            except Exception as e:
                self.error = str(e)
                print(f"[PyAV推流] 重连失败: {e}")
                self._close_container(flush=False)
                continue
            # 重置时间轴，丢弃旧积压音频
            self.frame_count = 0
            self.sample_count = 0
            self._drain_audio()
            self._log_ts.clear()
            self.reconnecting = False
            self.reconnect_count = 0
            print("[PyAV推流] 重连成功，已恢复推流")
            self._notify("reconnected", "")
            return True
        self.reconnecting = False
        self.fatal = True
        self.running = False
        self.error = self.error or "RTMP 连接中断且重连失败"
        print(f"[PyAV推流] 重连次数用尽，已停止推流：{self.error}")
        self._notify("fatal", self.error)
        return False

    def _drain_audio(self, limit=1000):
        if self.audio_getter is None:
            return
        for _ in range(limit):
            if self.audio_getter() is None:
                break

    # ---------- 启动 / 主循环 ----------
    def start(self, video_getter, audio_getter=None):
        self.video_getter = video_getter
        self.audio_getter = audio_getter
        self.running = True
        self.fatal = False
        self.reconnect_count = 0
        try:
            self._open_container()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            self.error = str(e)
            print(f"[PyAV推流] 启动失败: {e}")
            self._close_container(flush=False)
            self.running = False
            return False

    def _encode_video(self, vbase):
        frame = self.video_getter() if self.video_getter else None
        if frame is None:
            frame = self._last_frame
        else:
            self._last_frame = frame
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        vf.pts = self.frame_count
        vf.time_base = vbase
        self.frame_count += 1
        for pkt in self.vstream.encode(vf):
            self.container.mux(pkt)

    def _encode_audio(self, abase, max_chunks):
        """每轮最多消费 max_chunks 块音频；积压过多时丢弃最旧的，避免音画延迟越拖越大。"""
        if self.audio_getter is None or self.astream is None:
            return
        for _ in range(max_chunks):
            chunk = self.audio_getter()
            if chunk is None:
                return
            # PyAV 要求音频为二维数组 (声道数, 采样数)；麦克风为单声道，故 (1, N)
            arr = np.ascontiguousarray(chunk).reshape(self.audio_channels, -1)
            af = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
            af.sample_rate = self.audio_rate
            af.pts = self.sample_count
            af.time_base = abase
            self.sample_count += arr.shape[1]
            for pkt in self.astream.encode(af):
                self.container.mux(pkt)
        # 仍有积压说明消费不过来，直接丢弃旧数据保实时
        dropped = 0
        while dropped < 200 and self.audio_getter() is not None:
            dropped += 1
        if dropped:
            self._log("audio_drop", f"[PyAV推流] 音频积压，丢弃 {dropped} 块以保持实时")

    def _run(self):
        vbase = Fraction(1, self.fps)
        abase = Fraction(1, self.audio_rate)
        period = 1.0 / self.fps
        # 每帧周期内理论产生的音频块数，留 3 倍余量
        chunks_per_frame = max(1, int(self.audio_rate * period / max(1, AUDIO_BLOCK)) + 1)
        max_chunks = chunks_per_frame * 3
        next_tick = time.perf_counter()
        while self.running:
            try:
                t0 = time.perf_counter()
                self._encode_video(vbase)
                self._encode_audio(abase, max_chunks)
                cost = time.perf_counter() - t0
                # 发送/编码慢于实时，说明上行带宽或 CPU 不足
                if cost > period:
                    self._slow_ticks += 1
                    if self._slow_ticks % 40 == 0:
                        self._log("slow", f"[PyAV推流] 发送慢于实时（单帧耗时 {cost*1000:.0f}ms > "
                                          f"{period*1000:.0f}ms），上行带宽或 CPU 可能不足，"
                                          f"建议下调 RTMP_VIDEO_BITRATE / BASE_FPS")
                else:
                    self._slow_ticks = 0
                # 墙钟节流：严格按 fps 推送，避免以 CPU 全速灌爆上行
                next_tick += period
                sleep = next_tick - time.perf_counter()
                if sleep > 0:
                    time.sleep(sleep)
                elif sleep < -period * 5:
                    next_tick = time.perf_counter()   # 落后太多，重置基准不追帧
            except Exception as e:
                self.error = str(e)
                if self._is_network_error(e):
                    print(f"[PyAV推流] 连接异常: {e}")
                    if not self._reconnect():
                        break
                    next_tick = time.perf_counter()
                else:
                    self._log("loop", f"[PyAV推流] 循环异常: {e}")
                    time.sleep(0.05)
        # 收尾：flush 编码器
        self._close_container(flush=True)

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        self.thread = None

# -*- coding: utf-8 -*-
"""主播端麦克风采集。

sounddevice 以回调方式拿到 PCM 数据，在回调里做降噪 / 增益 / 音量统计，
并按限频把音量 emit 给 UI（跨线程 emit 太频繁会拖慢主线程）。
若配置了推流队列，则把 int16 PCM 放入队列供 PyAV 推流后端消费。
"""
import queue
import time

import numpy as np
import sounddevice as sd
from PyQt5.QtCore import QObject, pyqtSignal

from core.config import (AUDIO_RATE, AUDIO_CHANNELS, AUDIO_BLOCK, AUDIO_LATENCY,
                         NOISE_REDUCE_THRESHOLD, VOICE_BOOST_RATIO)


# ============================================================
# 音频处理类（主播端）
# ============================================================
class AudioHost(QObject):
    vol_sig = pyqtSignal(int)
    def __init__(self):
        super().__init__()
        self.running = False
        self.stream = None
        self.mic_gain = 1.2
        self.device_id = None
        self.last_vol = 15
        # 推流音频队列：由 HostStream 注入；麦克风采集的 PCM 会放入此队列供 RTMP 推流使用
        self.push_queue = None
        self._status_log_ts = 0.0     # 音频状态日志限频
        self._status_count = 0
        self._vol_emit_ts = 0.0       # 音量信号限频（跨线程 emit 太频繁会拖慢主线程）

    def set_mic_gain(self, val):
        self.mic_gain = max(1.0, min(2.2, val / 25))

    def set_mic_device(self, dev_id):
        self.device_id = dev_id
        print(f"[音频] 选择麦克风设备ID: {dev_id}")

    def set_push_queue(self, q):
        """设置推流音频队列（仅 PyAV 推流后端需要）。"""
        self.push_queue = q

    def get_device_name(self):
        """返回当前所选麦克风的设备名（用于匹配 ffmpeg 的 dshow 音频设备）。

        未手动选择或查询失败时返回 None，由调用方决定回退策略。
        """
        if self.device_id is None:
            return None
        try:
            return sd.query_devices(self.device_id)["name"]
        except Exception:
            return None

    def _audio_callback(self, indata, frames, time_info, status):
        # overflow 只表示上一块被丢过，本块数据依然有效：限频提示但继续处理，
        # 不能直接 return，否则会连带丢掉正常音频并造成推流断续。
        if status:
            self._status_count += 1
            now = time.time()
            if now - self._status_log_ts >= 5.0:
                extra = f"（5s 内共 {self._status_count} 次）" if self._status_count > 1 else ""
                print(f"[音频回调] 状态异常: {status}{extra}，通常是 CPU 繁忙所致，已自动容错")
                self._status_log_ts = now
                self._status_count = 0
        try:
            if indata.shape[1] > 1:
                data = np.mean(indata, axis=1)
            else:
                data = indata.flatten()
            data = data.astype(np.float32, copy=True)

            vol_level = np.max(np.abs(data))
            vol = int(vol_level * 200)
            vol = max(15, min(100, vol))
            self.last_vol = vol
            # 限频 emit：约 10 次/秒足够驱动音量条
            now_v = time.time()
            if now_v - self._vol_emit_ts >= 0.1:
                self._vol_emit_ts = now_v
                self.vol_sig.emit(vol)

            mask = np.abs(data) > NOISE_REDUCE_THRESHOLD
            data[~mask] *= 0.15
            data *= VOICE_BOOST_RATIO

            audio_data = (data * self.mic_gain * 32767).astype(np.int16)
            # 若已配置推流音频队列，则放入队列（非阻塞；满则丢弃最旧的一块，
            # 保留最新音频，避免推流端消费不过来时音画延迟持续累积）
            if self.push_queue is not None:
                try:
                    self.push_queue.put_nowait(audio_data)
                except queue.Full:
                    try:
                        self.push_queue.get_nowait()
                        self.push_queue.put_nowait(audio_data)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[音频回调] 异常: {e}")

    def start_mic_only(self):
        if self.device_id is None:
            try:
                devs = sd.query_devices()
                for idx, dev in enumerate(devs):
                    if dev["max_input_channels"] > 0:
                        self.device_id = idx
                        print(f"[音频] 未手动选择麦克风，自动选用默认设备: {dev['name']} (ID:{idx})")
                        break
                if self.device_id is None:
                    print("[音频] 错误：未检测到可用麦克风设备！")
                    return False
            except Exception as e:
                print(f"[音频] 自动检测麦克风失败: {e}")
                return False

        self.running = True
        try:
            print(f"[音频] 启动麦克风，设备ID: {self.device_id}")
            self.stream = sd.InputStream(
                samplerate=AUDIO_RATE,
                blocksize=AUDIO_BLOCK,
                device=self.device_id,
                channels=AUDIO_CHANNELS,
                callback=self._audio_callback,
                latency=AUDIO_LATENCY
            )
            self.stream.start()
            print("[音频] 麦克风已启动")
            return True
        except Exception as e:
            print(f"[音频] 麦克风启动失败: {e}")
            self.running = False
            return False

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
            self.stream = None
        self.push_queue = None
        print("[音频] 已停止")

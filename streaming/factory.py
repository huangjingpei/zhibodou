# -*- coding: utf-8 -*-
"""推流后端自动选择。

设计：优先用纯 Python（PyAV）编码并推流 RTMP；若环境没有 PyAV，则回退到
ffmpeg —— 视频帧由 Python 处理好后经 stdin 管道喂给它，音频能匹配到 dshow
设备就用，否则补一条静音轨道（纯视频流会被部分服务器拒收）。

本模块是 sessions 与具体推流后端之间的唯一接口：上层只需给出"当前麦克风名"
和"美颜参数"，不必知道后端是 PyAV 还是 ffmpeg。
"""

from core.config import (RTMP_PUSH_URL, VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT,
                         BASE_FPS, AUDIO_RATE, AUDIO_CHANNELS)
from core.runtime import HAVE_AV
from streaming.ffmpeg_pusher import FFmpegRtmpPusher
from streaming.ffmpeg_tool import find_ffmpeg, list_dshow_devices
from streaming.pyav_pusher import PyAVRtmpPusher


def _resolve_audio_device(mic_name, auds):
    """把 sounddevice 的麦克风名模糊匹配到 ffmpeg 的 dshow 音频设备名。

    两套 API 拿到的名字往往不完全一致（一个带驱动后缀、一个不带），因此双向
    子串匹配；都匹配不上时退回第一个可用设备，再不行就用原始名字硬试。
    """
    if not mic_name:
        return auds[0] if auds else None
    for d in auds:
        if mic_name in d or d in mic_name:
            return d
    return auds[0] if auds else mic_name


def create_pusher(mic_name=None, beauty=None, on_state=None, push_url=None):
    """按运行环境选择推流后端。

    :param mic_name: 当前选中的麦克风名（仅 ffmpeg 后端用于匹配 dshow 设备）
    :param beauty:   (bright, contrast, sat) 三元组，仅 ffmpeg 后端使用
    :param on_state: 状态回调 on_state(state, detail)
    :param push_url: 推流地址。正式会话由后端短效签发（pdk.live_service 申请）；
                     为空时回落本地配置地址（本地 MediaMTX / 开发场景）
    :return: (pusher, backend_name)；都不可用时返回 (None, None)
    """
    url = push_url or RTMP_PUSH_URL
    if HAVE_AV:
        p = PyAVRtmpPusher(url, VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT,
                           BASE_FPS, AUDIO_RATE, AUDIO_CHANNELS)
        p.on_state = on_state
        return p, "pyav"

    if find_ffmpeg() is None:
        return None, None

    p = FFmpegRtmpPusher(url, VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT,
                         BASE_FPS, AUDIO_RATE, AUDIO_CHANNELS)
    _, auds = list_dshow_devices()
    audio_dev = _resolve_audio_device(mic_name, auds)
    p.configure_devices(None, audio_dev, beauty=beauty)
    print(f"[主播] ffmpeg 推流（视频走管道）：音频设备={audio_dev}")
    return p, "ffmpeg"

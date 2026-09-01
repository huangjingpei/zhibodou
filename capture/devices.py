# -*- coding: utf-8 -*-
"""音频设备枚举（麦克风 / 扬声器）。"""
import sounddevice as sd


def get_all_mic_devices():
    mics = []
    try:
        devs = sd.query_devices()
        for idx, dev in enumerate(devs):
            if dev["max_input_channels"] > 0:
                mics.append((idx, dev["name"]))
    except Exception as e:
        print(f"获取麦克风设备失败: {e}")
    return mics

def get_all_speaker_devices():
    spks = []
    try:
        devs = sd.query_devices()
        for idx, dev in enumerate(devs):
            if dev["max_output_channels"] > 0:
                spks.append((idx, dev["name"]))
    except Exception as e:
        print(f"获取扬声器设备失败: {e}")
    return spks

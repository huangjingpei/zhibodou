# -*- coding: utf-8 -*-
"""推流：PyAV 后端（首选）、ffmpeg 后端（回退）与后端自动选择。

只负责"把帧编码并推到 RTMP"，不关心帧从哪来（由 sessions 提供 getter）。"""

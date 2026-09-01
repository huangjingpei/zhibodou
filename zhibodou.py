#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""兼容入口（历史遗留文件，已无实际代码）。

本项目原先所有代码都挤在单文件 zhibodou.py 中（2901 行），现已按功能拆分为
包结构，真正的主入口是 **main.py**：

    core/        基础设施：运行时兜底、全局配置、崩溃诊断、局域网发现
    capture/     音视频采集：音频设备枚举、麦克风采集、摄像头分辨率探测
    processing/  流处理：画面处理（美颜/裁竖屏）、直播源解析
    streaming/   推流：PyAV 后端（首选）、ffmpeg 后端（回退）、后端自动选择
    sessions/    业务编排：主播推流、观众拉流与矩阵分发
    licensing/   旧版授权兼容（当前登录与授权统一由 PDK 提供）
    pdk/         PDK 登录、激活、会话校验与设备许可证
    ui/          界面：主窗口、自定义控件、应用类

保留此文件仅为沿用 `python zhibodou.py` 的习惯；打包入口请用 main.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())

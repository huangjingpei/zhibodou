# -*- coding: utf-8 -*-
"""主播面板：主播页（左控制区 + 右预览）的全部控件与交互。

含：开始/停止推流、麦克风选择/增益/音量、分辨率选择与后台探测、直播源解析、
美颜调节、授权区（内嵌 AuthPanel）。预览渲染（pull_frame）与推流状态巡检
（check_push_state）由 MainWin 的定时器驱动。
"""
import time

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QSlider, QFrame, QScrollArea,
)
from capture.resolution import get_cached_resolutions, ResProbeThread
from core.config import (RTMP_PUSH_URL, RTMP_VIDEO_BITRATE, RTMP_SERVER_IP, RTMP_PORT)
from processing.image import crop_to_portrait, beauty_process
from ui.widgets import VolumeBar
from ui import theme
from ui.panels.base import Panel
from ui.panels.auth import AuthPanel

try:
    from pdk import auth_service as pdk_auth
except Exception:  # pragma: no cover
    pdk_auth = None


class HostPanel(Panel):
    def __init__(self, win):
        super().__init__(win)
        self.host_stream = win.host_stream
        self.timer = win.timer
        self._last_push_state = "idle"   # 推流状态巡检用
        self._res_probe = None
        self._pull_err = False
        self.auth_panel = None

    # ---------------------------------------------------------------- 构建页面
    def build(self, parent):
        host_page = QWidget(parent)
        host_lay = QHBoxLayout(host_page)
        host_lay.setContentsMargins(15, 15, 15, 15)
        host_lay.setSpacing(12)

        left_host = QWidget()
        left_host.setFixedWidth(320)
        left_lay = QVBoxLayout(left_host)
        left_lay.setContentsMargins(12, 12, 12, 12)
        left_lay.setSpacing(10)

        self.btn_start_host = QPushButton("开始直播推流")
        theme.set_button_role(self.btn_start_host, "primary")
        self.btn_start_host.setFixedHeight(40)
        self.btn_start_host.setFont(theme.font(theme.FS_BODY + 1, bold=True))
        self.btn_start_host.clicked.connect(self.toggle_cam)
        left_lay.addWidget(self.btn_start_host)

        self.lab_rtmp = QLabel(f"RTMP推流地址:\n{RTMP_PUSH_URL}")
        self.lab_rtmp.setWordWrap(True)
        self.lab_rtmp.setStyleSheet(theme.label_style(theme.FS_SMALL, theme.CYAN))
        left_lay.addWidget(self.lab_rtmp)

        left_lay.addWidget(QLabel("选择麦克风设备"))
        self.mic_combo = QComboBox()
        for dev_id, dev_name in self.win.all_mics:
            self.mic_combo.addItem(dev_name, dev_id)
        if self.win.all_mics:
            self.mic_combo.setCurrentIndex(0)
            self.host_stream.audio_host.set_mic_device(self.win.all_mics[0][0])
        self.mic_combo.currentIndexChanged.connect(
            lambda idx: self.host_stream.audio_host.set_mic_device(self.mic_combo.itemData(idx))
        )
        left_lay.addWidget(self.mic_combo)

        left_lay.addWidget(QLabel("麦克风音量"))
        self.host_vol_bar = VolumeBar()
        left_lay.addWidget(self.host_vol_bar)
        # 麦克风音量由采集线程 vol_sig 信号驱动刷新
        self.host_stream.audio_host.vol_sig.connect(self.update_vol)

        left_lay.addWidget(QLabel("麦克风增益"))
        self.mic_slider = QSlider(Qt.Horizontal)
        self.mic_slider.setRange(0, 100)
        self.mic_slider.setValue(50)
        self.mic_slider.valueChanged.connect(lambda v: self.host_stream.audio_host.set_mic_gain(v))
        left_lay.addWidget(self.mic_slider)

        left_lay.addWidget(QLabel("视频分辨率"))
        self.res_combo = QComboBox()
        # 先用静态列表填充，保证界面立即可用且不占用摄像头（避免启动时闪烁/卡顿）
        self._supported_res = get_cached_resolutions()
        for (w, h) in self._supported_res:
            orient = "竖屏" if h > w else "横屏"
            self.res_combo.addItem(f"{w}x{h} ({orient})", (w, h))
        # 默认值：优先竖屏 720p (720x1280)，其次横屏 1280x720，再退回第一个
        _preferred = [(720, 1280), (1280, 720)]
        _default_idx = 0
        for _pref in _preferred:
            if _pref in self._supported_res:
                _default_idx = self._supported_res.index(_pref)
                break
        self.res_combo.setCurrentIndex(_default_idx)
        self.res_combo.currentIndexChanged.connect(self.on_res_change)
        left_lay.addWidget(self.res_combo)

        # 让 HostStream 的采集分辨率与默认选项保持同步（此时摄像头尚未打开，仅记录）
        _dw, _dh = self._supported_res[_default_idx]
        self.host_stream.capture_w = _dw
        self.host_stream.capture_h = _dh

        # 后台异步探测摄像头真实支持的分辨率，完成后通过信号更新下拉框；
        # 这样启动/构建 UI 时不会在主线程同步打开摄像头，消除闪烁与卡顿
        self._res_probe = ResProbeThread()
        self._res_probe.done.connect(self._on_res_probed)
        # 注意：不能直接 finished -> deleteLater，否则 self._res_probe 会变成指向
        # 已销毁 C++ 对象的悬空包装器，后续 isRunning() 抛 RuntimeError，
        # 而 PyQt5 遇到槽内未捕获异常会直接 abort 进程（闪退且无日志）。
        self._res_probe.finished.connect(self._on_res_probe_finished)
        self._res_probe.start()

        left_lay.addWidget(QLabel("抖音直播间链接 (全局推流)"))
        self.host_live_input = QLineEdit()
        self.host_live_input.setPlaceholderText("粘贴抖音直播分享链接")
        left_lay.addWidget(self.host_live_input)
        host_parse_btn = QPushButton("解析线上流（作为推流画面源）")
        host_parse_btn.clicked.connect(self.on_parse_live)
        host_cam_btn = QPushButton("切回摄像头采集")
        host_cam_btn.clicked.connect(self.on_switch_cam)
        host_btn_lay = QHBoxLayout()
        host_btn_lay.addWidget(host_parse_btn)
        host_btn_lay.addWidget(host_cam_btn)
        left_lay.addLayout(host_btn_lay)
        left_lay.addSpacing(10)

        self.beauty_frame = QFrame()
        beauty_lay = QVBoxLayout(self.beauty_frame)
        beauty_lay.setContentsMargins(10, 10, 10, 10)
        beauty_lay.setSpacing(12)
        title_lab = QLabel("美颜调节")
        title_lab.setStyleSheet(theme.section_title_style())
        beauty_lay.addWidget(title_lab)

        self.slid_br = QSlider(Qt.Horizontal)
        self.slid_br.setRange(0, 100)
        self.slid_br.setValue(50)
        self.slid_br.valueChanged.connect(lambda v: setattr(self.host_stream, "bright", v))
        beauty_lay.addWidget(QLabel("亮度"))
        beauty_lay.addWidget(self.slid_br)

        self.slid_ct = QSlider(Qt.Horizontal)
        self.slid_ct.setRange(0, 100)
        self.slid_ct.setValue(50)
        self.slid_ct.valueChanged.connect(lambda v: setattr(self.host_stream, "contrast", v))
        beauty_lay.addWidget(QLabel("对比度"))
        beauty_lay.addWidget(self.slid_ct)

        self.slid_st = QSlider(Qt.Horizontal)
        self.slid_st.setRange(0, 100)
        self.slid_st.setValue(50)
        self.slid_st.valueChanged.connect(lambda v: setattr(self.host_stream, "sat", v))
        beauty_lay.addWidget(QLabel("饱和度"))
        beauty_lay.addWidget(self.slid_st)

        self.slid_sh = QSlider(Qt.Horizontal)
        self.slid_sh.setRange(0, 100)
        self.slid_sh.setValue(50)
        self.slid_sh.valueChanged.connect(lambda v: setattr(self.host_stream, "sharp", v))
        beauty_lay.addWidget(QLabel("锐度"))
        beauty_lay.addWidget(self.slid_sh)
        left_lay.addWidget(self.beauty_frame)

        # 授权区：内嵌 AuthPanel（机器码/激活码），授权状态通过 on_state 回传
        self.auth_panel = AuthPanel(
            self.win,
            on_state=lambda ok: self.btn_start_host.setEnabled(ok),
        )
        left_lay.addWidget(self.auth_panel.build(left_host))
        # 移除 stretch：左侧内容已超出窗口高度，改为用 QScrollArea 滚动，避免组件被压缩

        btn_back_h = QPushButton("返回首页")
        btn_back_h.setFixedHeight(30)
        btn_back_h.clicked.connect(self.win.return_home)
        left_lay.addWidget(btn_back_h)

        right_host = QWidget()
        right_lay = QVBoxLayout(right_host)
        right_lay.setAlignment(Qt.AlignCenter)
        self.lab_host_preview = QLabel("预览画面")
        self.lab_host_preview.setFixedSize(360, 640)
        self.lab_host_preview.setStyleSheet(
            f"border:2px solid {theme.BORDER_FOCUS};background:#000;"
            f"color:{theme.TEXT_FAINT};border-radius:8px;font-size:16px;")
        self.lab_host_preview.setAlignment(Qt.AlignCenter)
        right_lay.addWidget(self.lab_host_preview)

        # 左侧控制面板内容过多，加入滚动区域防止组件被压缩/截断
        # 用 QFrame 做视觉外框，QScrollArea 放在里面，让滚动条看起来是面板的一部分
        host_scroll = QScrollArea()
        host_scroll.setWidget(left_host)
        host_scroll.setWidgetResizable(True)
        host_scroll.setFrameShape(QScrollArea.NoFrame)
        host_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host_scroll.verticalScrollBar().setStyleSheet(
            "QScrollBar:vertical {background: transparent;width: 8px;"
            "margin: 4px 4px 4px 0px;border-radius: 4px;}"
            "QScrollBar::handle:vertical {background: " + theme.BORDER_FOCUS + ";"
            "min-height: 40px;border-radius: 4px;}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0px;}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background: transparent;}"
        )
        left_host_panel = QFrame()
        left_host_panel.setFixedWidth(328)
        left_host_panel_lay = QVBoxLayout(left_host_panel)
        left_host_panel_lay.setContentsMargins(0, 0, 0, 0)
        left_host_panel_lay.addWidget(host_scroll)
        host_lay.addWidget(left_host_panel)
        host_lay.addWidget(right_host)
        return host_page

    # ---------------------------------------------------------------- 分辨率探测
    def on_res_change(self, idx):
        w, h = self.res_combo.itemData(idx)
        self.host_stream.set_capture_resolution(w, h)

    def _on_res_probed(self, res):
        """分辨率后台探测完成：用真实支持的分辨率刷新下拉框（不影响正在进行的推流）。"""
        if not res or not hasattr(self, "res_combo") or self.res_combo is None:
            return
        cur = self.res_combo.currentData()
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        for (w, h) in res:
            orient = "竖屏" if h > w else "横屏"
            self.res_combo.addItem(f"{w}x{h} ({orient})", (w, h))
        idx = 0
        if cur in res:
            idx = res.index(cur)
        else:
            for _pref in [(720, 1280), (1280, 720)]:
                if _pref in res:
                    idx = res.index(_pref)
                    break
        self.res_combo.setCurrentIndex(idx)
        self.res_combo.blockSignals(False)
        # 仅当尚未开始推流时同步默认采集分辨率；推流中不打断摄像头
        if not self.timer.isActive():
            w, h = res[idx]
            self.host_stream.capture_w = w
            self.host_stream.capture_h = h

    def _on_res_probe_finished(self):
        """探测线程结束：先摘掉引用再安排销毁，避免留下悬空的 Python 包装器。"""
        t = getattr(self, "_res_probe", None)
        self._res_probe = None
        if t is not None:
            try:
                t.deleteLater()
            except Exception:
                pass

    def _wait_res_probe(self, timeout_ms=32000):
        """等待后台分辨率探测结束，避免探测子进程占着摄像头时与采集抢设备导致无预览。

        探测已改为独立子进程，耗时可能到数十秒，因此这里用 processEvents 轮询等待，
        保持界面可响应，而不是直接阻塞主线程。
        """
        t = getattr(self, "_res_probe", None)
        if t is None:
            return
        # 线程结束后 deleteLater 会销毁底层 C++ 对象，此时任何方法调用都会抛
        # RuntimeError；而 PyQt5 对槽函数内未捕获的异常默认直接 abort() 整个进程，
        # 表现就是"点一下按钮软件闪退且无任何日志"。这里必须逐次防御。
        from PyQt5.QtWidgets import QApplication

        def _alive_running(th):
            try:
                return th.isRunning()
            except RuntimeError:
                return False
            except Exception:
                return False

        if not _alive_running(t):
            self._res_probe = None
            return
        try:
            self.lab_host_preview.setText("正在检测摄像头支持的分辨率，请稍候…")
            QApplication.processEvents()
        except Exception:
            pass
        deadline = time.time() + timeout_ms / 1000.0
        while _alive_running(t) and time.time() < deadline:
            try:
                t.wait(100)
            except RuntimeError:
                break
            try:
                QApplication.processEvents()
            except Exception:
                pass

    # ---------------------------------------------------------------- 预览与推流
    def ensure_preview(self):
        """确保摄像头预览已开启：相机未就绪则打开；预览定时器始终运行（与推流解耦）。"""
        if self.timer.isActive():
            return
        self._wait_res_probe()
        if not self.host_stream.camera_ready:
            ok = False
            try:
                ok = self.host_stream.init_camera_only()
            except Exception as e:
                print(f"[主界面] 摄像头初始化异常: {e}")
            if not ok:
                self.lab_host_preview.setText("摄像头未就绪\n请检查设备是否被其他程序占用")
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.critical(self.lab_host_preview, "错误",
                                     "摄像头启动失败，请检查设备是否被其他程序占用！")
                return
        self.timer.start(55)

    def on_parse_live(self):
        from PyQt5.QtWidgets import QMessageBox
        url = self.host_live_input.text().strip()
        if not url:
            QMessageBox.warning(self.lab_host_preview, "提示", "请输入抖音直播间链接！")
            return
        if pdk_auth is None or not pdk_auth.is_authenticated():
            QMessageBox.warning(self.lab_host_preview, "错误", "未授权或授权已过期!")
            return
        self.win.run_authorized(lambda: self._start_live_source(url))

    def _start_live_source(self, url):
        from PyQt5.QtWidgets import QMessageBox
        # 若正在推流，先停推流（保留摄像头）
        if self.host_stream.running:
            self.host_stream.stop_streaming()
            self._set_stream_button(False)
        ok = self.host_stream.set_live_source(url)
        if ok:
            self.ensure_preview()
            if not self.host_stream.camera_ready:
                QMessageBox.critical(self.lab_host_preview, "错误", "直播源启动失败！")
                return
            if not self.host_stream.start_streaming():
                QMessageBox.critical(self.lab_host_preview, "错误", "推流服务启动失败！")
                return
            self._set_stream_button(True)
            QMessageBox.information(self.lab_host_preview, "成功", "已切换线上直播源，将作为 RTMP 推流画面")
        else:
            QMessageBox.critical(self.lab_host_preview, "失败", "链接解析失败，请检查链接有效性")

    def on_switch_cam(self):
        from PyQt5.QtWidgets import QMessageBox
        if self.host_stream.running:
            self.host_stream.stop_streaming()
            self._set_stream_button(False)
        self.host_stream.set_cam_source()
        self.ensure_preview()
        QMessageBox.information(self.lab_host_preview, "切换", "已切回摄像头采集")

    def toggle_cam(self):
        from PyQt5.QtWidgets import QMessageBox
        if pdk_auth is None or not pdk_auth.is_authenticated():
            QMessageBox.warning(self.lab_host_preview, "错误", "未授权或授权已过期!")
            return
        if not self.host_stream.running:
            self.win.run_authorized(self._start_camera_stream)
        else:
            # 停止推流不需要网络授权，保证授权服务异常时仍能立即止流。
            self.host_stream.stop_streaming()
            self._set_stream_button(False)
            self.lab_rtmp.setText(f"RTMP推流地址:\n{RTMP_PUSH_URL}")

    def _start_camera_stream(self):
        from PyQt5.QtWidgets import QMessageBox
        if not self.host_stream.running:
            # 确保预览已开启（摄像头已打开），再启动推流
            self.ensure_preview()
            if not self.host_stream.camera_ready:
                QMessageBox.critical(self.lab_host_preview, "错误", "摄像头或直播源启动失败，请检查设备！")
                return
            if not self.host_stream.start_streaming():
                QMessageBox.critical(self.lab_host_preview, "错误", "推流服务启动失败!")
                return
            self._set_stream_button(True)
            backend = self.host_stream.push_backend or "未知"
            self.lab_rtmp.setText(f"RTMP推流中（后端:{backend}）:\n{RTMP_PUSH_URL}")

    def update_vol(self, vol):
        self.host_vol_bar.set_vol(vol)

    def _set_stream_button(self, running):
        self.btn_start_host.setText("停止直播推流" if running else "开始直播推流")
        theme.set_button_role(self.btn_start_host, "danger" if running else "primary")

    def check_push_state(self):
        """预览定时器顺带巡检推流状态：重连中提示、彻底断流则复位按钮。"""
        st = getattr(self.host_stream, "push_state", "idle")
        if st == self._last_push_state:
            return
        self._last_push_state = st
        if st == "reconnecting":
            self.lab_rtmp.setText(f"RTMP 连接中断，正在重连…\n{RTMP_PUSH_URL}")
        elif st == "running":
            backend = self.host_stream.push_backend or "未知"
            self.lab_rtmp.setText(f"RTMP推流中（后端:{backend}）:\n{RTMP_PUSH_URL}")
        elif st == "fatal":
            err = self.host_stream.push_error or "连接中断"
            self.host_stream.stop_streaming()
            self._last_push_state = "idle"
            self._set_stream_button(False)
            self.lab_rtmp.setText(f"RTMP推流地址:\n{RTMP_PUSH_URL}")
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self.lab_host_preview, "推流已断开",
                f"RTMP 推流中断且重连失败：\n{err}\n\n"
                f"常见原因：\n"
                f"1) 上行带宽不足以承载 {RTMP_VIDEO_BITRATE // 1000} kbps，可下调码率或分辨率\n"
                f"2) 服务器 {RTMP_SERVER_IP}:{RTMP_PORT} 不可达或已拒绝推流\n"
                f"3) 网络防火墙/NAT 掐断了长连接\n\n"
                f"预览画面不受影响，可稍后重新点击「开始直播推流」。")

    def pull_frame(self):
        try:
            self.check_push_state()
            frame = self.host_stream.get_latest_frame()
            if frame is None:
                return
            br = self.slid_br.value()
            ct = self.slid_ct.value()
            st = self.slid_st.value()
            sh = self.slid_sh.value()
            send_frame = beauty_process(frame, br, ct, st, sh)
            send_frame = crop_to_portrait(send_frame)
            pw = max(2, self.lab_host_preview.width())
            ph = max(2, self.lab_host_preview.height())
            send_frame = cv2.resize(send_frame, (pw, ph), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(send_frame, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, pw, ph, pw * 3, QImage.Format_RGB888)
            self.lab_host_preview.setPixmap(QPixmap.fromImage(qimg))
        except Exception as e:
            if not getattr(self, "_pull_err", False):
                self._pull_err = True
                print(f"[预览] pull_host_frame 异常: {e}")

    def reset_preview(self):
        """返回首页时清空并复位预览画面（由 MainWin.return_home 调用）。"""
        self.lab_host_preview.clear()
        self.lab_host_preview.setText("预览画面")

    def shutdown(self):
        """窗口退出前停止异步探测，避免下一次登录仍占用摄像头。"""
        probe = getattr(self, "_res_probe", None)
        self._res_probe = None
        if probe is None:
            return
        try:
            if probe.isRunning():
                probe.requestInterruption()
                probe.wait(1500)
        except RuntimeError:
            pass
        except Exception as exc:
            print(f"[分辨率] 退出时停止探测失败: {exc}")

# -*- coding: utf-8 -*-
"""智播豆系统通知与版本升级公告弹窗（PyQt5 版）。

风格与智播豆深海蓝配色保持统一，展示通知列表卡片，支持：
1. 版本升级公告：专属蓝色标签、目标版本号高亮、一键打开浏览器下载更新；
2. 系统维护通知：橙黄色预警标签；
3. 常规业务公告：绿色标签；
4. 未读红色圆点高亮；
5. 一键「全部标为已读」；
6. 打开或关闭弹窗自动完成已读同步并清零红点。
"""
from __future__ import annotations

import webbrowser
from typing import Any, Callable, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui import theme
from pdk.notifications import NotificationLocalStore


class NotificationCard(QFrame):
    """可折叠/展开的手风琴通知卡片组件。

    - 折叠态：显示类型标签、标题、未读红点标识、发布时间、展开指示箭头 ▼，紧凑单行显示；
    - 展开态：单行概要 + 分割线 + 完整正文（支持鼠标划词复制）+ 版本升级专属操作行 + 折叠指示箭头 ▲。
    """

    def __init__(
        self,
        index: int,
        item: dict[str, Any],
        is_unread: bool,
        is_expanded: bool = False,
        on_toggle: Optional[Callable[[int], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.index = index
        self.item = item
        self.is_unread = is_unread
        self._is_expanded = is_expanded
        self.on_toggle = on_toggle

        self.setCursor(Qt.PointingHandCursor)
        self._init_ui()
        self._apply_expanded_state()

    def _init_ui(self) -> None:
        self.card_layout = QVBoxLayout(self)
        self.card_layout.setContentsMargins(14, 10, 14, 10)
        self.card_layout.setSpacing(8)

        # ---------------- 顶部单行概要（始终显示） ----------------
        self.header_widget = QWidget(self)
        self.header_widget.setCursor(Qt.PointingHandCursor)
        header_lay = QHBoxLayout(self.header_widget)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.setSpacing(8)

        # 类型标签
        ntype = str(self.item.get("noticeType") or "ANNOUNCEMENT").upper()
        if ntype == "UPDATE":
            badge_text = "版本升级"
            badge_bg = "#2563EB"
        elif ntype == "MAINTENANCE":
            badge_text = "系统维护"
            badge_bg = "#D97706"
        else:
            badge_text = "系统公告"
            badge_bg = "#059669"

        type_lbl = QLabel(f" {badge_text} ")
        type_lbl.setFont(theme.font(theme.FS_TINY, bold=True))
        type_lbl.setStyleSheet(f"""
            background-color: {badge_bg};
            color: #FFFFFF;
            border-radius: 4px;
            padding: 2px 5px;
            font-weight: bold;
            border: none;
        """)
        type_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header_lay.addWidget(type_lbl)

        # 标题（单行）
        title_text = str(self.item.get("title") or "通知公告")
        self.title_lbl = QLabel(title_text)
        self.title_lbl.setFont(theme.font(theme.FS_BODY, bold=True))
        self.title_lbl.setStyleSheet(f"color: {theme.TEXT}; font-weight: bold; border: none;")
        self.title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.title_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header_lay.addWidget(self.title_lbl)

        # 未读红点标识
        self.unread_lbl = QLabel("● 未读")
        self.unread_lbl.setFont(theme.font(theme.FS_TINY, bold=True))
        self.unread_lbl.setStyleSheet(f"color: {theme.RED}; font-weight: bold; border: none;")
        self.unread_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if not self.is_unread:
            self.unread_lbl.hide()
        header_lay.addWidget(self.unread_lbl)

        header_lay.addStretch(1)

        # 发布时间
        pub_time = str(self.item.get("publishTime") or self.item.get("publishAt") or "")
        if pub_time:
            clean_time = pub_time.replace("T", " ")[:19]
            time_lbl = QLabel(clean_time)
            time_lbl.setFont(theme.font(theme.FS_SMALL))
            time_lbl.setStyleSheet(f"color: {theme.TEXT_FAINT}; border: none;")
            time_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            header_lay.addWidget(time_lbl)

        # 展开/折叠指示箭头
        self.arrow_lbl = QLabel()
        self.arrow_lbl.setFont(theme.font(theme.FS_SMALL, bold=True))
        self.arrow_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        self.arrow_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header_lay.addWidget(self.arrow_lbl)

        self.card_layout.addWidget(self.header_widget)

        # ---------------- 展开详情区域（折叠时隐藏） ----------------
        self.body_widget = QWidget(self)
        body_lay = QVBoxLayout(self.body_widget)
        body_lay.setContentsMargins(0, 6, 0, 2)
        body_lay.setSpacing(10)

        # 分割线
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        body_lay.addWidget(divider)

        # 正文内容
        content = str(self.item.get("content") or "")
        if content:
            content_lbl = QLabel(content)
            content_lbl.setWordWrap(True)
            content_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content_lbl.setFont(theme.font(theme.FS_SMALL))
            content_lbl.setStyleSheet(f"color: {theme.TEXT_SOFT}; border: none; line-height: 1.45;")
            body_lay.addWidget(content_lbl)

        # 版本升级专用操作栏
        target_ver = str(self.item.get("targetVersion") or "").strip()
        download_url = str(self.item.get("downloadUrl") or "").strip()
        if ntype == "UPDATE" and (target_ver or download_url):
            up_row = QHBoxLayout()
            up_row.setContentsMargins(0, 4, 0, 0)
            up_row.setSpacing(10)

            if target_ver:
                ver_lbl = QLabel(f"目标升级版本: v{target_ver}")
                ver_lbl.setFont(theme.font(theme.FS_SMALL, bold=True))
                ver_lbl.setStyleSheet(f"color: {theme.PRIMARY_HOVER}; font-weight: bold; border: none;")
                up_row.addWidget(ver_lbl)

            up_row.addStretch()

            if download_url:
                dl_btn = QPushButton("🚀 立即下载更新")
                dl_btn.setFixedHeight(28)
                dl_btn.setFont(theme.font(theme.FS_SMALL, bold=True))
                dl_btn.setCursor(Qt.PointingHandCursor)
                dl_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {theme.PRIMARY};
                        color: #FFFFFF;
                        border: none;
                        border-radius: 6px;
                        padding: 0 12px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background-color: {theme.PRIMARY_HOVER};
                    }}
                """)
                dl_btn.clicked.connect(lambda _, url=download_url: webbrowser.open(url))
                up_row.addWidget(dl_btn)

            body_lay.addLayout(up_row)

        self.card_layout.addWidget(self.body_widget)

    def _apply_expanded_state(self) -> None:
        if self._is_expanded:
            self.body_widget.show()
            self.arrow_lbl.setText(" ▲")
            self.setToolTip("点击收起此条通知")
            self.setStyleSheet(f"""
                NotificationCard {{
                    background-color: {theme.SURFACE};
                    border: 1px solid {theme.PRIMARY};
                    border-radius: 8px;
                }}
            """)
        else:
            self.body_widget.hide()
            self.arrow_lbl.setText(" ▼")
            self.setToolTip("点击展开查看全部内容")
            self.setStyleSheet(f"""
                NotificationCard {{
                    background-color: {theme.SURFACE};
                    border: 1px solid {theme.BORDER};
                    border-radius: 8px;
                }}
                NotificationCard:hover {{
                    border-color: {theme.PRIMARY_HOVER};
                    background-color: {theme.SURFACE_ALT};
                }}
            """)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self.on_toggle:
                self.on_toggle(self.index)
        super().mousePressEvent(event)

    def set_expanded(self, expanded: bool) -> None:
        if self._is_expanded != expanded:
            self._is_expanded = expanded
            self._apply_expanded_state()

    def is_expanded(self) -> bool:
        return self._is_expanded

    def mark_as_read(self) -> None:
        self.is_unread = False
        if hasattr(self, "unread_lbl") and self.unread_lbl is not None:
            self.unread_lbl.hide()


class NotificationDialog(QDialog):
    """客户端系统通知与升级公告弹窗。"""

    def __init__(
        self,
        parent: Optional[QWidget],
        store: NotificationLocalStore,
        on_read_changed: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.store = store
        self.on_read_changed = on_read_changed
        self.notifications = list(self.store.cached_list)
        self.cards: list[NotificationCard] = []

        self.setWindowTitle("系统通知与升级公告")
        self.resize(640, 520)
        self.setMinimumSize(540, 420)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {theme.BG};
            }}
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {theme.BG_ELEVATED};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {theme.BORDER};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # 头部导航栏
        header = QHBoxLayout()
        header.setSpacing(12)

        unread_count = self.store.get_unread_count()
        unread_hint = f"（{unread_count} 条未读）" if unread_count > 0 else "（全部已读）"

        title_lbl = QLabel(f"🔔 系统通知与升级公告 {unread_hint}")
        title_lbl.setFont(theme.font(theme.FS_H2, bold=True))
        title_lbl.setStyleSheet(theme.label_style(theme.FS_H2, theme.TEXT, bold=True))
        header.addWidget(title_lbl)

        header.addStretch()

        if self.notifications:
            mark_btn = QPushButton("全部标为已读")
            mark_btn.setFixedHeight(28)
            mark_btn.setFont(theme.font(theme.FS_SMALL))
            mark_btn.setCursor(Qt.PointingHandCursor)
            mark_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme.SURFACE_SOFT};
                    color: {theme.TEXT_MUTED};
                    border: 1px solid {theme.BORDER};
                    border-radius: 6px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {theme.SURFACE_ALT};
                    color: {theme.TEXT};
                    border-color: {theme.PRIMARY};
                }}
            """)
            mark_btn.clicked.connect(self._mark_all_read_and_refresh)
            header.addWidget(mark_btn)

        root.addLayout(header)

        # 滚动列表区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet(f"background-color: {theme.BG};")
        cards_layout = QVBoxLayout(scroll_widget)
        cards_layout.setContentsMargins(0, 4, 4, 4)
        cards_layout.setSpacing(10)

        if not self.notifications:
            empty_box = QWidget()
            empty_box.setMinimumHeight(240)
            empty_layout = QVBoxLayout(empty_box)
            empty_lbl = QLabel("暂无通知公告")
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setFont(theme.font(theme.FS_BODY))
            empty_lbl.setStyleSheet(theme.label_style(theme.FS_BODY, theme.TEXT_FAINT))
            empty_layout.addWidget(empty_lbl)
            cards_layout.addWidget(empty_box)
        else:
            read_ids = self.store.read_ids
            self.cards.clear()
            for idx, item in enumerate(self.notifications):
                nid = str(item.get("id", ""))
                is_unread = nid not in read_ids
                # 最新的一条（第一条）默认打开，其他条数默认折叠单行
                is_expanded = (idx == 0)
                card = NotificationCard(
                    index=idx,
                    item=item,
                    is_unread=is_unread,
                    is_expanded=is_expanded,
                    on_toggle=self._on_card_toggle,
                    parent=scroll_widget,
                )
                self.cards.append(card)
                cards_layout.addWidget(card)

        cards_layout.addStretch()
        scroll.setWidget(scroll_widget)
        root.addWidget(scroll, 1)

        # 底部操作栏
        footer = QHBoxLayout()
        footer.addStretch()

        close_btn = QPushButton("关 闭")
        close_btn.setFixedSize(88, 34)
        close_btn.setFont(theme.font(theme.FS_BODY))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.SURFACE_SOFT};
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {theme.SURFACE_ALT};
                border-color: {theme.BORDER_FOCUS};
            }}
        """)
        close_btn.clicked.connect(self._on_close_clicked)
        footer.addWidget(close_btn)

        root.addLayout(footer)

    def _on_card_toggle(self, clicked_index: int) -> None:
        """手风琴交互：点击具体通知时，将当前已展开的进行缩放收起，当前行展开显示全部内容。"""
        if clicked_index < 0 or clicked_index >= len(self.cards):
            return

        target_card = self.cards[clicked_index]
        was_expanded = target_card.is_expanded()

        for idx, card in enumerate(self.cards):
            if idx == clicked_index:
                card.set_expanded(not was_expanded)
            else:
                card.set_expanded(False)

    def _mark_all_read_and_refresh(self) -> None:
        self.store.mark_all_as_read()
        for card in self.cards:
            card.mark_as_read()
        if self.on_read_changed:
            self.on_read_changed()
        self.accept()

    def _on_close_clicked(self) -> None:
        # 用户点击关闭时，自动将本批次已展示的通知标记为已读
        self.store.mark_all_as_read()
        if self.on_read_changed:
            self.on_read_changed()
        self.accept()

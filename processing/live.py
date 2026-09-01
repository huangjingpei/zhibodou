# -*- coding: utf-8 -*-
"""抖音直播源解析：把分享链接解析成可直接拉流的地址。"""
import re
import time

import cv2
import requests
import streamlink


# ============================================================
# 抖音直播解析模块
# ============================================================
class LiveStreamParser:
    @staticmethod
    def parse_douyin_url(url: str) -> str:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Referer": "https://live.douyin.com/",
                "Accept-Language": "zh-CN,zh;q=0.9"
            }
            if "v.douyin.com" in url:
                resp = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
                final_url = resp.url
            else:
                final_url = url
            room_id = re.search(r"live\.douyin\.com/(\d+)", final_url)
            if not room_id:
                room_id = re.search(r"(\d{18,19})", final_url)
            if not room_id:
                print("[解析] 无法提取直播间ID")
                return ""
            rid = room_id.group(1)
            print(f"[解析] 提取到直播间ID: {rid}")
            api_url = f"https://webcast-hl.amemv.com/webcast/room/reflow/info/?room_id={rid}&live_id=1"
            resp = requests.get(api_url, headers=headers, timeout=10)
            data = resp.json()
            stream_url = ""
            stream_url = data.get("data", {}).get("room", {}).get("stream_url", {}).get("rtmp_pull_url", "")
            if not stream_url:
                stream_url = data.get("data", {}).get("room", {}).get("stream_url", {}).get("flv_pull_url", {}).get("FULL_HD1", "")
            if not stream_url:
                stream_url = data.get("data", {}).get("room", {}).get("stream_url", {}).get("hls_pull_url", "")
            if not stream_url:
                print("[解析] 未获取到直播流地址")
                return ""
            print(f"[解析] 成功获取直播流地址: {stream_url[:50]}...")
            return stream_url
        except Exception as e:
            print(f"[解析] 抖音解析失败：{e}")
            return ""

    @staticmethod
    def read_stream_frame(stream_url: str, width, height):
        try:
            streams = streamlink.streams(stream_url)
            if streams:
                stream = streams["best"]
                cap = cv2.VideoCapture(stream.url)
            else:
                cap = cv2.VideoCapture(stream_url)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            for _ in range(30):
                ret, frame = cap.read()
                if ret and frame is not None:
                    return frame
                time.sleep(0.1)
            print("[解析] 无法读取直播流画面")
            return None
        except Exception as e:
            print(f"[解析] 读取直播流失败：{e}")
            return None

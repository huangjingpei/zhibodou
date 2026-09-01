# -*- coding: utf-8 -*-
"""局域网广播发现（主播端广播自己的 IP 供子机自动连接）。

注：当前版本子机走硬编码的中继服务器地址，这组函数暂未被主流程调用，
保留用于后续接入自动发现。
"""
import socket
import threading
import time

from core.config import BROADCAST_PORT, BROADCAST_MSG


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def start_broadcast():
    local_ip = get_local_ip()
    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            try:
                msg = f"{BROADCAST_MSG.decode()}|{local_ip}".encode()
                sock.sendto(msg, ("255.255.255.255", BROADCAST_PORT))
                time.sleep(0.5)
            except:
                time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()

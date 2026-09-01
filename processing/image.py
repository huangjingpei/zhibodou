# -*- coding: utf-8 -*-
"""画面处理：裁竖屏 + 美颜。"""
import cv2
import numpy as np


def crop_to_portrait(frame):
    h, w = frame.shape[:2]
    target_ratio = 9 / 16
    current_ratio = w / h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x_start = (w - new_w) // 2
        return frame[:, x_start:x_start+new_w]
    else:
        new_h = int(w / target_ratio)
        y_start = (h - new_h) // 2
        return frame[y_start:y_start+new_h]

def beauty_process(frame, bright=50, contrast=50, sat=50, sharp=50):
    result = frame.astype(np.float32)
    if bright != 50:
        bright_factor = 1.0 + (bright - 50) / 60.0
        result = result * bright_factor
        result = np.clip(result, 0, 255)
    if contrast != 50:
        alpha = 0.88 + (contrast - 50) / 110
        result = result * alpha
        result = np.clip(result, 0, 255)
    if sat != 50:
        hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] += (sat - 50) * 0.22
        hsv[..., 1] = np.clip(hsv[..., 1], 0, 255)
        result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    if sharp > 50:
        k = (sharp - 50) / 26
        kernel = np.array([[0, -k, 0], [-k, 1+4*k, -k], [0, -k, 0]], np.float32)
        result = cv2.filter2D(result, -1, kernel)
        result = np.clip(result, 0, 255)
    return result.astype(np.uint8)

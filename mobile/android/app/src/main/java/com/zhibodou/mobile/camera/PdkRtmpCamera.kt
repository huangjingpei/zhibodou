package com.zhibodou.mobile.camera

import android.content.Context
import android.media.MediaCodec
import com.pedro.common.AudioCodec
import com.pedro.common.ConnectChecker
import com.pedro.common.VideoCodec
import com.pedro.library.base.recording.RecordController
import com.pedro.library.util.streamclient.RtmpStreamClient
import com.pedro.library.util.streamclient.StreamBaseClient
import com.pedro.library.util.streamclient.StreamClientListener
import com.pedro.rtmp.rtmp.RtmpClient
import java.nio.ByteBuffer

/**
 * 智播专用原生 RTMP 推流相机引擎
 * 继承定制版 PdkCamera2Base，支持 1920x1080 硬件层直连、PdkOpenGlView 沉浸式 1:1 渲染与 RTMP 推流
 */
class PdkRtmpCamera : PdkCamera2Base {

    private val streamClientListener = object : StreamClientListener {
        override fun onRequestKeyframe() {
            requestKeyFrame()
        }
    }

    private lateinit var rtmpClient: RtmpClient
    private lateinit var streamClient: RtmpStreamClient

    constructor(openGlView: PdkOpenGlView, connectChecker: ConnectChecker) : super(openGlView) {
        init(connectChecker)
    }

    constructor(context: Context, connectChecker: ConnectChecker) : super(context) {
        init(connectChecker)
    }

    private fun init(connectChecker: ConnectChecker) {
        rtmpClient = RtmpClient(connectChecker)
        streamClient = RtmpStreamClient(rtmpClient, streamClientListener)
    }

    override fun getStreamClient(): RtmpStreamClient = streamClient

    override fun setVideoCodecImp(videoCodec: VideoCodec) {
        val record = recordController.status == RecordController.Status.RECORDING
        if (!record) rtmpClient.setVideoCodec(videoCodec)
    }

    override fun setAudioCodecImp(audioCodec: AudioCodec) {
        val record = recordController.status == RecordController.Status.RECORDING
        if (!record) rtmpClient.setAudioCodec(audioCodec)
    }

    override fun onAudioInfoImp(isStereo: Boolean, sampleRate: Int) {
        rtmpClient.setAudioInfo(sampleRate, isStereo)
    }

    override fun startStreamImp(endPoint: String) {
        if (videoEncoder.rotation == 90 || videoEncoder.rotation == 270) {
            rtmpClient.setVideoResolution(videoEncoder.height, videoEncoder.width)
        } else {
            rtmpClient.setVideoResolution(videoEncoder.width, videoEncoder.height)
        }
        rtmpClient.setFps(videoEncoder.fps)
        rtmpClient.connect(endPoint)
    }

    override fun stopStreamImp() {
        rtmpClient.disconnect()
    }

    override fun getAudioDataImp(audioBuffer: ByteBuffer, info: MediaCodec.BufferInfo) {
        rtmpClient.sendAudio(audioBuffer, info)
    }

    override fun onVideoInfoImp(sps: ByteBuffer, pps: ByteBuffer, vps: ByteBuffer?) {
        rtmpClient.setVideoInfo(sps, pps, vps)
    }

    override fun getVideoDataImp(videoBuffer: ByteBuffer, info: MediaCodec.BufferInfo) {
        rtmpClient.sendVideo(videoBuffer, info)
    }
}

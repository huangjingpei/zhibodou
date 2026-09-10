package com.zhibodou.mobile.camera;

import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Point;
import android.graphics.SurfaceTexture;
import android.os.Build;
import android.util.AttributeSet;
import android.util.Log;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;

import com.pedro.common.ExtensionsKt;
import com.pedro.encoder.input.gl.FilterAction;
import com.pedro.encoder.input.gl.SurfaceManager;
import com.pedro.encoder.input.gl.render.MainRender;
import com.pedro.encoder.input.gl.render.filters.BaseFilterRender;
import com.pedro.encoder.input.gl.render.filters.NoFilterRender;
import com.pedro.encoder.input.video.FpsLimiter;
import com.pedro.encoder.utils.gl.AspectRatioMode;
import com.pedro.encoder.utils.gl.GlUtil;
import com.pedro.library.util.Filter;
import com.pedro.library.view.ForceRenderer;
import com.pedro.library.view.GlInterface;
import com.pedro.library.view.TakePhotoCallback;

import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

@RequiresApi(api = Build.VERSION_CODES.JELLY_BEAN_MR2)
public class PdkOpenGlView extends SurfaceView
    implements GlInterface, SurfaceTexture.OnFrameAvailableListener, SurfaceHolder.Callback {

  public interface SurfaceListener {
    void onSurfaceCreated(PdkOpenGlView view);
    void onSurfaceChanged(PdkOpenGlView view, int width, int height);
    void onSurfaceDestroyed(PdkOpenGlView view);
  }

  private static final String TAG = "PdkOpenGlView";

  private final AtomicBoolean running = new AtomicBoolean(false);
  private volatile boolean isSurfaceReady = false;
  private volatile boolean wasRunning = false;
  private SurfaceListener surfaceListener = null;

  private final MainRender mainRender = new MainRender();
  private final SurfaceManager surfaceManagerPhoto = new SurfaceManager();
  private final SurfaceManager surfaceManager = new SurfaceManager();
  private final SurfaceManager surfaceManagerEncoder = new SurfaceManager();
  private final BlockingQueue<Filter> filterQueue = new LinkedBlockingQueue<>();
  private final LinkedBlockingQueue<Runnable> threadQueue = new LinkedBlockingQueue<>();
  private int previewWidth, previewHeight;
  private int encoderWidth, encoderHeight;
  private TakePhotoCallback takePhotoCallback;
  private int streamRotation;
  private boolean muteVideo = false;
  private boolean isPreviewHorizontalFlip = false;
  private boolean isPreviewVerticalFlip = false;
  private boolean isStreamHorizontalFlip = false;
  private boolean isStreamVerticalFlip = false;
  private AspectRatioMode aspectRatioMode = AspectRatioMode.Fill;
  private ExecutorService executor = null;
  private final FpsLimiter fpsLimiter = new FpsLimiter();
  private final ForceRenderer forceRenderer = new ForceRenderer();

  public PdkOpenGlView(Context context) {
    super(context);
    aspectRatioMode = AspectRatioMode.Fill;
    getHolder().addCallback(this);
  }

  public PdkOpenGlView(Context context, AttributeSet attrs) {
    super(context, attrs);
    aspectRatioMode = AspectRatioMode.Fill;
    getHolder().addCallback(this);
  }

  public void setSurfaceListener(SurfaceListener listener) {
    this.surfaceListener = listener;
  }

  public boolean isSurfaceReady() {
    return isSurfaceReady && getHolder().getSurface() != null && getHolder().getSurface().isValid();
  }

  @Override
  public SurfaceTexture getSurfaceTexture() {
    return mainRender.getSurfaceTexture();
  }

  @Override
  public Surface getSurface() {
    return mainRender.getSurface();
  }

  @Override
  public void setFilter(int filterPosition, @NonNull BaseFilterRender baseFilterRender) {
    filterQueue.add(new Filter(FilterAction.SET_INDEX, filterPosition, baseFilterRender));
  }

  @Override
  public void addFilter(@NonNull BaseFilterRender baseFilterRender) {
    filterQueue.add(new Filter(FilterAction.ADD, 0, baseFilterRender));
  }

  @Override
  public void addFilter(int filterPosition, @NonNull BaseFilterRender baseFilterRender) {
    filterQueue.add(new Filter(FilterAction.ADD_INDEX, filterPosition, baseFilterRender));
  }

  @Override
  public void clearFilters() {
    filterQueue.add(new Filter(FilterAction.CLEAR, 0, new NoFilterRender()));
  }

  @Override
  public void removeFilter(int filterPosition) {
    filterQueue.add(new Filter(FilterAction.REMOVE_INDEX, filterPosition, new NoFilterRender()));
  }

  @Override
  public void removeFilter(@NonNull BaseFilterRender baseFilterRender) {
    filterQueue.add(new Filter(FilterAction.REMOVE, 0, baseFilterRender));
  }

  @Override
  public int filtersCount() {
    return mainRender.filtersCount();
  }

  @Override
  public void setFilter(@NonNull BaseFilterRender baseFilterRender) {
    filterQueue.add(new Filter(FilterAction.SET, 0, baseFilterRender));
  }

  @Override
  public void setRotation(int rotation) {
    mainRender.setCameraRotation(rotation);
  }

  @Override
  public void forceFpsLimit(int fps) {
    fpsLimiter.setFPS(fps);
  }

  public void setAspectRatioMode(AspectRatioMode aspectRatioMode) {
    this.aspectRatioMode = aspectRatioMode;
  }

  public void setCameraFlip(boolean isFlipHorizontal, boolean isFlipVertical) {
    mainRender.setCameraFlip(isFlipHorizontal, isFlipVertical);
  }

  @Override
  public void setStreamRotation(int streamRotation) {
    this.streamRotation = streamRotation;
  }

  @Override
  public void setIsStreamHorizontalFlip(boolean flip) {
    isStreamHorizontalFlip = flip;
  }

  @Override
  public void setIsStreamVerticalFlip(boolean flip) {
    isStreamVerticalFlip = flip;
  }

  @Override
  public void setIsPreviewHorizontalFlip(boolean flip) {
    isPreviewHorizontalFlip = flip;
  }

  @Override
  public void setIsPreviewVerticalFlip(boolean flip) {
    isPreviewVerticalFlip = flip;
  }

  @Override
  public void muteVideo() {
    muteVideo = true;
  }

  @Override
  public void unMuteVideo() {
    muteVideo = false;
  }

  @Override
  public boolean isVideoMuted() {
    return muteVideo;
  }

  @Override
  public void setForceRender(boolean enabled, int fps) {
    forceRenderer.setEnabled(enabled, fps);
  }

  @Override
  public void setForceRender(boolean enabled) {
    setForceRender(enabled, 5);
  }

  @Override
  public boolean isRunning() {
    return running.get();
  }

  @Override
  public void setEncoderSize(int width, int height) {
    this.encoderWidth = width;
    this.encoderHeight = height;
  }

  @Override
  public Point getEncoderSize() {
    return new Point(encoderWidth, encoderHeight);
  }

  @Override
  public void takePhoto(TakePhotoCallback takePhotoCallback) {
    this.takePhotoCallback = takePhotoCallback;
  }

  private void draw(boolean forced) {
    if (!isRunning() || fpsLimiter.limitFPS()) return;
    if (!forced) forceRenderer.frameAvailable();

    if (surfaceManager.isReady() && mainRender.isReady()) {
      try {
        surfaceManager.makeCurrent();
        mainRender.updateFrame();
        mainRender.drawOffScreen();

        // 核心修复点：动态判断当前物理屏幕方向，并调用针对竖屏/横屏自适应的 drawScreenPreview
        // 彻底解决 streamWidth/Height 未按 isPortrait 旋转导致竖屏画面被纵向拉长 13.1% 的核心缺陷
        boolean isPortrait = getContext().getResources().getConfiguration().orientation == Configuration.ORIENTATION_PORTRAIT;
        mainRender.drawScreenPreview(previewWidth, previewHeight, isPortrait, aspectRatioMode, 0,
            isPreviewVerticalFlip, isPreviewHorizontalFlip);
        surfaceManager.swapBuffer();
      } catch (Exception e) {
        Log.w(TAG, "draw preview safely ignored: " + e.getMessage());
      }
    }

    if (!filterQueue.isEmpty() && mainRender.isReady()) {
      try {
        Filter filter = filterQueue.take();
        mainRender.setFilterAction(filter.filterAction, filter.position, filter.baseFilterRender);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        return;
      }
    }
    if (surfaceManagerEncoder.isReady() && mainRender.isReady()) {
      int w = muteVideo ? 0 : encoderWidth;
      int h = muteVideo ? 0 : encoderHeight;
      try {
        surfaceManagerEncoder.makeCurrent();
        mainRender.drawScreen(w, h, aspectRatioMode,
            streamRotation, isStreamVerticalFlip, isStreamHorizontalFlip);
        surfaceManagerEncoder.swapBuffer();
      } catch (Exception e) {
        Log.w(TAG, "draw encoder safely ignored: " + e.getMessage());
      }
    }
    if (takePhotoCallback != null && surfaceManagerPhoto.isReady() && mainRender.isReady()) {
      try {
        surfaceManagerPhoto.makeCurrent();
        mainRender.drawScreen(encoderWidth, encoderHeight, aspectRatioMode,
            streamRotation, isStreamVerticalFlip, isStreamHorizontalFlip);
        takePhotoCallback.onTakePhoto(GlUtil.getBitmap(encoderWidth, encoderHeight));
        takePhotoCallback = null;
        surfaceManagerPhoto.swapBuffer();
      } catch (Exception e) {
        Log.w(TAG, "takePhoto safely ignored: " + e.getMessage());
      }
    }
  }

  @Override
  public void addMediaCodecSurface(Surface surface) {
    ExecutorService executor = this.executor;
    if (executor == null) return;
    ExtensionsKt.secureSubmit(executor, () -> {
      if (surfaceManager.isReady()) {
        surfaceManagerPhoto.release();
        surfaceManagerEncoder.release();
        surfaceManagerEncoder.eglSetup(surface, surfaceManager);
        surfaceManagerPhoto.eglSetup(encoderWidth, encoderHeight, surfaceManagerEncoder);
      }
      return null;
    });
  }

  @Override
  public void removeMediaCodecSurface() {
    threadQueue.clear();
    ExecutorService executor = this.executor;
    if (executor == null) return;
    ExtensionsKt.secureSubmit(executor, () -> {
      surfaceManagerPhoto.release();
      surfaceManagerEncoder.release();
      surfaceManagerPhoto.eglSetup(encoderWidth, encoderHeight, surfaceManager);
      return null;
    });
  }

  @Override
  public void start() {
    wasRunning = true;
    Surface surface = getHolder().getSurface();
    if (surface == null || !surface.isValid()) {
      Log.w(TAG, "start: underlying surface not yet valid");
      return;
    }
    if (running.get()) {
      Log.i(TAG, "start: renderer already running");
      return;
    }
    final int w = encoderWidth > 0 ? encoderWidth : 1920;
    final int h = encoderHeight > 0 ? encoderHeight : 1080;
    executor = ExtensionsKt.newSingleThreadExecutor(threadQueue);
    ExecutorService executor = this.executor;
    if (executor == null) return;
    ExtensionsKt.secureSubmit(executor, () -> {
      try {
        surfaceManager.release();
        surfaceManager.eglSetup(getHolder().getSurface());
        surfaceManager.makeCurrent();
        mainRender.initGl(getContext(), w, h, w, h);
        surfaceManagerPhoto.release();
        surfaceManagerPhoto.eglSetup(w, h, surfaceManager);
        running.set(true);
        mainRender.getSurfaceTexture().setOnFrameAvailableListener(this);
        forceRenderer.start(() -> {
          ExecutorService ex = this.executor;
          if (ex == null) return null;
          ex.execute(() -> draw(true));
          return null;
        });
      } catch (Exception e) {
        Log.e(TAG, "start eglSetup error: " + e.getMessage(), e);
        running.set(false);
      }
      return null;
    });
  }

  @Override
  public void stop() {
    running.set(false);
    threadQueue.clear();
    ExecutorService executor = this.executor;
    if (executor == null) return;
    ExtensionsKt.secureSubmit(executor, () -> {
      try {
        forceRenderer.stop();
        surfaceManagerPhoto.release();
        surfaceManagerEncoder.release();
        surfaceManager.release();
        mainRender.release();
      } catch (Exception e) {
        Log.w(TAG, "stop release safely ignored: " + e.getMessage());
      }
      return null;
    });
    executor.shutdown();
    this.executor = null;
  }

  @Override
  public void onFrameAvailable(SurfaceTexture surfaceTexture) {
    if (!isRunning()) return;
    ExecutorService ex = this.executor;
    if (ex == null) return;
    ex.execute(() -> draw(false));
  }

  @Override
  public void surfaceCreated(@NonNull SurfaceHolder holder) {
    Log.i(TAG, "surfaceCreated: surface is now valid");
    isSurfaceReady = true;
    if (surfaceListener != null) {
      surfaceListener.onSurfaceCreated(this);
    }
  }

  @Override
  public void surfaceChanged(@NonNull SurfaceHolder holder, int format, int width, int height) {
    this.previewWidth = width;
    this.previewHeight = height;
    mainRender.setPreviewSize(previewWidth, previewHeight);
    if (surfaceListener != null) {
      surfaceListener.onSurfaceChanged(this, width, height);
    }
  }

  @Override
  public void surfaceDestroyed(@NonNull SurfaceHolder holder) {
    Log.i(TAG, "surfaceDestroyed: surface destroyed by system");
    isSurfaceReady = false;
    stop();
    if (surfaceListener != null) {
      surfaceListener.onSurfaceDestroyed(this);
    }
  }
}

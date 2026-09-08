import React from 'react';
import { requireNativeComponent, ViewProps, Platform, View, StyleSheet } from 'react-native';

interface PdkCameraNativeViewProps extends ViewProps {}

const NativeCamera =
  Platform.OS === 'android'
    ? requireNativeComponent<PdkCameraNativeViewProps>('PdkCameraView')
    : null;

/**
 * 智播原生摄像头取景视图 (Android SurfaceView / OpenGlView)
 * 由 Android 端 PdkCameraViewManager 提供原生硬件级 GLSurfaceView 渲染管线
 */
export const PdkCameraNativeView: React.FC<PdkCameraNativeViewProps> = (props) => {
  if (NativeCamera) {
    return <NativeCamera {...props} />;
  }
  return <View {...props} style={[styles.fallback, props.style]} />;
};

const styles = StyleSheet.create({
  fallback: {
    backgroundColor: '#0a0f1d',
  },
});

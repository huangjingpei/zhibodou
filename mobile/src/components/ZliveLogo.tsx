import React from 'react';
import { StyleSheet, View, Image, ViewStyle } from 'react-native';

interface ZliveLogoProps {
  size?: number;
  style?: ViewStyle;
}

/**
  Zlive 现代鲜明多色折纸图标组件 (Gmail 风格)
  基于 Google 多彩几何折叠语言，融合极光蓝、活力黄、正红与翠绿
 */
export const ZliveLogo: React.FC<ZliveLogoProps> = ({ size = 64, style }) => {
  return (
    <View style={[{ width: size, height: size }, styles.container, style]}>
      <Image
        source={require('../assets/zlive_logo.png')}
        style={{ width: size, height: size }}
        resizeMode="contain"
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    justifyContent: 'center',
    alignItems: 'center',
  },
});

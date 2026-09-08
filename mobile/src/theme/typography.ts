import { Platform, TextStyle } from 'react-native';

export const Typography = {
  h1: {
    fontSize: 26,
    fontWeight: '700',
    letterSpacing: -0.5,
    ...Platform.select({
      ios: { fontFamily: 'System' },
      android: { fontFamily: 'sans-serif-medium' },
    }),
  } as TextStyle,

  h2: {
    fontSize: 20,
    fontWeight: '600',
    letterSpacing: -0.3,
  } as TextStyle,

  h3: {
    fontSize: 16,
    fontWeight: '600',
  } as TextStyle,

  body: {
    fontSize: 14,
    fontWeight: '400',
    lineHeight: 20,
  } as TextStyle,

  bodySmall: {
    fontSize: 12,
    fontWeight: '400',
    lineHeight: 16,
  } as TextStyle,

  mono: {
    fontSize: 13,
    fontWeight: '500',
    ...Platform.select({
      ios: { fontFamily: 'Menlo' },
      android: { fontFamily: 'monospace' },
    }),
  } as TextStyle,

  badge: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
  } as TextStyle,
};

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 14,
  lg: 20,
  xl: 28,
  xxl: 36,
};

export const Radius = {
  sm: 6,
  md: 12,
  lg: 18,
  full: 999,
};

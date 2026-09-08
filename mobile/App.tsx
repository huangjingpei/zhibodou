import React, { useState } from 'react';
import { StyleSheet, View, SafeAreaView } from 'react-native';
import { Colors } from './src/theme/colors';
import { LoginScreen } from './src/screens/LoginScreen';
import { LiveScreen } from './src/screens/LiveScreen';
import { ProfileScreen } from './src/screens/ProfileScreen';
import { LoginResult } from './src/api/types';

type ScreenName = 'LOGIN' | 'LIVE' | 'PROFILE';

/**
 * 智播豆移动端应用根入口与路由控制器
 */
export default function App() {
  const [currentScreen, setCurrentScreen] = useState<ScreenName>('LOGIN');
  const [loginResult, setLoginResult] = useState<LoginResult | null>(null);

  const handleLoginSuccess = (result: LoginResult) => {
    setLoginResult(result);
    setCurrentScreen('LIVE');
  };

  const handleLogout = () => {
    setLoginResult(null);
    setCurrentScreen('LOGIN');
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.rootContainer}>
        {currentScreen === 'LOGIN' && (
          <LoginScreen onLoginSuccess={handleLoginSuccess} />
        )}

        {currentScreen === 'LIVE' && loginResult && (
          <LiveScreen
            loginResult={loginResult}
            onNavigateProfile={() => setCurrentScreen('PROFILE')}
          />
        )}

        {currentScreen === 'PROFILE' && loginResult && (
          <ProfileScreen
            loginResult={loginResult}
            onBack={() => setCurrentScreen('LIVE')}
            onLogout={handleLogout}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  rootContainer: {
    flex: 1,
  },
});

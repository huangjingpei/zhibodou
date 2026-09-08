# Fix 16 KB Page Size Compatibility Issue

The project is currently producing an APK that is incompatible with 16 KB page size devices because its native libraries have LOAD segments aligned to 4 KB boundaries. This is a common issue for React Native 0.76 and older projects when built with legacy NDK versions or default packaging settings.

## Proposed Changes

### Build Configuration

#### [MODIFY] [build.gradle](file:///E:/zhibodou/mobile/android/build.gradle)
- Upgrade `ndkVersion` to **r28** (`28.0.12433566`) which supports 16 KB alignment by default.
- Upgrade `buildToolsVersion` to **35.0.0** or **36.0.0** to ensure tools like `zipalign` handle 16 KB boundaries correctly.

#### [MODIFY] [app/build.gradle](file:///E:/zhibodou/mobile/android/app/build.gradle)
- Add `packaging` configuration to set `useLegacyPackaging = true`. This forces native libraries to be compressed in the APK and extracted at install time, which serves as a robust compatibility workaround for libraries that are not yet 16 KB aligned (such as prebuilts in React Native 0.76).

## Verification Plan

### Automated Tests
- Run `./gradlew :app:assembleDebug` to ensure the build still succeeds.
- Run `zipalign -c -P 16 -v 4 <apk_path>` to verify that the APK now satisfies the 16 KB alignment requirement.

### Manual Verification
- The user should test the generated APK on a 16 KB Android Emulator or a device with the 16 KB developer option enabled to confirm it no longer crashes or shows compatibility warnings.

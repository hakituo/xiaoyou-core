# Aveline Android 使用说明

## 简介
Aveline Android 是一个轻量本地伴随应用，支持：
- 私聊界面与本地后端对接（HTTP）
- 悬浮窗状态提示（Idle/Analyzing/Danger）
- 无障碍服务长按音量键触发屏幕分析
- TTS 语音播放（后端返回的 Base64 音频）

最低支持 Android 8.0（API 26），目标 API 34。

## 安装
有两种方式安装：
- 使用 Android Studio：打开 `android` 目录 → Build → Build APK(s) → 生成 `app-debug.apk` 并安装到设备
- 使用 Gradle（需要安装 Gradle）：在 `android` 目录执行 `gradle assembleDebug`，输出位于 `app/build/outputs/apk/debug/app-debug.apk`

提示：Release 包需要签名；如需发布生产包，请使用 Android Studio 生成签名并在 `app/build.gradle` 配置 `signingConfigs` 与 `buildTypes.release`。

## 首次运行与权限
- 悬浮窗：在主界面点击“浮窗”按钮，系统将弹出授权页面，请允许悬浮窗权限
- 无障碍：进入系统设置 → 辅助功能 → 启用 “Aveline 无障碍服务”，用于拦截按键与触发分析
- 网络：应用默认允许明文 HTTP（已开启 `usesCleartextTraffic`），建议后端部署在局域网

## 配置后端地址
- 主界面的服务器地址输入框支持 `IP:端口` 或完整 `http://...` 地址
- 点击“保存”后，会保存到 `SharedPreferences` 并立即生效
- 默认值为 `10.0.2.2:5000`（Android 模拟器指向宿主机）

## 使用步骤
1. 打开应用，配置服务器地址
2. 点击“浮窗”并授权，右上角出现状态徽标
3. 在聊天输入框输入消息并发送，应用会调用后端 `/api/v1/message` 接口，返回文本与可选音频
4. 长按音量减键，触发屏幕分析：
   - 应用捕获当前屏幕并编码为 Base64 JPEG 上传 `/api/v1/analyze_screen`
   - 悬浮窗显示 `Analyzing` 状态；如返回 `label=fraud`，显示 `Danger`
   - 若返回 `audio_base64`，自动播放语音

## 接口约定
- `/api/v1/message`：请求 `{ content: string }`，返回包含 `content` 或 `reply` 字段，以及可选 `audio`/`audio_base64`
- `/api/v1/analyze_screen`：请求 `{ image_base64: dataUrl }`，返回包含 `label` 与可选 `audio_base64`

## 注意事项
- Android 9+ 默认禁用明文 HTTP；本应用已配置 `usesCleartextTraffic=true`，请确保后端在可信网络
- 悬浮窗与无障碍需用户主动授权；若未授权，相关功能不可用
- 音频播放采用临时文件缓存，播放完成后自动释放资源

## 构建说明
- 项目使用 Kotlin 1.9.22、AGP 8.3.0、compileSdk 34、minSdk 26、targetSdk 34
- ProGuard/R8 已开启（release）：
  - `minifyEnabled=true`、`shrinkResources=true`
  - `proguard-rules.pro` 已添加 OkHttp/Okio 保留与警告忽略规则
- 若使用 Gradle CLI，请确保环境安装并匹配 AGP 要求（Gradle ≥ 8.4）

## 常见问题
- 连接失败：检查地址是否包含协议（例如 `http://192.168.1.100:5000`）
- 无法播放音频：确认后端返回的是有效 `data:audio/wav;base64,...` 或兼容格式的 Data URL
- 无障碍不触发：确认已启用服务，且系统允许过滤按键（配置见 `res/xml/accessibility_config.xml`）

## 目录结构
- `app/src/main/java/com/aveline/core`：核心逻辑（网络/音频/悬浮窗/无障碍/捕获）
- `app/src/main/res`：布局、样式与 XML 配置
- `app/src/main/AndroidManifest.xml`：权限与组件声明
- `app/build.gradle`：应用构建配置
- `build.gradle`、`settings.gradle`：项目级配置

如需定制 UI 或行为，可修改 `MainActivity.kt`、`AvelineOverlay.kt` 与布局文件。

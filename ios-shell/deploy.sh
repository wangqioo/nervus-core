#!/bin/bash
set -e

DEVICE_ID="00008150-001C44E20288401C"
PROJECT="ios/App/App.xcodeproj"
SCHEME="App"
APP_PATH="/Users/wq/Library/Developer/Xcode/DerivedData/App-gxyyvzcywzxduibpweefbhzydvzm/Build/Products/Debug-iphoneos/App.app"

echo "▶ 同步 Web 资源..."
npx cap sync ios

echo "▶ 编译..."
xcodebuild -project "$PROJECT" -scheme "$SCHEME" \
  -destination "id=$DEVICE_ID" \
  -configuration Debug build 2>&1 | tail -5

echo "▶ 安装到手机..."
xcrun devicectl device install app --device "$DEVICE_ID" "$APP_PATH"

echo "✓ 完成"

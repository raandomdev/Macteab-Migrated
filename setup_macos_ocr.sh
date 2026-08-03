set -euo pipefail

APP_NAME="MacteabMacro"
BUNDLE_ID="com.macteab.macro"
ENTRY_POINT="main.py"
ICON_PATH="lib/official_release.icns"
DATA_DIR="lib"
ARM_PYTHON="${ARM_PYTHON:-python3.13}"
CODESIGN_IDENTITY="${CODESIGN_IDENTITY:--}"

BUILD_DIR="$(pwd)/build_tmp/arm64"
DIST_DIR="$(pwd)/dist"
FINAL_APP="$DIST_DIR/${APP_NAME}-arm64.app"

COMMON_FLAGS=(
    --standalone
    --onefile
    --macos-create-app-bundle
    --macos-app-name="$APP_NAME"
    --macos-signed-app-name="$BUNDLE_ID"
    --macos-app-icon="$ICON_PATH"
    --macos-app-protected-resource="accessibility:$APP_NAME needs Accessibility access to control input"
    --macos-app-protected-resource="screen-capture:$APP_NAME needs Screen Recording access to detect biomes"
    --disable-console
    --include-data-dir="$DATA_DIR=$DATA_DIR"
    --include-package=AppKit
    --include-package=Quartz
    --include-package=ApplicationServices
    --include-package=objc
    --include-package=webview
    --include-package=discord
    --include-package=rapidocr_onnxruntime
    --include-package=pynput
    --assume-yes-for-downloads
)

echo "=============================================="
echo " Building $APP_NAME for arm64"
echo "=============================================="

rm -rf "$BUILD_DIR" "$FINAL_APP"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

"$ARM_PYTHON" -m nuitka \
    --macos-target-arch=arm64 \
    --output-dir="$BUILD_DIR" \
    "${COMMON_FLAGS[@]}" \
    "$ENTRY_POINT"

BUILT_APP="$BUILD_DIR/${ENTRY_POINT%.py}.app"
if [ ! -d "$BUILT_APP" ]; then
    echo "ERROR: build did not produce an .app at $BUILT_APP"
    exit 1
fi

cp -R "$BUILT_APP" "$FINAL_APP"

codesign --force --deep --sign "$CODESIGN_IDENTITY" "$FINAL_APP"
codesign --verify --deep --strict --verbose=2 "$FINAL_APP"

MAIN_BIN="$FINAL_APP/Contents/MacOS/$(basename "${ENTRY_POINT%.py}")"
if [ -f "$MAIN_BIN" ]; then
    lipo -info "$MAIN_BIN" || true
else
    ls "$FINAL_APP/Contents/MacOS/"
fi
pip download --no-deps --platform macosx_11_0_universal2 --python-version 313 --only-binary=:all: pillow -d /tmp/plcheck
echo ""
echo "=============================================="
echo " Done. arm64 app at:"
echo "   $FINAL_APP"
echo "=============================================="
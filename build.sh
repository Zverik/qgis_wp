#!/bin/bash
BUILD_DIR="$(dirname "$0")/build"
SRC_DIR="$(dirname "$0")/walking_papers"
PLUGIN_NAME=walking_papers
TARGET="$BUILD_DIR/$PLUGIN_NAME"
[ -d "$BUILD_DIR" ] && rm -r "$BUILD_DIR"
mkdir -p "$TARGET"
cp "$SRC_DIR"/*.py "$TARGET"
cp -r "$SRC_DIR/icons" "$TARGET"

# Build translations
cp -r "$SRC_DIR/i18n" "$TARGET"
rm "$TARGET/i18n/base.ts"
for i in "$TARGET"/i18n/*.ts; do
  lrelease-qt4 "$i"
  rm "$i"
done

# Build zip
cd "$BUILD_DIR"
zip -9 -r "$PLUGIN_NAME.zip" "$PLUGIN_NAME"
echo "Now upload $BUILD_DIR/$PLUGIN_NAME.zip"

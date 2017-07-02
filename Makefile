BUILD_DIR=build
SRC_DIR=walking_papers
PLUGIN_NAME=walking_papers
TARGET="$(BUILD_DIR)/$(PLUGIN_NAME)"
QGIS_PLUGINS=$(HOME)/.qgis2/python/plugins

default: zip

package:
	if [ -d "$(BUILD_DIR)" ]; then rm -r "$(BUILD_DIR)"; fi
	mkdir -p "$(TARGET)"
	cp "$(SRC_DIR)"/*.py "$(TARGET)"
	cp "$(SRC_DIR)"/metadata.txt "$(TARGET)"
	cp -r "$(SRC_DIR)/icons" "$(TARGET)"
	cp -r "$(SRC_DIR)/res" "$(TARGET)"

	# Build translations
	cp -r "$(SRC_DIR)/i18n" "$(TARGET)"
	rm "$(TARGET)/i18n/base.ts"
	for i in $(TARGET)/i18n/*.ts; do lrelease-qt4 "$$i"; rm "$$i"; done

zip: package
	cd "$(BUILD_DIR)"; zip -9 -r "$(PLUGIN_NAME).zip" "$(PLUGIN_NAME)"
	echo "Now upload $(BUILD_DIR)/$(PLUGIN_NAME).zip"

deploy: package
	if [ -d "$(QGIS_PLUGINS)/$(PLUGIN_NAME)" ]; then rm -r "$(QGIS_PLUGINS)/$(PLUGIN_NAME)"; fi
	cp -r "$(BUILD_DIR)/$(PLUGIN_NAME)" "$(QGIS_PLUGINS)"

trans:
	for i in $(SRC_DIR)/i18n/*.ts; do pylupdate4 -noobsolete $(SRC_DIR)/mainplugin.py -ts "$$i"; done

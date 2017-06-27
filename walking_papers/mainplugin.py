from PyQt4.QtCore import QVariant, QRectF
from PyQt4.QtGui import QMenu, QAction, QIcon, QColor, QFont, QFileDialog
from qgis.core import (
    QgsField,
    QgsMapLayerRegistry,
    QgsVectorLayer,
    QgsFillSymbolV2,
    QgsPalLayerSettings,
    QgsComposerMap,
    QgsComposerLabel,
    QgsComposerObject,
)
from processing import runalg
from processing.tools.system import isWindows
from processing.algs.gdal.GdalUtils import GdalUtils
import os


PIE_LAYER = 'sheets'
PLAN_LAYER = 'pie'
DOWNLOAD_POLYGON_LAYER = 'osm_area'
ROTATION_FIELD = 'rotation'
NAME_FIELD = 'name'


class ProgressMock(object):
    def setInfo(self, s):
        pass

    def setCommand(self, s):
        pass

    def setConsoleInfo(self, s):
        pass


class WalkingPapersPlugin(object):
    def __init__(self, iface):
        self.iface = iface

    def initGui(self):
        self.menu = QMenu(self.iface.mainWindow())
        self.menu.setObjectName("wpMenu")
        self.menu.setTitle("Walking Papers")

        downloadAction = QAction(QIcon(":/plugins/testplug/icon.png"),
                                 "Download OSM Data", self.iface.mainWindow())
        downloadAction.setObjectName("downloadOSM")
        downloadAction.setStatusTip(
            'Downloads data from OpenStreetMap and styles it.')
        downloadAction.triggered.connect(self.downloadOSM)
        self.menu.addAction(downloadAction)

        openAction = QAction(QIcon(":/plugins/testplug/icon.png"),
                             "Open OSM Data", self.iface.mainWindow())
        openAction.setObjectName("openOSM")
        openAction.setStatusTip(
            'Converts OSM data, loads and styles it for walking papers')
        openAction.triggered.connect(self.openOSM)
        self.menu.addAction(openAction)

        pieAction = QAction(QIcon(":/plugins/testplug/icon.png"),
                            "Create Pie Layers", self.iface.mainWindow())
        pieAction.setObjectName("makePie")
        pieAction.setStatusTip(
            'Creates a "{}" and "{}" layers'.format(PIE_LAYER, PLAN_LAYER))
        pieAction.triggered.connect(self.createPie)
        self.menu.addAction(pieAction)

        rotateAction = QAction(QIcon(":/plugins/testplug/icon.png"),
                               "Calculate Pie Rotation", self.iface.mainWindow())
        rotateAction.setObjectName("calcRotation")
        rotateAction.setStatusTip(
            'Adds or updates a "{}" column with degrees.'
            'Requires a "{}" layer.'.format(ROTATION_FIELD, PIE_LAYER))
        rotateAction.triggered.connect(self.calcRotation)
        self.menu.addAction(rotateAction)

        atlasAction = QAction(QIcon(":/plugins/testplug/icon.png"),
                              "Prepare Atlas", self.iface.mainWindow())
        atlasAction.setObjectName("makeAtlas")
        atlasAction.setStatusTip(
            'Creates an atlas in map composer to print walking papers'.format(PIE_LAYER))
        atlasAction.triggered.connect(self.createAtlas)
        self.menu.addAction(atlasAction)

        self.iface.pluginMenu().addMenu(self.menu)

    def unload(self):
        self.menu.deleteLater()

    def calcRotation(self):
        pies = QgsMapLayerRegistry.instance().mapLayersByName(PIE_LAYER)
        if not pies:
            self.iface.messageBar().pushCritical(
                'No layer', 'Please add "{}" layer.'.format(PIE_LAYER))
            return
        pie = pies[0]
        if not pie.featureCount():
            self.iface.messageBar().pushInfo(
                'No data', 'No features in the "{}" layer.'.format(PIE_LAYER))
            return

        rotIndex = pie.dataProvider().fieldNameIndex(ROTATION_FIELD)
        if rotIndex < 0:
            if not self.addFieldToLayer(pie, ROTATION_FIELD, QVariant.Int):
                return
            rotIndex = pie.dataProvider().fieldNameIndex(ROTATION_FIELD)

        boxes = runalg('qgis:orientedminimumboundingbox', pie, True, None)
        boxesLayer = QgsVectorLayer(boxes['OUTPUT'], 'boxes_tmp', 'ogr')
        if not boxesLayer.isValid():
            self.iface.messageBar().pushCritical(
                'Access error', 'Failed to load a temporary processing layer.')
            return

        iterbox = boxesLayer.getFeatures()
        for l in pie.getFeatures():
            box = next(iterbox)
            angle = round(box['ANGLE'])
            if box['WIDTH'] > box['HEIGHT']:
                angle += 90 if angle < 0 else -90
            pie.dataProvider().changeAttributeValues({l.id(): {rotIndex: angle}})
        self.iface.messageBar().pushSuccess('Done', 'Pie rotation values were updated.')

    def createAtlas(self):
        pies = QgsMapLayerRegistry.instance().mapLayersByName(PIE_LAYER)
        if not pies:
            self.iface.messageBar().pushCritical(
                'No layer', 'Please add "{}" layer.'.format(PIE_LAYER))
            return
        pie = pies[0]

        # initialize composer
        view = self.iface.createNewComposer()
        comp = view.composition()
        comp.setPaperSize(210, 297)

        # a map and a label
        atlasMap = QgsComposerMap(comp, 10, 10, 190, 277)
        atlasMap.setId('Map')
        atlasMap.setAtlasDriven(True)
        atlasMap.setAtlasMargin(0)
        atlasMap.setDataDefinedProperty(QgsComposerObject.MapRotation, True, False, '', 'rotation')
        comp.addComposerMap(atlasMap)

        label = QgsComposerLabel(comp)
        label.setId('Label')
        label.setSceneRect(QRectF(10, 10, 50, 10))
        label.setText('[% "name" %]')
        label.setMargin(0)
        font = QFont('PT Sans Caption', 14, QFont.Bold)
        label.setFont(font)
        label.setFontColor(QColor('#0000aa'))
        comp.addComposerLabel(label)

        # setup atlas
        atlas = comp.atlasComposition()
        atlas.setCoverageLayer(pie)
        atlas.setEnabled(True)
        atlas.setHideCoverage(True)

    def addFieldToLayer(self, layer, name, typ):
        if layer.dataProvider().fieldNameIndex(name) < 0:
            layer.dataProvider().addAttributes([QgsField(name, typ)])
            layer.updateFields()
            if layer.dataProvider().fieldNameIndex(name) < 0:
                self.iface.messageBar().pushCritical(
                    'Access error',
                    'Failed to add a "{}" field to the "{}" layer.'.format(name, layer.layerName()))
                return False
        return True

    def createPie(self):
        pies = QgsMapLayerRegistry.instance().mapLayersByName(PIE_LAYER)
        if not pies:
            layerUri = 'Polygon?crs=epsg:3857&field=name:string(30)&field=rotation:integer'
            pie = QgsVectorLayer(layerUri, PIE_LAYER, 'memory')
            QgsMapLayerRegistry.instance().addMapLayer(pie)
        else:
            pie = pies[0]
            if not self.addFieldToLayer(pie, ROTATION_FIELD, QVariant.Int):
                return
            if not self.addFieldToLayer(pie, NAME_FIELD, QVariant.String):
                return

        symbol = QgsFillSymbolV2.createSimple({
            'style': 'no',
            'line_color': '#0000aa',
            'line_width': '1.5'
        })
        pie.rendererV2().setSymbol(symbol)
        label = QgsPalLayerSettings()
        label.readFromLayer(pie)
        label.enabled = True
        label.drawLabels = True
        label.fieldName = 'name'
        label.textFont.setPointSize(14)
        label.textFont.setBold(True)
        label.textColor = QColor('#0000aa')
        label.bufferDraw = True
        label.writeToLayer(pie)

        self.iface.mapCanvas().refresh()

    def openGeoPackage(self, filename=None):
        if not filename:
            filename = QFileDialog.getOpenFileName(
                parent=None,
                caption='Select GeoPackage file',
                filter='GeoPackage File (*.gpkg *.geopackage)')
            if not filename:
                return
        if not os.path.isfile(filename):
            self.iface.messageBar().pushCritical(
                'Open GeoPackage', '{} is not a file'.format(filename))
            return
        filename = os.path.abspath(filename)

        registry = QgsMapLayerRegistry.instance()

        def construct_uri(filename, polygons, subset):
            return '{}|layername={}|subset={}'.format(
                filename,
                'multipolygons' if polygons else 'lines',
                subset)

        roads = QgsVectorLayer(construct_uri(
            filename, False,
            '"highway" IN (\'primary\', \'secondary\', \'tertiary\', '
            '\'residential\', \'unclassified\', \'pedestrian\')'
        ), 'Roads', 'ogr')

        registry.addMapLayer(roads)

        buildings = QgsVectorLayer(construct_uri(filename, True, 'building not null'),
                                   'Buildings', 'ogr')
        buildings.rendererV2().setSymbol(QgsFillSymbolV2.createSimple({
            'style': 'no',
            'line_color': '#aaaaaa',
            'line_width': '0.2'
        }))
        registry.addMapLayer(buildings)
        # TODO

    def openOSM(self, filename=None):
        """Converts an OSM file to GeoPackage, loads and styles it."""
        if not filename:
            filename = QFileDialog.getOpenFileName(
                parent=None,
                caption='Select OpenStreetMap file',
                filter='OSM File (*.osm *.pbf)')
            if not filename:
                return
        if not os.path.isfile(filename):
            self.iface.messageBar().pushCritical(
                'Open OSM', '{} is not a file'.format(filename))
            return
        filename = os.path.abspath(filename)
        gpkgFile = os.path.splitext(filename)[0] + '.gpkg'
        if os.path.isfile(gpkgFile):
            os.remove(gpkgFile)
        iniFile = None  # TODO
        if isWindows():
            cmd = ['cmd.exe', '/C', 'ogr2ogr.exe']
        else:
            cmd = ['ogr2ogr']
        if iniFile:
            cmd.extend(['--config', 'OSM_CONFIG_FILE', iniFile])
        cmd.extend(['-f', 'GPKG', gpkgFile, filename])
        try:
            GdalUtils.runGdal(cmd, ProgressMock())
        except IOError as e:
            self.iface.messageBar().pushCritical(
                'Open OSM', 'Error running ogr2ogr: {}'.format(e))
            return
        if 'FAILURE' in GdalUtils.consoleOutput:
            self.iface.messageBar().pushCritical(
                'Open OSM', 'Error converting OSM to GeoPackage')
            return
        self.openGeoPackage(gpkgFile)

    def downloadOSM(self):
        """Creates a polygon layer if not present, otherwise
        downloads data from overpass based on polygons.
        Then calls openOSM() to convert them to GeoPackage and style."""
        layers = QgsMapLayerRegistry.instance().mapLayersByName(DOWNLOAD_POLYGON_LAYER)
        if not layers:
            layerUri = 'Polygon?crs=epsg:3857'
            layer = QgsVectorLayer(layerUri, DOWNLOAD_POLYGON_LAYER, 'memory')
            QgsMapLayerRegistry.instance().addMapLayer(layer)
            symbol = QgsFillSymbolV2.createSimple({
                'style': 'no',
                'line_color': '#aa0000',
                'line_width': '1.5'
            })
            layer.rendererV2().setSymbol(symbol)
            self.iface.mapCanvas().refresh()
        else:
            layer = layers[0]
        if not layer.featureCount():
            self.iface.messageBar().pushInfo(
                'Download OSM',
                'Draw a polygon in the "{}" layer to download OSM data'
                .format(DOWNLOAD_POLYGON_LAYER))
            return

        filename = QFileDialog.getSaveFileName(
            parent=None,
            caption='Select OpenStreetMap file to write',
            filter='OSM File (*.osm)')
        if not filename:
            return

        polygons = []
        for feature in layer.getFeatures():
            poly = ''  # TODO
            polygons.append(poly)

        # TODO: Get polygons, construct Overpass API query, download data into a file
        self.iface.messageBar().pushWarning(
            'Not implemented', 'Downloading OSM data is yet to be implemented.')

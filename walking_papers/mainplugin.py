# Walking Papers QGIS Plugin
# Copyright (C) 2017 Ilya Zverev
# This code is licensed GPL v3, see the LICENSE file for details.
# And it comes WITHOUT ANY WARRANTY obviously.

from PyQt4.QtCore import QVariant, QRectF, QUrl, QEventLoop
from PyQt4.QtGui import QMenu, QAction, QColor, QFont, QFileDialog, QIcon, QToolButton
from PyQt4.QtNetwork import QNetworkRequest, QNetworkReply
from qgis.core import (
    QgsField,
    QgsMapLayerRegistry,
    QgsVectorLayer,
    QgsFillSymbolV2,
    QgsComposerMap,
    QgsComposerLabel,
    QgsComposerObject,
    QgsNetworkAccessManager,
    QgsMessageLog,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)
from processing import runalg
from processing.tools.system import isWindows
from processing.algs.gdal.GdalUtils import GdalUtils
from .styler import applyStyle, applyLayerStyle
import os
import yaml


PIE_LAYER = 'Pie Sheets'
PLAN_LAYER = 'Pie Overview'
DOWNLOAD_POLYGON_LAYER = 'OSM Download Area'
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
        self.path = os.path.dirname(os.path.realpath(__file__))

    def initGui(self):
        self.menu = QMenu(self.iface.mainWindow())
        self.menu.setObjectName("wpMenu")
        self.menu.setTitle("Walking Papers")
        self.menu.setIcon(QIcon(os.path.join(self.path, "walking_papers.svg")))

        downloadAction = QAction("Download OSM Data", self.iface.mainWindow())
        downloadAction.setObjectName("downloadOSM")
        downloadAction.setStatusTip(
            'Downloads data from OpenStreetMap and styles it.')
        downloadAction.triggered.connect(self.downloadOSM)
        self.menu.addAction(downloadAction)

        openAction = QAction("Open OSM Data", self.iface.mainWindow())
        openAction.setObjectName("openOSM")
        openAction.setStatusTip(
            'Converts OSM data, loads and styles it for walking papers')
        openAction.triggered.connect(self.openOSM)
        self.menu.addAction(openAction)

        pieAction = QAction("Create Pie Layers", self.iface.mainWindow())
        pieAction.setObjectName("makePie")
        pieAction.setStatusTip(
            'Creates a "{}" and "{}" layers'.format(PIE_LAYER, PLAN_LAYER))
        pieAction.triggered.connect(self.createPie)
        self.menu.addAction(pieAction)

        self.menu.addSeparator()

        rotateAction = QAction("Calculate Pie Rotation", self.iface.mainWindow())
        rotateAction.setObjectName("calcRotation")
        rotateAction.setStatusTip(
            'Adds or updates a "{}" column with degrees.'
            'Requires a "{}" layer.'.format(ROTATION_FIELD, PIE_LAYER))
        rotateAction.triggered.connect(self.calcRotation)
        self.menu.addAction(rotateAction)

        atlasAction = QAction("Prepare Atlas", self.iface.mainWindow())
        atlasAction.setObjectName("makeAtlas")
        atlasAction.setStatusTip(
            'Creates an atlas in map composer to print walking papers'.format(PIE_LAYER))
        atlasAction.triggered.connect(self.createAtlas)
        self.menu.addAction(atlasAction)

        self.iface.pluginMenu().addMenu(self.menu)

        self.toolButton = QToolButton()
        self.toolButton.setToolTip("Walking Papers")
        self.toolButton.setMenu(self.menu)
        self.toolButton.setIcon(QIcon(os.path.join(self.path, "walking_papers.svg")))
        self.toolButton.setPopupMode(QToolButton.InstantPopup)
        self.toolbarAction = self.iface.addToolBarWidget(self.toolButton)

    def unload(self):
        self.menu.deleteLater()
        self.iface.removeToolBarIcon(self.toolbarAction)

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
        if pie.isEditable():
            self.iface.vectorLayerTools().saveEdits(pie)

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
        atlas.setSingleFile(True)
        comp.refreshItems()

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

        applyLayerStyle(pie, {
            'fill': {
                'style': 'no',
                'line-color': '#0000aa',
                'line-width': '1',
            },
            'label': {
                'field': 'name',
                'font-size': 14,
                'font-weight': 'bold',
                'color': '#0000aa',
                'buffer-color': '#ffffff',
            }
        })
        self.iface.legendInterface().refreshLayerSymbology(pie)

        overviews = QgsMapLayerRegistry.instance().mapLayersByName(PLAN_LAYER)
        if not overviews:
            layerUri = 'LineString?crs=epsg:3857'
            overview = QgsVectorLayer(layerUri, PLAN_LAYER, 'memory')
            QgsMapLayerRegistry.instance().addMapLayer(overview)
        else:
            overview = overviews[0]
        applyLayerStyle(overview, {
            'line': {
                'line-color': '#0000aa',
                'line-width': '2',
            }
        })
        self.iface.legendInterface().refreshLayerSymbology(overview)

        self.iface.mapCanvas().refresh()
        self.iface.messageBar().pushInfo(
            'Pie',
            'Now sketch pie on the "{}" layer and then split it into rectangle sheets '
            'on the "{}" layer. After that choose "Calculate Rotation" '
            'and then "Prepare Atlas".'
            .format(PLAN_LAYER, PIE_LAYER))

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

        styleFile = os.path.join(self.path, 'wp_style.yaml')
        with open(styleFile, 'r') as f:
            style = yaml.load(f)
        applyStyle(filename, style)
        for layer in self.iface.legendInterface().layers():
            self.iface.legendInterface().refreshLayerSymbology(layer)
        self.createPie()

    def openOSM(self, filename=None):
        """Converts an OSM file to GeoPackage, loads and styles it."""
        if not filename:
            filename = QFileDialog.getOpenFileName(
                parent=None,
                caption='Select OpenStreetMap file',
                filter='OSM or GeoPackage File (*.osm *.pbf *.gpkg)')
            if not filename:
                return
        if not os.path.isfile(filename):
            self.iface.messageBar().pushCritical(
                'Open OSM', '{} is not a file'.format(filename))
            return
        filename = os.path.abspath(filename)
        gpkgFile = os.path.splitext(filename)[0] + '.gpkg'
        if filename.endswith('.gpkg'):
            self.openGeoPackage(filename)
            return

        if os.path.isfile(gpkgFile):
            os.remove(gpkgFile)
        if isWindows():
            cmd = ['cmd.exe', '/C', 'ogr2ogr.exe']
        else:
            cmd = ['ogr2ogr']

        cmd.extend(['--config', 'OSM_USE_CUSTOM_INDEXING', 'NO'])
        iniFile = os.path.join(self.path, 'osmconf.ini')
        cmd.extend(['--config', 'OSM_CONFIG_FILE', iniFile])
        cmd.extend(['-t_srs', 'EPSG:3857'])
        cmd.extend(['-overwrite'])
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
            layerUri = 'Polygon?crs=epsg:4326'
            layer = QgsVectorLayer(layerUri, DOWNLOAD_POLYGON_LAYER, 'memory')
            QgsMapLayerRegistry.instance().addMapLayer(layer)
            symbol = QgsFillSymbolV2.createSimple({
                'style': 'no',
                'line_color': '#aa0000',
                'line_width': '1.5'
            })
            layer.rendererV2().setSymbol(symbol)
            self.iface.mapCanvas().refresh()
            downloadAction = QAction("Download OSM Data", self.iface.legendInterface())
            downloadAction.triggered.connect(self.downloadOSM)
            self.iface.legendInterface().addLegendLayerActionForLayer(downloadAction, layer)
        else:
            layer = layers[0]
        if not layer.featureCount():
            self.iface.setActiveLayer(layer)
            self.iface.vectorLayerTools().startEditing(layer)
            self.iface.messageBar().pushInfo(
                'Download OSM',
                'Draw a polygon in the "{}" layer and the choose the same '
                'menu item to download object in the polygon'
                .format(DOWNLOAD_POLYGON_LAYER))
            return
        if layer.isEditable():
            self.iface.vectorLayerTools().saveEdits(layer)

        filename = QFileDialog.getSaveFileName(
            parent=None,
            caption='Select OpenStreetMap file to write',
            filter='OSM File (*.osm)')
        if not filename:
            return

        xform = QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem(4326))
        polygons = []
        for feature in layer.getFeatures():
            points = map(xform.transform, feature.geometry().asPolygon()[0])
            poly = ' '.join(['{:.6f} {:.6f}'.format(qp.y(), qp.x()) for qp in points])
            polygons.append(poly)
        query = '[out:xml][timeout:250];('
        query += ''.join(['node(poly:"{}");<;'.format(p) for p in polygons])
        query += ');out body qt;'

        url = QUrl('http://overpass-api.de/api/interpreter')
        url.addEncodedQueryItem('data', QUrl.toPercentEncoding(query))
        url.setPort(80)

        request = QNetworkRequest(url)
        request.setRawHeader('User-Agent', 'QGIS_wp')
        network = QgsNetworkAccessManager.instance()
        reply = network.get(request)
        loop = QEventLoop()
        network.finished.connect(loop.quit)
        loop.exec_()

        data = reply.readAll()
        if (not data or '<remark> runtime error' in data or
                '<node' not in data or reply.error() != QNetworkReply.NoError):
            QgsMessageLog.logMessage('Overpass API reply: ' + str(data))
            self.iface.messageBar().pushCritical(
                'Download error',
                'Failed to download data from Overpass API. See log for details')
        else:
            with open(filename, 'wb') as f:
                f.write(data)
            # Remove the polygon layer and hide any OSM layers used to draw it
            for n, l in QgsMapLayerRegistry.instance().mapLayers().iteritems():
                if 'OSM' in n or 'openstreetmap' in n.lower():
                    self.iface.legendInterface().setLayerVisible(l, False)
            QgsMapLayerRegistry.instance().removeMapLayer(layer)
            self.openOSM(filename)

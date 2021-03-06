# Walking Papers QGIS Plugin
# Copyright (C) 2017 Ilya Zverev
# This code is licensed GPL v3, see the LICENSE file for details.
# And it comes WITHOUT ANY WARRANTY obviously.

from PyQt4.QtCore import (
    QCoreApplication,
    QEventLoop,
    QRectF,
    QSettings,
    QTranslator,
    QUrl,
    QVariant,
)
from PyQt4.QtGui import (
    QAction,
    QColor,
    QFileDialog,
    QFont,
    QIcon,
    QMenu,
    QMessageBox,
    QToolButton,
)
from PyQt4.QtNetwork import (
    QNetworkReply,
    QNetworkRequest,
)
from qgis.core import (
    QgsComposerLabel,
    QgsComposerMap,
    QgsComposerObject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsField,
    QgsFillSymbolV2,
    QgsGeometry,
    QgsMapLayerRegistry,
    QgsMessageLog,
    QgsNetworkAccessManager,
    QgsVectorLayer,
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
ROTATION_LAYER = 'Pie Sheets For Atlas'
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
        locale = QSettings().value("locale/userLocale")[0:2]
        localePath = os.path.join(self.path, 'i18n', '{}.qm'.format(locale))
        if os.path.exists(localePath):
            self.translator = QTranslator()
            self.translator.load(localePath)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, text):
        return QCoreApplication.translate('WalkingPapersPlugin', text)

    def initGui(self):
        self.menu = QMenu(self.iface.mainWindow())
        self.menu.setObjectName("wpMenu")
        self.menu.setTitle(self.tr(u"Walking Papers"))
        self.menu.setIcon(QIcon(os.path.join(self.path, "icons", "walking_papers.svg")))

        downloadAction = QAction(self.tr(u"Download OSM Data"), self.iface.mainWindow())
        downloadAction.setObjectName("downloadOSM")
        downloadAction.setStatusTip(
            self.tr(u'Downloads data from OpenStreetMap and styles it.'))
        downloadAction.triggered.connect(self.downloadOSM)
        self.menu.addAction(downloadAction)

        openAction = QAction(self.tr(u"Open OSM Data"), self.iface.mainWindow())
        openAction.setObjectName("openOSM")
        openAction.setStatusTip(
            self.tr(u'Converts OSM data, loads and styles it for walking papers'))
        openAction.triggered.connect(self.openOSM)
        self.menu.addAction(openAction)

        pieAction = QAction(self.tr(u"Create Pie Layers"), self.iface.mainWindow())
        pieAction.setObjectName("makePie")
        pieAction.setStatusTip(
            self.tr(u'Creates pie sheets and pie overview layers'))
        pieAction.triggered.connect(self.createPie)
        self.menu.addAction(pieAction)

        self.menu.addSeparator()

        atlasAction = QAction(self.tr(u"Prepare Atlas"), self.iface.mainWindow())
        atlasAction.setObjectName("makeAtlas")
        atlasAction.setStatusTip(
            self.tr(u'Creates an atlas in map composer to print walking papers').format(PIE_LAYER))
        atlasAction.triggered.connect(self.createAtlas)
        self.menu.addAction(atlasAction)

        self.iface.pluginMenu().addMenu(self.menu)

        self.toolButton = QToolButton()
        self.toolButton.setToolTip(self.tr(u"Walking Papers"))
        self.toolButton.setMenu(self.menu)
        self.toolButton.setIcon(QIcon(os.path.join(self.path, "icons", "walking_papers.svg")))
        self.toolButton.setPopupMode(QToolButton.InstantPopup)
        self.toolbarAction = self.iface.addToolBarWidget(self.toolButton)

    def unload(self):
        self.menu.deleteLater()
        self.iface.removeToolBarIcon(self.toolbarAction)

    def createRotationLayer(self):
        pies = QgsMapLayerRegistry.instance().mapLayersByName(PIE_LAYER)
        if not pies:
            self.iface.messageBar().pushCritical(
                self.tr(u'No layer'), self.tr(u'Please add "{}" layer.').format(PIE_LAYER))
            return
        pie = pies[0]
        if not pie.featureCount():
            self.iface.messageBar().pushInfo(
                self.tr(u'No data'), self.tr(u'No features in the "{}" layer.').format(PIE_LAYER))
            return
        if pie.isEditable():
            self.iface.vectorLayerTools().saveEdits(pie)

        boxes = runalg('qgis:orientedminimumboundingbox', pie, True, None)
        boxesLayer = QgsVectorLayer(boxes['OUTPUT'], ROTATION_LAYER, 'ogr')
        if not boxesLayer.isValid():
            self.iface.messageBar().pushCritical(
                self.tr(u'Access error'), self.tr(u'Failed to load a temporary processing layer.'))
            return

        self.addFieldToLayer(boxesLayer, NAME_FIELD, QVariant.String)
        rotIndex = boxesLayer.dataProvider().fieldNameIndex('ANGLE')
        nameIndex = boxesLayer.dataProvider().fieldNameIndex(NAME_FIELD)
        iterpie = pie.getFeatures()
        for box in boxesLayer.getFeatures():
            name = next(iterpie)['name']
            angle = round(box['ANGLE'])
            if box['WIDTH'] > box['HEIGHT']:
                angle += 90 if angle < 0 else -90
            geom = QgsGeometry(box.geometry())
            geom.rotate(angle, box.geometry().boundingBox().center())
            boxesLayer.dataProvider().changeAttributeValues(
                {box.id(): {rotIndex: angle, nameIndex: name}})
            boxesLayer.dataProvider().changeGeometryValues({box.id(): geom})
        QgsMapLayerRegistry.instance().addMapLayer(boxesLayer)
        self.iface.legendInterface().setLayerVisible(boxesLayer, False)
        self.iface.legendInterface().setLayerVisible(pie, False)
        return boxesLayer

    def createAtlas(self):
        pie = self.createRotationLayer()

        # initialize composer
        view = self.iface.createNewComposer()
        comp = view.composition()
        comp.setPaperSize(210, 297)

        # a map and a label
        atlasMap = QgsComposerMap(comp, 10, 10, 190, 277)
        atlasMap.setId('Map')
        atlasMap.setAtlasDriven(True)
        atlasMap.setAtlasMargin(0)
        atlasMap.setDataDefinedProperty(QgsComposerObject.MapRotation, True, False, '', 'ANGLE')
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
                    self.tr(u'Access error'),
                    self.tr(u'Failed to add a "{}" field to the "{}" layer.')
                        .format(name, layer.layerName()))
                return False
        return True

    def checkCrs(self):
        settings = self.iface.mapCanvas().mapSettings()
        crs = settings.destinationCrs().authid()
        if '3857' not in crs and '900913' not in crs:
            # Suggest changing
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                self.tr(u'Projection Warning'),
                self.tr(u'Your project\'s map projection may not preserve angles. '
                        'This is bad for understanding the map in walking papers. '
                        'Do you want to change it to EPSG:3857?'),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Yes:
                self.iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem(3857))
                self.iface.mapCanvas().setCrsTransformEnabled(True)
            elif answer == QMessageBox.Cancel:
                return False
        return True

    def createPie(self):
        # This is a good place to check that the project crs is "equal angle"
        if not self.checkCrs():
            return

        pies = QgsMapLayerRegistry.instance().mapLayersByName(PIE_LAYER)
        if not pies:
            layerUri = 'Polygon?crs=epsg:3857&field=name:string(30)&field=rotation:integer'
            pie = QgsVectorLayer(layerUri, PIE_LAYER, 'memory')
            QgsMapLayerRegistry.instance().addMapLayer(pie)
        else:
            pie = pies[0]
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
            self.tr(u'Done'),
            self.tr(u'Now sketch pie on the "{}" layer and then split it into rectangle sheets '
                    'on the "{}" layer. After that choose "{}" '
                    'and then "{}".')
            .format(PLAN_LAYER, PIE_LAYER,
                    self.tr(u'Calculate Pie Rotation'),
                    self.tr(u'Prepare Atlas')))

    def openGeoPackage(self, filename=None):
        if not filename:
            filename = QFileDialog.getOpenFileName(
                parent=None,
                caption=self.tr(u'Select GeoPackage file'),
                filter=self.tr(u'GeoPackage File') + u' (*.gpkg *.geopackage)')
        if not filename or not os.path.isfile(filename):
            return
        filename = os.path.abspath(filename)

        styleFile = os.path.join(self.path, 'res', 'wp_style.yaml')
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
                caption=self.tr(u'Select OpenStreetMap file'),
                filter=self.tr(u'OSM or GeoPackage File') + u' (*.osm *.pbf *.gpkg)')
        if not filename or not os.path.isfile(filename):
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
        iniFile = os.path.join(self.path, 'res', 'osmconf.ini')
        cmd.extend(['--config', 'OSM_CONFIG_FILE', iniFile])
        cmd.extend(['-t_srs', 'EPSG:3857'])
        cmd.extend(['-overwrite'])
        cmd.extend(['-f', 'GPKG', gpkgFile, filename])
        try:
            GdalUtils.runGdal(cmd, ProgressMock())
        except IOError as e:
            self.iface.messageBar().pushCritical(
                self.tr(u'Open OSM Data'), self.tr(u'Error running ogr2ogr: {}').format(e))
            return
        if 'FAILURE' in GdalUtils.consoleOutput:
            self.iface.messageBar().pushCritical(
                self.tr(u'Open OSM Data'), self.tr(u'Error converting OSM to GeoPackage.'))
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
        else:
            layer = layers[0]
        if not layer.featureCount():
            self.iface.setActiveLayer(layer)
            self.iface.vectorLayerTools().startEditing(layer)
            self.iface.messageBar().pushInfo(
                self.tr(u'Download OSM Data'),
                self.tr(u'Draw a polygon in the "{}" layer and the choose the same '
                        'menu item to download object in the polygon.')
                .format(DOWNLOAD_POLYGON_LAYER))
            return
        if layer.isEditable():
            self.iface.vectorLayerTools().saveEdits(layer)

        filename = QFileDialog.getSaveFileName(
            parent=None,
            caption=self.tr(u'Select OpenStreetMap file to write'),
            filter=self.tr(u'OSM File') + u' (*.osm)')
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
                self.tr(u'Download error'),
                self.tr(u'Failed to download data from Overpass API. See log for details.'))
        else:
            with open(filename, 'wb') as f:
                f.write(data)
            # Remove the polygon layer and hide any OSM layers used to draw it
            for n, l in QgsMapLayerRegistry.instance().mapLayers().iteritems():
                if 'OSM' in n or 'openstreetmap' in n.lower():
                    self.iface.legendInterface().setLayerVisible(l, False)
            QgsMapLayerRegistry.instance().removeMapLayer(layer)
            self.openOSM(filename)

from PyQt4.QtCore import QVariant, QRectF
from PyQt4.QtGui import QMenu, QAction, QIcon, QColor, QFont
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


PIE_LAYER = 'sheets'
PLAN_LAYER = 'pie'
ROTATION_FIELD = 'rotation'
NAME_FIELD = 'name'


class WalkingPapersPlugin:
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

        # delete pie composer views if present
        # TODO: Does not work
        for c in self.iface.activeComposers():
            if c.windowTitle() == 'pie':
                self.iface.deleteComposer(c)

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
            pie = QgsVectorLayer(layerUri, 'pie_layer', 'memory')
            pie.setLayerName(PIE_LAYER)
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

    def styleOSM(self):
        self.iface.messageBar().pushWarning(
            'Not implemented', 'Styling OSM data is yet to be implemented.')

    def openOSM(self, filename=None):
        """Converts an OSM file to GeoPackage, loads and styles it."""
        self.iface.messageBar().pushWarning(
            'Not implemented', 'Opening OSM data is yet to be implemented.')

    def downloadOSM(self):
        """Creates a polygon layer if not present, otherwise
        downloads data from overpass based on polygons.
        Then calls openOSM() to convert them to GeoPackage and style."""
        self.iface.messageBar().pushWarning(
            'Not implemented', 'Downloading OSM data is yet to be implemented.')

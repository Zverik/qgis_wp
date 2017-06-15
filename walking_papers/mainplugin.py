from PyQt4.QtCore import QVariant
from PyQt4.QtGui import QMenu, QAction, QIcon, QColor
from qgis.core import (
    QgsField,
    QgsMapLayerRegistry,
    QgsVectorLayer,
    QgsFillSymbolV2,
    QgsPalLayerSettings,
    QgsMessageLog,
)
from processing import runalg


PIE_LAYER = 'pie'
ROTATION_FIELD = 'rotation'
NAME_FIELD = 'name'


class WalkingPapersPlugin:
    def __init__(self, iface):
        self.iface = iface

    def initGui(self):
        self.menu = QMenu(self.iface.mainWindow())
        self.menu.setObjectName("wpMenu")
        self.menu.setTitle("Walking Papers")

        styleAction = QAction(QIcon(":/plugins/testplug/icon.png"), "Style OSM Data", self.iface.mainWindow())
        styleAction.setObjectName("styleOSM")
        styleAction.setStatusTip('Takes "lines" and "multipolygon" layers and prepares a Walking Papers style')
        styleAction.triggered.connect(self.styleOSM)
        self.menu.addAction(styleAction)

        prepareAction = QAction(QIcon(":/plugins/testplug/icon.png"), "Create Pie Layer and Prepare Atlas", self.iface.mainWindow())
        prepareAction.setObjectName("makePie")
        prepareAction.setStatusTip('Creates a "{}" layer and prepares an atlas in map composer to use it'.format(PIE_LAYER))
        prepareAction.triggered.connect(self.preparePie)
        self.menu.addAction(prepareAction)

        rotateAction = QAction(QIcon(":/plugins/testplug/icon.png"), "Calculate Pie Rotation", self.iface.mainWindow())
        rotateAction.setObjectName("calcRotation")
        rotateAction.setStatusTip('Adds or updates a "{}" column with degrees. Requires a "{}" layer.'.format(ROTATION_FIELD, PIE_LAYER))
        rotateAction.triggered.connect(self.calcRotation)
        self.menu.addAction(rotateAction)

        self.iface.pluginMenu().addMenu(self.menu)

    def unload(self):
        self.menu.deleteLater()

    def calcRotation(self):
        pies = QgsMapLayerRegistry.instance().mapLayersByName(PIE_LAYER)
        if not pies:
            self.iface.messageBar().pushCritical('No layer', 'Please add "{}" layer.'.format(PIE_LAYER))
            return
        pie = pies[0]
        if not pie.featureCount():
            self.iface.messageBar().pushInfo('No data', 'No features in the "{}" layer.'.format(PIE_LAYER))
            return

        rotIndex = pie.dataProvider().fieldNameIndex(ROTATION_FIELD)
        if rotIndex < 0:
            if not self.addFieldToLayer(pie, ROTATION_FIELD, QVariant.Int):
                return
            rotIndex = pie.dataProvider().fieldNameIndex(ROTATION_FIELD)

        boxes = runalg('qgis:orientedminimumboundingbox', pie, True, None)
        boxesLayer = QgsVectorLayer(boxes['OUTPUT'], 'boxes_tmp', 'ogr')
        if not boxesLayer.isValid():
            self.iface.messageBar().pushCritical('Access error', 'Failed to load a temporary processing layer.')
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
        self.iface.messageBar().pushWarning('Not implemented', 'Creating atlas is yet to be implemented.')

    def styleOSM(self):
        QgsMessageLog.logMessage("message", "name")
        self.iface.messageBar().pushWarning('Not implemented', 'Styling OSM data is yet to be implemented.')

    def addFieldToLayer(self, layer, name, typ):
        if layer.dataProvider().fieldNameIndex(name) < 0:
            layer.dataProvider().addAttributes([QgsField(name, typ)])
            layer.updateFields()
            if layer.dataProvider().fieldNameIndex(name) < 0:
                self.iface.messageBar().pushCritical('Access error', 'Failed to add a "{}" field to the "{}" layer.'.format(name, layer.layerName()))
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

    def preparePie(self):
        self.createPie()
        self.createAtlas()

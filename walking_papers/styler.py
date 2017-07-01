# QGIS Layer Styling Module
# Copyright (C) 2017 Ilya Zverev
# This code is licensed GPL v3, see the LICENSE file for details.
# And it comes WITHOUT ANY WARRANTY obviously.

from PyQt4.QtGui import QColor, QFont
from qgis.core import (
    QgsMapLayerRegistry,
    QgsVectorLayer,
    QgsMarkerSymbolV2,
    QgsLineSymbolV2,
    QgsFillSymbolV2,
    QgsPalLayerSettings,
)


def applyLayerStyle(layer, style):
    if not layer.rendererV2():
        return

    def format_value(v):
        if v is True:
            return 'yes'
        if v is False:
            return 'no'
        return str(v)

    if 'fill' in style:
        props = {k.replace('-', '_'): format_value(v) for k, v in style['fill'].iteritems()}
        symbol = QgsFillSymbolV2.createSimple(props)
        layer.rendererV2().setSymbol(symbol)
    if 'line' in style:
        props = {k.replace('-', '_'): format_value(v) for k, v in style['line'].iteritems()}
        symbol = QgsLineSymbolV2.createSimple(props)
        layer.rendererV2().setSymbol(symbol)
    if 'marker' in style:
        props = {k.replace('-', '_'): format_value(v) for k, v in style['marker'].iteritems()}
        symbol = QgsMarkerSymbolV2.createSimple(props)
        layer.rendererV2().setSymbol(symbol)
    if 'label' in style:
        l = style['label']
        label = QgsPalLayerSettings()
        label.readFromLayer(layer)
        label.enabled = l.get('enabled', True)
        label.drawLabels = l.get('enabled', True)
        if 'field' in l:
            label.fieldName = l['field']
            label.isExpression = False
        if 'expression' in l:
            label.fieldName = l['expression']
            label.isExpression = True
        if 'font-family' in l:
            label.textFont.setFamily(l['font-family'])
        if 'font-size' in l:
            label.textFont.setPointSizeF(float(l['font-size']))
        weights = {
            'light': QFont.Light,
            'normal': QFont.Normal,
            'bold': QFont.Bold,
            'demibold': QFont.DemiBold,
            'black': QFont.Black,
        }
        if l.get('font-weight', None) in weights:
            label.textFont.setWeight(weights[l['font-weight']])
        label.textFont.setItalic(l.get('font-style', None) == 'italic')
        label.textFont.setUnderline(l.get('text-decoration', None) == 'underline')
        aligns = {
            'left': QgsPalLayerSettings.MultiLeft,
            'center': QgsPalLayerSettings.MultiCenter,
            'right': QgsPalLayerSettings.MultiRight,
            'follow': QgsPalLayerSettings.MultiFollowPlacement,
        }
        if l.get('text-align', None) in aligns:
            label.multilineAlign = aligns[l['text-align']]
        if 'line-height' in l:
            label.multilineHeight = float(l['line-height'])
        if 'color' in l:
            label.textColor = QColor(l['color'])
        if 'buffer-color' in l:
            label.bufferDraw = True
            label.bufferColor = QColor(l['buffer-color'])
        if 'buffer-size' in l:
            label.bufferDraw = True
            label.bufferSize = float(l['buffer-size'])
        if 'buffer-opacity' in l:
            label.bufferTransp = 100 - int(100 * float(l['buffer-opacity']))
        # Fix for lines
        if label.enabled and 'line' in style:
            label.placement = QgsPalLayerSettings.Line
            label.placementFlags = QgsPalLayerSettings.AboveLine
        label.writeToLayer(layer)


def applyStyle(filename, style):
    registry = QgsMapLayerRegistry.instance()
    for layer in reversed(style):
        params = {}
        params['layername'] = layer.get('layer', None)
        params['subset'] = layer.get('query', None)
        uri = filename + ''.join(['|{}={}'.format(k, v) for k, v in params.iteritems() if v])
        name = layer.get('name', params['layername'])
        vector = QgsVectorLayer(uri, name, 'ogr')
        if vector.featureCount():
            registry.addMapLayer(vector)
            if 'style' in layer:
                applyLayerStyle(vector, layer['style'])

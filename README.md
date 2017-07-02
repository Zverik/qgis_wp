# Walking Papers QGIS Plugin

2. Open QGIS and install this plugin.
3. In menu "Plugins" -> "Walking Papers" click "Download OSM Data", select an area and click the same option again.
4. Draw pie pieces.
5. In the same menu click "Calculate Pie Rotation".
6. Click "Prepare Atlas" and export it to PDF.

## Installation

Install the plugin from the QGIS Plugin Repository. Alternatively, clone this repository and do

    ln -s "$(pwd)/walking_papers" ~/.qgis2/python/plugins/walking_papers

Note that in order to use translations you would need to run `lrelease` on needed `*.ts` files.

## Author and License

Written by Ilya Zverev, published under GPL v3 license.

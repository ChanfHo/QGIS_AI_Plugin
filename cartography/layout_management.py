from ..core.localization import t
from ..core.error_handling import failure, execution_boundary, ToolResult
from ..ui.ui_theme import DIALOG_STYLE
import os
from typing import Dict, Any
from qgis.utils import iface
from qgis.core import (
    QgsProject,
    QgsPrintLayout,
    QgsLayoutItemMap,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutItemLabel,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsUnitTypes,
    QgsLayoutItemPage,
    QgsLayoutExporter,
    QgsLayoutItemPicture,
    QgsApplication,
    QgsMapLayerLegendUtils,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QHBoxLayout,
)

class LegendSelectionDialog(QDialog):
    def __init__(self, legend_model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('Select legend items to display'))
        self.setStyleSheet(DIALOG_STYLE)
        self.resize(400, 500)
        self.legend_model = legend_model
        
        layout = QVBoxLayout(self)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)
        
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(t('OK'))
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)
        
        self._populate_tree()
        self.tree.itemChanged.connect(self.on_item_changed)

    def _populate_tree(self):
        root_group = self.legend_model.rootGroup()
        for layer_node in root_group.findLayers():
            layer = layer_node.layer()
            if not layer:
                continue
                
            layer_item = QTreeWidgetItem(self.tree)
            layer_item.setText(0, layer.name())
            layer_item.setFlags(layer_item.flags() | Qt.ItemIsUserCheckable)
            layer_item.setCheckState(0, Qt.Checked)
            layer_item.setData(0, Qt.UserRole, layer_node)
            
            legend_nodes = self.legend_model.layerLegendNodes(layer_node)
            for i, node in enumerate(legend_nodes):
                node_item = QTreeWidgetItem(layer_item)
                val = node.data(Qt.DisplayRole)
                text = str(val.value()) if hasattr(val, 'value') else str(val)
                node_item.setText(0, text)
                node_item.setFlags(node_item.flags() | Qt.ItemIsUserCheckable)
                node_item.setCheckState(0, Qt.Checked)
                node_item.setData(0, Qt.UserRole, i)
                
        self.tree.expandAll()

    def on_item_changed(self, item, column):
        self.tree.blockSignals(True)
        if item.parent() is None:
            state = item.checkState(0)
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, state)
        else:
            parent = item.parent()
            any_checked = False
            for i in range(parent.childCount()):
                if parent.child(i).checkState(0) == Qt.Checked:
                    any_checked = True
                    break
            parent.setCheckState(0, Qt.Checked if any_checked else Qt.Unchecked)
        self.tree.blockSignals(False)

    def get_selections(self):
        removed_layers = []
        layer_visibility = {}
        
        for i in range(self.tree.topLevelItemCount()):
            layer_item = self.tree.topLevelItem(i)
            layer_node_data = layer_item.data(0, Qt.UserRole)
            layer_node = layer_node_data.value() if hasattr(layer_node_data, 'value') else layer_node_data
            
            if layer_item.checkState(0) == Qt.Unchecked:
                removed_layers.append(layer_node)
            else:
                visible_indices = []
                for j in range(layer_item.childCount()):
                    node_item = layer_item.child(j)
                    if node_item.checkState(0) == Qt.Checked:
                        idx = node_item.data(0, Qt.UserRole)
                        idx_val = int(idx.value()) if hasattr(idx, 'value') else int(idx)
                        visible_indices.append(idx_val)
                
                if len(visible_indices) < layer_item.childCount():
                    layer_visibility[layer_node] = visible_indices
                    
        return removed_layers, layer_visibility


def get_target_layout(project: QgsProject, layout_name: str = None) -> QgsPrintLayout:
    """Get the target layout, or the active/last layout when unspecified."""
    if layout_name and layout_name != "AI自动布局":
        layout = project.layoutManager().layoutByName(layout_name)
        if layout:
            return layout
    
    # Get project layouts and prefer the last, usually newest, layout.
    layouts = project.layoutManager().printLayouts()
    if layouts:
        return layouts[-1]
        
    # Fallback: try the currently active layout.
    try:
        active_layouts = iface.openLayoutDesigners()
        if active_layouts:
            return active_layouts[0].layout()
    except Exception:
        pass
        
    return None

@execution_boundary("agent_d", "LAYOUT_FAILED")
def execute_layout_task(params: Dict[str, Any]) -> ToolResult:
    """Agent E's operation execution unit."""
    action_type = params.get("action_type")
    canvas = iface.mapCanvas()
    project = QgsProject.instance()

    try:
        # View control.
        if action_type == "zoom_layer":
            layer_name = params.get("layer_name")
            layers = project.mapLayersByName(layer_name)
            if not layers: return failure("LAYER_NOT_FOUND", "agent_d", t("Error: Layer '{v0}' does not exist", v0=layer_name))
            canvas.setExtent(layers[0].extent())
            canvas.refresh()
            return t("Zoomed to layer '{v0}'", v0=layer_name)

        elif action_type == "zoom_full":
            canvas.zoomToFullExtent()
            canvas.refresh()
            return t('Full extent displayed')

        # Create the base layout.
        elif action_type == "create_print_layout":
            title = params.get("title", "AI自动布局")
            page_size_str = params.get("page_size", "A4").upper()
            orientation_str = params.get("orientation", "landscape")
            layout_manager = project.layoutManager()

            existing_layout = layout_manager.layoutByName(title)
            if existing_layout:
                layout_manager.removeLayout(existing_layout)

            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            layout.setName(title)
            layout_manager.addLayout(layout)

            # Set the page according to paper size.
            valid_sizes = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594)}
            if page_size_str not in valid_sizes:
                page_size_str = "A4"
            page_width, page_height = valid_sizes[page_size_str]

            if orientation_str in ("portrait", "竖向"):
                page_width, page_height = page_height, page_width
                page_orientation = QgsLayoutItemPage.Orientation.Portrait
            else:
                page_orientation = QgsLayoutItemPage.Orientation.Landscape

            pc = layout.pageCollection()
            page = pc.page(0)
            page.setPageSize(page_size_str, page_orientation)

            # Title.
            title_item = QgsLayoutItemLabel(layout)
            title_item.setText(title)
            title_font = QFont("SimHei", 28, QFont.Bold)
            title_item.setFont(title_font)
            title_item.setHAlign(Qt.AlignHCenter)
            title_item.setVAlign(Qt.AlignVCenter)
            title_item.attemptMove(QgsLayoutPoint(0, 5, QgsUnitTypes.LayoutMillimeters))
            title_item.attemptResize(QgsLayoutSize(page_width, 15, QgsUnitTypes.LayoutMillimeters))
            layout.addLayoutItem(title_item)

            # Map margins: top 25, bottom 10, left/right 10 each.
            map_item = QgsLayoutItemMap(layout)
            map_width = page_width - 20
            map_height = page_height - 35
            map_item.attemptMove(QgsLayoutPoint(10, 25, QgsUnitTypes.LayoutMillimeters))
            map_item.attemptResize(QgsLayoutSize(map_width, map_height, QgsUnitTypes.LayoutMillimeters))
            
            # Zoom to the layer extent and enlarge the map slightly to fill the frame.
            map_item.zoomToExtent(canvas.extent())
            current_scale = map_item.scale()
            map_item.setScale(current_scale)
            
            map_item.setFrameEnabled(True)
            layout.addLayoutItem(map_item)

            iface.openLayoutDesigner(layout)
            return t("Created base layout '{v0}' (page: {v1})", v0=title, v1=page_size_str)

        # Add components and export.
        elif action_type in ["add_legend", "add_scale_bar", "add_north_arrow", "add_map", "export_layout_png", "set_title"]:
            requested_name = params.get("layout_name")
            layout = (project.layoutManager().layoutByName(requested_name) if requested_name
                      else get_target_layout(project))
            if not layout: 
                return failure("LAYOUT_NOT_FOUND", "agent_d", t('Error: No available layout was found.'))
            layout_name = layout.name()

            # Set the title.
            if action_type == "set_title":
                new_title = params.get("title", t('Unnamed layout'))
                layout.setName(new_title)
                
                # Find and update the existing title item.
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemLabel):
                        # Assume the only/first label in this layout is its title.
                        item.setText(new_title)
                        return t("Layout title set to '{v0}'", v0=new_title)
                
                # Create one if none was found.
                page = layout.pageCollection().page(0)
                page_width = page.pageSize().width()
                title_item = QgsLayoutItemLabel(layout)
                title_item.setText(new_title)
                title_font = QFont("SimHei", 28, QFont.Bold)
                title_item.setFont(title_font)
                title_item.setHAlign(Qt.AlignHCenter)
                title_item.setVAlign(Qt.AlignVCenter)
                title_item.attemptMove(QgsLayoutPoint(0, 5, QgsUnitTypes.LayoutMillimeters))
                title_item.attemptResize(QgsLayoutSize(page_width, 15, QgsUnitTypes.LayoutMillimeters))
                layout.addLayoutItem(title_item)
                return t("Layout title set to '{v0}'", v0=new_title)

            # Export PNG.
            if action_type == "export_layout_png":
                # Show the save dialog; this is safe on the main thread.
                # Arguments: parent, title, default filename, file filter.
                file_path, _ = QFileDialog.getSaveFileName(
                    None,
                    t('Export layout as PNG'),
                    f"{layout_name}.png",
                    "PNG Files (*.png)"
                )

                if file_path:
                    exporter = QgsLayoutExporter(layout)
                    settings = QgsLayoutExporter.ImageExportSettings()
                    # Export.
                    result = exporter.exportToImage(file_path, settings)

                    if result == QgsLayoutExporter.Success:
                        return t('Successfully exported PNG to: {v0}', v0=file_path)
                    else:
                        code = "EXPORT_PATH_INVALID" if result == QgsLayoutExporter.FileError else "EXPORT_FAILED"
                        return failure(code, "agent_d", t('Export error code {v0}', v0=result), parameters={"file_path": file_path})
                else:
                    return failure("USER_CANCELLED", "agent_d", t('Operation cancelled (no save path selected)'))

            map_item = None
            for item in layout.items():
                if isinstance(item, QgsLayoutItemMap):
                    map_item = item
                    break

            if action_type == "add_map":
                if map_item: return t("Layout '{v0}' already has a map; skipped.", v0=layout_name)
                
                # Get page dimensions to calculate map size.
                page = layout.pageCollection().page(0)
                page_width = page.pageSize().width()
                page_height = page.pageSize().height()
                map_width = page_width - 20
                map_height = page_height - 35
                
                map_item = QgsLayoutItemMap(layout)
                map_item.attemptMove(QgsLayoutPoint(10, 25, QgsUnitTypes.LayoutMillimeters))
                map_item.attemptResize(QgsLayoutSize(map_width, map_height, QgsUnitTypes.LayoutMillimeters))
                map_item.zoomToExtent(canvas.extent())
                layout.addLayoutItem(map_item)
                return t("Added a map to '{v0}'", v0=layout_name)

            if not map_item and action_type in ("add_legend", "add_scale_bar", "add_north_arrow"):
                return failure("LAYOUT_ITEM_NOT_FOUND", "agent_d", t('The target layout has no map item'))

            elif action_type == "add_legend":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemLegend): return t('Duplicate legend skipped.')
                legend = QgsLayoutItemLegend(layout)
                if map_item: legend.setLinkedMap(map_item)
                legend.setTitle(t('Legend'))
                
                # Default to True to get all layers.
                legend.setAutoUpdateModel(True)
                
                # Disable automatic updates to allow custom filtering.
                legend.setAutoUpdateModel(False)
                
                # Show a selection dialog to filter unwanted legend items.
                dialog = LegendSelectionDialog(legend.model(), iface.mainWindow())
                if dialog.exec_() == QDialog.Accepted:
                    removed_layers, layer_visibility = dialog.get_selections()
                    
                    root_group = legend.model().rootGroup()
                    # Remove unselected layers.
                    for node in removed_layers:
                        root_group.removeChildNode(node)
                        
                    # Set visibility of categorized/graduated items inside layers.
                    for node, visible_indices in layer_visibility.items():
                        QgsMapLayerLegendUtils.setLegendNodeOrder(node, visible_indices)
                        legend.model().refreshLayerLegend(node)
                else:
                    return failure("USER_CANCELLED", "agent_d", t('Adding the legend was cancelled'))
                
                layout.addLayoutItem(legend)
                
                # Force recalculation to get the correct width and height.
                legend.adjustBoxSize()
                
                # Anchor inside the map's lower-right corner.
                if map_item:
                    # Use the map item's position and size.
                    map_pos = map_item.positionWithUnits()
                    map_size = map_item.sizeWithUnits()
                    
                    # Use LowerRight (8) so the legend's lower-right corner cannot exceed the given position.
                    legend.setReferencePoint(8)
                    
                    # Place the lower-right corner 5 mm inside the map's lower-right corner.
                    legend_x = map_pos.x() + map_size.width() - 5
                    legend_y = map_pos.y() + map_size.height() - 5
                    
                    legend.attemptMove(QgsLayoutPoint(legend_x, legend_y, QgsUnitTypes.LayoutMillimeters))
                return t('Legend added')

            elif action_type == "add_scale_bar":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemScaleBar): 
                        return t('Duplicate scale bar skipped.')
                        
                scalebar = QgsLayoutItemScaleBar(layout)
                scalebar.setStyle('Single Box')
                if map_item: scalebar.setLinkedMap(map_item)
                
                # Set units and text.
                scalebar.setUnits(QgsUnitTypes.DistanceKilometers)
                scalebar.setUnitLabel("km")
                
                # Configure segments.
                scalebar.setNumberOfSegments(3)
                scalebar.setNumberOfSegmentsLeft(0)
                
                # Use FitWidth (1) segment sizing to adapt dynamically to the map scale.
                try:
                    scalebar.setSegmentSizeMode(1)
                    scalebar.setMinimumBarWidth(15)
                    scalebar.setMaximumBarWidth(50)
                except Exception:
                    pass
                
                # Adjust alignment to show units to the right of the scale bar.
                try:
                    scalebar.setAlignment(2) # 2 = AlignRight
                except Exception:
                    pass
                
                # Apply the default calculation if the preceding configuration did not fully take effect.
                scalebar.applyDefaultSize() 
                
                # Try adjusting text format in a QGIS 3-compatible way.
                try:
                    from qgis.core import QgsTextFormat
                    text_format = QgsTextFormat()
                    text_format.setFont(QFont("Arial", 12))
                    scalebar.setTextFormat(text_format)
                except Exception:
                    pass # Ignore font configuration errors.
                    
                scalebar.update()
                
                layout.addLayoutItem(scalebar)
                
                # Anchor inside the map's lower-left corner.
                if map_item:
                    map_pos = map_item.positionWithUnits()
                    map_size = map_item.sizeWithUnits()
                    
                    # Use LowerLeft (6) to keep the lower-left corner fixed during dynamic resizing.
                    scalebar.setReferencePoint(6)
                    
                    scalebar_x = map_pos.x() + 5
                    scalebar_y = map_pos.y() + map_size.height() - 5
                    
                    scalebar.attemptMove(QgsLayoutPoint(scalebar_x, scalebar_y, QgsUnitTypes.LayoutMillimeters))
                
                return t('Dynamic scale bar added')

            elif action_type == "add_north_arrow":
                # Add the actual north arrow image.
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemPicture): return t('Duplicate north arrow skipped.')
                
                arrow = QgsLayoutItemPicture(layout)
                arrow.setMode(QgsLayoutItemPicture.FormatSVG)
                
                # Try resolving the SVG path.
                svg_paths = QgsApplication.svgPaths()
                svg_path = ""
                if svg_paths:
                    # Search common directories first.
                    for base_path in svg_paths:
                        test_path = os.path.join(base_path, "arrows", "NorthArrow_10.svg")
                        if os.path.exists(test_path):
                            svg_path = test_path
                            break
                    
                    if not svg_path:
                        # Fallback: select any available item.
                        test_path = os.path.join(svg_paths[0], "arrows", "NorthArrow_10.svg")
                        svg_path = test_path
                
                if svg_path:
                    arrow.setPicturePath(svg_path)
                layout.addLayoutItem(arrow)
                
                # Set north arrow size.
                arrow.attemptResize(QgsLayoutSize(15, 15, QgsUnitTypes.LayoutMillimeters))
                
                # Anchor inside the map's upper-right corner.
                if map_item:
                    map_pos = map_item.positionWithUnits()
                    map_size = map_item.sizeWithUnits()
                    arrow_size = arrow.sizeWithUnits()
                    
                    arrow_x = map_pos.x() + map_size.width() - arrow_size.width() - 5
                    arrow_y = map_pos.y() + 5
                    
                    arrow.attemptMove(QgsLayoutPoint(arrow_x, arrow_y, QgsUnitTypes.LayoutMillimeters))
                return t('North arrow added')

        return failure("INVALID_PARAMETER", "agent_d", t('Error: Unknown operation {v0}', v0=action_type))

    except Exception as e:
        err_msg = str(e)
        return failure("LAYOUT_FAILED", "agent_d", f"Error: {err_msg}")

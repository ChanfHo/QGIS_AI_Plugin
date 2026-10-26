from ..core.error_handling import failure, execution_boundary, ToolResult
import random
from typing import Dict, Any
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import Qt
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsSymbol,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRendererCategory,
    QgsRendererRange,
    QgsStyle,
    QgsGradientColorRamp,
    QgsClassificationQuantile,
    QgsClassificationJenks,
    QgsClassificationEqualInterval,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
    QgsPalettedRasterRenderer,
    QgsHillshadeRenderer,
    QgsRasterShader,
    QgsColorRampShader,
    QgsRasterBandStats,
    QgsContrastEnhancement,
)

# Style mapping constants.
PEN_STYLES = {
    "solid": Qt.SolidLine,
    "dash": Qt.DashLine,
    "dot": Qt.DotLine,
    "dash dot": Qt.DashDotLine,
    "dash dot dot": Qt.DashDotDotLine,
    "dash dash dot": Qt.CustomDashLine,
    "no": Qt.NoPen
}

BRUSH_STYLES = {
    "solid": Qt.SolidPattern,
    "no": Qt.NoBrush,
    "cross": Qt.CrossPattern,
    "dense1": Qt.Dense1Pattern
}

JOIN_STYLES = {
    "bevel": Qt.BevelJoin,
    "miter": Qt.MiterJoin,
    "round": Qt.RoundJoin
}

CAP_STYLES = {
    "square": Qt.SquareCap,
    "flat": Qt.FlatCap,
    "round": Qt.RoundCap
}

LABEL_PLACEMENT_MAP = {
    "around_point": QgsPalLayerSettings.AroundPoint,
    "over_point": QgsPalLayerSettings.OverPoint,
    "over_line": QgsPalLayerSettings.Line,
    "curved": QgsPalLayerSettings.Curved,
    "horizontal": QgsPalLayerSettings.Horizontal,
    "free": QgsPalLayerSettings.Free,
    "cartographic": QgsPalLayerSettings.OrderedPositionsAroundPoint
}

EDIT_STRENGTH_MAP = {
    "slight": {
        "scale_up": 1.15,
        "scale_down": 0.85,
        "color_factor": 0.04,
        "alpha_delta": 30
    },
    "medium": {
        "scale_up": 1.3,
        "scale_down": 0.7,
        "color_factor": 0.08,
        "alpha_delta": 80
    },
    "strong": {
        "scale_up": 1.6,
        "scale_down": 0.5,
        "color_factor": 0.12,
        "alpha_delta": 130
    }
}


# Color parsing helper.
def parse_color(color_str: str, default: str = "#000000") -> QColor:
    """Parse a color string, returning the default on failure."""
    if not color_str:
        return QColor(default)
    try:
        c = QColor(color_str)
        return c if c.isValid() else QColor(default)
    except:
        return QColor(default)


# Symbol configuration helper.
def configure_symbol_layer(symbol: QgsSymbol, params: Dict[str, Any]):
    """
    Configure symbol properties from symbol_layer_params,
    corresponding to that section of the schema.
    """
    if not symbol:
        return

    # 1. Set top-level size, width and angle according to geometry type.
    # Marker symbols support setSize and setAngle.
    if isinstance(symbol, QgsMarkerSymbol):
        if "size" in params:
            symbol.setSize(float(params["size"]))
        if "angle" in params:
            symbol.setAngle(float(params["angle"]))

    # Line symbols support setWidth, not setSize or setAngle.
    elif isinstance(symbol, QgsLineSymbol):
        if "line_width" in params:
            symbol.setWidth(float(params["line_width"]))

    # Fill symbols have no top-level size/width and do not support setSize.
    elif isinstance(symbol, QgsFillSymbol):
        pass

    # 2. Configure symbol-layer color, style and stroke properties.
    if symbol.symbolLayerCount() > 0:
        sl = symbol.symbolLayer(0)

        # A. Point marker: SimpleMarker.
        if isinstance(symbol, QgsMarkerSymbol):
            # Shape.
            if params.get("marker_type") == "simple" and "name" in params:
                # Use a temporary symbol to obtain the shape enum.
                temp_sym = QgsMarkerSymbol.createSimple({'name': params['name']})
                if temp_sym and temp_sym.symbolLayerCount() > 0:
                    sl.setShape(temp_sym.symbolLayer(0).shape())

            # SimpleMarker fill color.
            if "fill_color" in params:
                sl.setColor(parse_color(params["fill_color"]))

            # SimpleMarker stroke / outline.
            if "outline_color" in params:
                sl.setStrokeColor(parse_color(params["outline_color"]))
            if "outline_width" in params:
                sl.setStrokeWidth(float(params["outline_width"]))
            if "outline_style" in params:
                o_style = params["outline_style"]
                sl.setStrokeStyle(PEN_STYLES.get(o_style, Qt.SolidLine))

        # B. Line: SimpleLine.
        elif isinstance(symbol, QgsLineSymbol):
            # Line color.
            if "line_color" in params:
                sl.setColor(parse_color(params["line_color"]))
            # Line width usually follows top-level settings, but setting it explicitly is safer.
            if "line_width" in params:
                sl.setWidth(float(params["line_width"]))

            # Line style.
            if "pen_style" in params:
                p_style = params["pen_style"]
                sl.setPenStyle(PEN_STYLES.get(p_style, Qt.SolidLine))
                if p_style == "dash dash dot" and hasattr(sl, "setCustomDashVector"):
                    if hasattr(sl, "setUseCustomDashPattern"):
                        sl.setUseCustomDashPattern(True)
                    sl.setCustomDashVector([6.0, 2.0, 6.0, 2.0, 1.0, 2.0])
                elif hasattr(sl, "setUseCustomDashPattern"):
                    sl.setUseCustomDashPattern(False)

            if "cap_style" in params:
                sl.setPenCapStyle(CAP_STYLES.get(params["cap_style"], Qt.SquareCap))
            if "join_style" in params:
                sl.setPenJoinStyle(JOIN_STYLES.get(params["join_style"], Qt.BevelJoin))

        # C. Polygon fill: SimpleFill.
        elif isinstance(symbol, QgsFillSymbol):
            # Fill color.
            if "fill_color" in params:
                sl.setColor(parse_color(params["fill_color"]))
            # Fill style (Solid, Cross, etc.).
            if "fill_style" in params:
                sl.setBrushStyle(BRUSH_STYLES.get(params["fill_style"], Qt.SolidPattern))

            # Fill-layer outline stroke.
            if "outline_color" in params:
                sl.setStrokeColor(parse_color(params["outline_color"]))
            if "outline_width" in params:
                sl.setStrokeWidth(float(params["outline_width"]))
            if "outline_style" in params:
                o_style = params["outline_style"]
                sl.setStrokeStyle(PEN_STYLES.get(o_style, Qt.SolidLine))
                if o_style == "dash dash dot" and hasattr(sl, "setCustomDashVector"):
                    if hasattr(sl, "setUseCustomDashPattern"):
                        sl.setUseCustomDashPattern(True)
                    sl.setCustomDashVector([6.0, 2.0, 6.0, 2.0, 1.0, 2.0])
                elif hasattr(sl, "setUseCustomDashPattern"):
                    sl.setUseCustomDashPattern(False)


# Fuzzy style modification helper.
def modify_symbol_by_edit_config(symbol: QgsSymbol, edit_config: Dict[str, Any]):
    """
    Modify an existing symbol using edit_style_config,
    combining edit_intent, edit_scope and edit_strength.
    """
    if not symbol or not edit_config:
        return

    intent = edit_config.get("edit_intent", "")
    scopes = edit_config.get("edit_scope", [])
    strength = edit_config.get("edit_strength", "medium")

    strength_cfg = EDIT_STRENGTH_MAP.get(strength, EDIT_STRENGTH_MAP["medium"])

    scale_up = strength_cfg["scale_up"]
    scale_down = strength_cfg["scale_down"]
    color_factor = strength_cfg["color_factor"]
    alpha_delta = strength_cfg["alpha_delta"]

    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)

        # Color settings.
        def adjust_color(color: QColor) -> QColor:
            if not color.isValid():
                return color

            # Extract HSL color components.
            h, s, l, a = color.getHsl()
            s /= 255.0
            l /= 255.0

            # Color adjustment logic.
            if intent == "lighter":
                l = min(1.0, l + color_factor)
            elif intent == "darker":
                l = max(0.0, l - color_factor)
            elif intent == "more_transparent":
                a = max(0, a - alpha_delta)
            elif intent == "less_transparent":
                a = min(255, a + alpha_delta)
            elif intent == "more_prominent":
                s = min(1.0, s + color_factor)
                l = l + (0.5 - l) * color_factor
            elif intent == "less_prominent":
                s = max(0.0, s - color_factor)
                l = l + (0.5 - l) * color_factor

            new_color = QColor(color)
            new_color.setHsl(h, int(s * 255), int(l * 255), int(a))
            return new_color

        # fill_color
        if "fill_color" in scopes and hasattr(sl, "color") and hasattr(sl, "setColor"):
            try:
                sl.setColor(adjust_color(sl.color()))
            except:
                pass

        # outline_color
        if "outline_color" in scopes and hasattr(sl, "strokeColor") and hasattr(sl, "setStrokeColor"):
            try:
                sl.setStrokeColor(adjust_color(sl.strokeColor()))
            except:
                pass

        # line_color
        if "line_color" in scopes and hasattr(sl, "color") and hasattr(sl, "setColor"):
            try:
                sl.setColor(adjust_color(sl.color()))
            except:
                pass

        # Size / line width.
        def scale_value(v: float) -> float:
            if intent in ["larger", "thicker", "more_prominent"]:
                return v * scale_up
            elif intent in ["smaller", "thinner", "less_prominent"]:
                return v * scale_down
            return v

        # Point size.
        if "size" in scopes and isinstance(symbol, QgsMarkerSymbol):
            if hasattr(sl, "size") and hasattr(sl, "setSize"):
                sl.setSize(scale_value(sl.size()))

        # Line width.
        if "line_width" in scopes and hasattr(sl, "width") and hasattr(sl, "setWidth"):
            sl.setWidth(scale_value(sl.width()))

        # Polygon / point outline width.
        if "outline_width" in scopes and hasattr(sl, "strokeWidth") and hasattr(sl, "setStrokeWidth"):
            sl.setStrokeWidth(scale_value(sl.strokeWidth()))


# Base symbol factory.
def create_base_symbol(geometry_type: int, params: Dict[str, Any]) -> QgsSymbol:
    """Create a base symbol and apply initial parameters."""
    symbol = None
    if geometry_type == 0:  # Point
        symbol = QgsMarkerSymbol.createSimple({})
    elif geometry_type == 1:  # Line
        symbol = QgsLineSymbol.createSimple({})
    elif geometry_type == 2:  # Polygon
        symbol = QgsFillSymbol.createSimple({})

    if symbol:
        configure_symbol_layer(symbol, params)
        
        additional_layers = params.get("additional_layers", [])
        for add_params in additional_layers:
            add_sym = None
            if geometry_type == 0:
                add_sym = QgsMarkerSymbol.createSimple({})
            elif geometry_type == 1:
                add_sym = QgsLineSymbol.createSimple({})
            elif geometry_type == 2:
                add_sym = QgsFillSymbol.createSimple({})
                
            if add_sym:
                configure_symbol_layer(add_sym, add_params)
                if add_sym.symbolLayerCount() > 0:
                    symbol.appendSymbolLayer(add_sym.symbolLayer(0).clone())

    return symbol


# Label configuration helper.
def apply_annotation_style(layer: QgsVectorLayer, field_name: str, config: Dict[str, Any]) -> ToolResult:
    """
    Apply label styling.
    :param config: The schema's annotation_config section.

    """
    target_field = field_name
    if not target_field:
        return failure("FIELD_NOT_FOUND", "agent_c", "Error: No valid field found for annotation.")

    # Configure font format (QgsTextFormat).
    text_format = QgsTextFormat()
    font = QFont(config.get("font_family", "Microsoft YaHei"))  # Font family.
    font.setBold(config.get("is_bold", False))  # Bold.
    font.setItalic(config.get("is_italic", False))  # Italic.
    text_format.setFont(font)
    text_format.setSize(float(config.get("font_size", 10.0)))  # Font size (usually points in the schema).
    text_format.setColor(parse_color(config.get("font_color", "#000000")))  # Color.

    # Configure the outline / buffer.
    if config.get("draw_buffer", True):
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(float(config.get("buffer_size", 1.0)))
        buffer_settings.setColor(parse_color(config.get("buffer_color", "#FFFFFF")))
        text_format.setBuffer(buffer_settings)

    # Configure placement settings (QgsPalLayerSettings).
    settings = QgsPalLayerSettings()
    settings.setFormat(text_format)
    settings.fieldName = target_field

    mode_str = config.get("mode", "free").lower()

    # Map placement modes.
    if mode_str in LABEL_PLACEMENT_MAP:
        settings.placement = LABEL_PLACEMENT_MAP[mode_str]
    else:
        # Default fallback logic.
        geom_type = layer.geometryType()
        if geom_type == 0:  # Point
            settings.placement = QgsPalLayerSettings.OrderedPositionsAroundPoint
        elif geom_type == 1:  # Line
            settings.placement = QgsPalLayerSettings.Curved
        else:  # Polygon
            settings.placement = QgsPalLayerSettings.Horizontal

    # Handle offsets (offset_xy).
    offset = config.get("offset_xy", [0.0, 0.0])
    if isinstance(offset, list) and len(offset) >= 2:
        # xOffset/yOffset control offsets in most modes.
        settings.xOffset = float(offset[0])
        settings.yOffset = float(offset[1])
        # Around-point mode may use dist; handling is simplified here.

    # Apply settings.
    labeling = QgsVectorLayerSimpleLabeling(settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()

    return f"Success: Annotation added on field '{target_field}'."


# Raster rendering helper.
def apply_raster_style(layer: QgsRasterLayer, config: Dict[str, Any]) -> ToolResult:
    """Apply raster styling to a QgsRasterLayer using the schema's raster_config section."""
    raster_type = config.get("raster_type", "pseudocolor")
    if raster_type == "single_band_pseudocolor":
        raster_type = "pseudocolor"
    band_no = config.get("band_no", 1)
    if raster_type not in ("gray", "hillshade", "pseudocolor", "unique"):
        return failure("STYLE_UNSUPPORTED", "agent_c", 'Unsupported raster renderer type')
    if not isinstance(band_no, int) or isinstance(band_no, bool) or not 1 <= band_no <= layer.bandCount():
        return failure("INVALID_PARAMETER", "agent_c", 'Band number is outside the available range')
    
    # Helper: get stretch statistics.
    def get_min_max(layer, band):
        stats = layer.dataProvider().bandStatistics(band, QgsRasterBandStats.All)
        return stats.minimumValue, stats.maximumValue

    try:
        if raster_type == "gray":
            min_val, max_val = get_min_max(layer, band_no)
            renderer = QgsSingleBandGrayRenderer(layer.dataProvider(), band_no)
            
            # Create a contrast enhancement object.
            ce = QgsContrastEnhancement(layer.dataProvider().dataType(band_no))
            ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
            ce.setMinimumValue(min_val)
            ce.setMaximumValue(max_val)
            
            renderer.setContrastEnhancement(ce)
            layer.setRenderer(renderer)

        elif raster_type == "hillshade":
            renderer = QgsHillshadeRenderer(layer.dataProvider(), band_no, 
                                          config.get("hillshade_azimuth", 315.0), 
                                          config.get("hillshade_altitude", 45.0))
            renderer.setZFactor(config.get("hillshade_z_factor", 1.0))
            layer.setRenderer(renderer)

        elif raster_type == "pseudocolor":
            min_val, max_val = get_min_max(layer, band_no)
            
            # Create the shader.
            shader = QgsRasterShader()
            color_ramp_shader = QgsColorRampShader(min_val, max_val)
            
            # Interpolation method.
            interp_map = {
                "linear": QgsColorRampShader.Interpolated,
                "discrete": QgsColorRampShader.Discrete,
                "exact": QgsColorRampShader.Exact
            }
            color_ramp_shader.setColorRampType(interp_map.get(config.get("interpolation", "linear"), QgsColorRampShader.Interpolated))
            
            # Get the color ramp.
            ramp_name = config.get("color_ramp_name", "Spectral")
            style = QgsStyle.defaultStyle()
            ramp = style.colorRamp(ramp_name)
            if not ramp:
                ramp = style.colorRamp("Spectral") # Fallback.
            
            if config.get("invert_ramp", False):
                ramp.invert()
                
            # Classification mode and classes.
            mode_map = {
                "continuous": QgsColorRampShader.Continuous,
                "equal_interval": QgsColorRampShader.EqualInterval,
                "quantile": QgsColorRampShader.Quantile
            }
            class_mode = mode_map.get(config.get("classification_mode", "continuous"), QgsColorRampShader.Continuous)
            classes_count = config.get("classes_count", 5)
            
            # DEM quantile logic: evenly spaced ramp colors with quantile values.
            # Set shader properties first.
            color_ramp_shader.setSourceColorRamp(ramp)
            color_ramp_shader.setClassificationMode(class_mode)
            
            # PyQGIS classifyColorRamp handles the selected mode automatically.
            color_ramp_shader.classifyColorRamp(classes_count, band_no, layer.extent(), layer.dataProvider())
            
            shader.setRasterShaderFunction(color_ramp_shader)
            renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), band_no, shader)
            layer.setRenderer(renderer)

        elif raster_type == "unique":
            classes = []
            
            classes = QgsPalettedRasterRenderer.classDataFromRaster(layer.dataProvider(), band_no)
                
            # Assign a new random color to each category.
            for cls in classes:
                # Generate a random RGB color.
                cls.color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            
            # Create the renderer.
            renderer = QgsPalettedRasterRenderer(layer.dataProvider(), band_no, classes)
            layer.setRenderer(renderer)

        layer.triggerRepaint()
        return f"Success: Applied raster style '{raster_type}' to layer."

    except Exception as e:
        return failure("STYLE_FAILED", "agent_c", f"Error in raster styling: {str(e)}")

# Main entry point.
@execution_boundary("agent_c", "STYLE_FAILED")
def set_layer_style(layer_name: str, full_config: Dict[str, Any]) -> ToolResult:
    """Main entry point. layer_name identifies the layer; full_config is the full schema JSON object including style_type and style_config."""
    project = QgsProject.instance()
    layers = project.mapLayersByName(layer_name)
    if not layers:
        return failure("LAYER_NOT_FOUND", "agent_c", f"Error: Layer '{layer_name}' not found.")

    layer = layers[0]
    # Unpack configuration.
    style_type = full_config.get("style_type", "single")
    config = full_config.get("style_config", {})
    if not isinstance(config, dict):
        return failure("INVALID_PARAMETER", "agent_c", 'style_config must be an object', target_layer=layer_name)
    field_name = config.get("target_field_actual")
    if style_type in ("categorized", "graduated", "annotation"):
        if not field_name or layer.fields().indexOf(field_name) < 0:
            return failure("FIELD_NOT_FOUND", "agent_c", 'The target field does not exist', target_layer=layer_name,
                           target_field=field_name or 'Unspecified')
    if style_type == "graduated":
        count = config.get("graduated_config", {}).get("classes_count", 5)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return failure("INVALID_PARAMETER", "agent_c", 'Class count must be a positive integer', target_layer=layer_name)
    base_params = config.get("symbol_layer_params", {})  # Base style parameters.

    # Handle vector layer styling.
    if isinstance(layer, QgsVectorLayer):
        # Get geometry type (0: point, 1: line, 2: polygon).
        geom_type = layer.geometryType()

        try:
            # 1. Single symbol.
            if style_type == "single":
                # Get the style modification configuration.
                edit_config = config.get("edit_style_config", {})

                renderer = layer.renderer()

                # Whether this modifies the existing style.
                is_editing = bool(edit_config and edit_config.get("edit_intent"))

                if is_editing and isinstance(renderer, QgsSingleSymbolRenderer):
                    symbol = renderer.symbol().clone()
                else:
                    symbol = create_base_symbol(geom_type, base_params)

                if symbol:
                    if is_editing:
                        modify_symbol_by_edit_config(symbol, edit_config)

                    renderer = QgsSingleSymbolRenderer(symbol)
                    layer.setRenderer(renderer)
                else:
                    return failure("STYLE_FAILED", "agent_c", f"Error: Failed to create symbol for geometry type {geom_type}")

            # 2. Categorized rendering.
            elif style_type == "categorized":
                field_name = config.get("target_field_actual")  # Use the actual field name resolved by Agent C.
                if not field_name:
                    return failure("FIELD_NOT_FOUND", "agent_c", "Error: Categorized style requires a valid field (match failed).")

                cat_config = config.get("categories_config", {})
                cat_data_list = cat_config.get("categories_data", [])
                target_attr = cat_config.get("categories_attribute", "color")  # color | size | width
                color_palette = cat_config.get("color_palette", [])

                categories = []

                # Get all unique values of this field.
                f_idx = layer.fields().indexOf(field_name)
                if f_idx == -1:
                    return failure("FIELD_NOT_FOUND", "agent_c", f"Error: Field '{field_name}' not found in layer.")
                unique_values = layer.dataProvider().uniqueValues(f_idx)

                # Create a symbol for each unique value.
                for i, val in enumerate(unique_values):
                    # Look up value-specific configuration.
                    specific_conf = next((item for item in cat_data_list if str(item.get("value")) == str(val)), None)

                    if specific_conf and "symbol_params" in specific_conf:
                        # Merge specific configuration before creating the symbol.
                        merged_params = {**base_params, **specific_conf["symbol_params"]}
                        symbol = create_base_symbol(geom_type, merged_params)
                    else:
                        # Create the symbol with base parameters.
                        symbol = create_base_symbol(geom_type, base_params)

                        # Without specific configuration, use a random color or palette for color attributes.
                        if target_attr == "color":
                            if color_palette:
                                hex_color = color_palette[i % len(color_palette)]
                                symbol.setColor(parse_color(hex_color))
                            else:
                                rand_color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                                symbol.setColor(rand_color)

                    categories.append(QgsRendererCategory(val, symbol, str(val)))

                renderer = QgsCategorizedSymbolRenderer(field_name, categories)
                layer.setRenderer(renderer)

            # 3. Graduated rendering.
            elif style_type == "graduated":
                field_name = config.get("target_field_actual")
                if not field_name:
                    return failure("FIELD_NOT_FOUND", "agent_c", "Error: Graduated style requires a valid field.")

                grad_config = config.get("graduated_config", {})
                method_str = grad_config.get("classification_method", "Quantile")
                classes_count = grad_config.get("classes_count", 5)
                ramp_colors = grad_config.get("ramp_colors", ["#FFFFFF", "#FF0000"])  #

                # 1. Create a gradient color ramp.
                c1 = parse_color(ramp_colors[0])
                c2 = parse_color(ramp_colors[-1] if len(ramp_colors) > 1 else ramp_colors[0])
                ramp = QgsGradientColorRamp(c1, c2)

                # 2. Create a base symbol.
                base_symbol = create_base_symbol(geom_type, base_params)

                # 3. Initialize the renderer.
                renderer = QgsGraduatedSymbolRenderer(field_name, [QgsRendererRange(0, 0, base_symbol, "Legend")])
                renderer.setSourceColorRamp(ramp)

                # 4. Set the classification method.
                if method_str == "NaturalBreaks":
                    renderer.setClassificationMethod(QgsClassificationJenks())
                elif method_str == "EqualInterval":
                    renderer.setClassificationMethod(QgsClassificationEqualInterval())
                else:
                    renderer.setClassificationMethod(QgsClassificationQuantile())

                # 5. Calculate and apply classes.
                renderer.updateClasses(layer, classes_count)

                # 6. Handle size/width gradients.
                scale_attr = grad_config.get("symbol_scale_attribute", "color")
                if scale_attr in ["size", "width"]:
                    ramp_size = grad_config.get("ramp_size", [])
                    if not ramp_size or len(ramp_size) < 2:
                        ramp_size = [1.0, 5.0]
                    else:
                        # Clean numeric strings: "float: 1.0" -> 1.0.
                        try:
                            min_s = float(str(ramp_size[0]).split(":")[-1])
                            max_s = float(str(ramp_size[-1]).split(":")[-1])
                        except:
                            min_s, max_s = 1.0, 5.0

                    ranges = renderer.ranges()
                    if len(ranges) > 1:
                        step = (max_s - min_s) / (len(ranges) - 1)
                        for i, rng in enumerate(ranges):
                            new_sym = rng.symbol().clone()
                            curr_size = min_s + (i * step)
                            if isinstance(new_sym, QgsLineSymbol):
                                new_sym.setWidth(curr_size)
                            elif isinstance(new_sym, QgsMarkerSymbol):
                                new_sym.setSize(curr_size)
                            renderer.updateRangeSymbol(i, new_sym)

                layer.setRenderer(renderer)

            # 4. Annotation.
            elif style_type == "annotation":
                field_name = config.get("target_field_actual")
                if not field_name:
                    return failure("FIELD_NOT_FOUND", "agent_c", "Error: Categorized style requires a valid field (match failed).")

                anno_config = config.get("annotation_config", {})
                return apply_annotation_style(layer, field_name, anno_config)
            
            else:
                return failure("STYLE_UNSUPPORTED", "agent_c", f"Error: Unsupported style type '{style_type}'")

            layer.triggerRepaint()
            project.layerTreeRoot().findLayer(layer.id()).setExpanded(True)
            project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(True)
            return f"Success: Applied '{style_type}' style to layer '{layer_name}'."

        except Exception as e:
            import traceback
            return failure("STYLE_FAILED", "agent_c", f"Error setting style: {str(e)}\n{traceback.format_exc()}")


    # Handle raster layer styling.
    if isinstance(layer, QgsRasterLayer):
        if style_type == "raster":
            try: 
                raster_config = config.get("raster_config", {})
                return apply_raster_style(layer, raster_config)
            except Exception as e:
                import traceback
                return failure("STYLE_FAILED", "agent_c", f"Error setting raster style: {str(e)}\n{traceback.format_exc()}")
        else:
            return failure("STYLE_UNSUPPORTED", "agent_c", f"Error: Unsupported style type '{style_type}'")

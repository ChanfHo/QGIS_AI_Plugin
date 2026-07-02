import random
from typing import Dict, Any
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import Qt
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsSymbol, QgsMarkerSymbol, QgsLineSymbol,
    QgsFillSymbol, QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer, QgsRendererCategory, QgsRendererRange,
    QgsStyle, QgsColorRamp, QgsGradientColorRamp,
    QgsClassificationQuantile, QgsClassificationJenks, QgsClassificationEqualInterval,
    QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings, QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling, QgsExpression,
    QgsSingleBandGrayRenderer, QgsSingleBandPseudoColorRenderer,
    QgsPalettedRasterRenderer, QgsHillshadeRenderer, QgsRasterShader,
    QgsColorRampShader, QgsRasterBandStats, QgsContrastEnhancement,
    QgsWkbTypes
)

# --- 样式映射常量 ---
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


# --- 颜色解析函数 ---
def parse_color(color_str: str, default: str = "#000000") -> QColor:
    """解析颜色字符串，失败则返回默认值"""
    if not color_str:
        return QColor(default)
    try:
        c = QColor(color_str)
        return c if c.isValid() else QColor(default)
    except:
        return QColor(default)


# --- 符号配置函数 ---
def configure_symbol_layer(symbol: QgsSymbol, params: Dict[str, Any]):
    """
    根据 symbol_layer_params 字典配置符号的具体属性
    对应 Schema 中的 symbol_layer_params 部分
    """
    if not symbol:
        return

    # 1. 顶层属性设置 (Size, Width, Angle) - 区分几何类型
    # 点符号 (Marker): 支持 setSize, setAngle
    if isinstance(symbol, QgsMarkerSymbol):
        if "size" in params:
            symbol.setSize(float(params["size"]))
        if "angle" in params:
            symbol.setAngle(float(params["angle"]))

    # 线符号 (Line): 支持 setWidth (不支持 setSize, setAngle)
    elif isinstance(symbol, QgsLineSymbol):
        if "line_width" in params:
            symbol.setWidth(float(params["line_width"]))

    # 面符号 (Fill): 没有顶层 size/width (不支持 setSize)
    elif isinstance(symbol, QgsFillSymbol):
        pass

    # 2. 符号层级详细属性设置 (Color, Style, Stroke)
    if symbol.symbolLayerCount() > 0:
        sl = symbol.symbolLayer(0)

        # A. 点 (Marker) - SimpleMarker
        if isinstance(symbol, QgsMarkerSymbol):
            # 形状
            if params.get("marker_type") == "simple" and "name" in params:
                # 获取一个临时符号来提取 shape 枚举
                temp_sym = QgsMarkerSymbol.createSimple({'name': params['name']})
                if temp_sym and temp_sym.symbolLayerCount() > 0:
                    sl.setShape(temp_sym.symbolLayer(0).shape())

            # 填充颜色 (SimpleMarker 的 fill)
            if "fill_color" in params:
                sl.setColor(parse_color(params["fill_color"]))

            # 描边/边框 (SimpleMarker 的 stroke)
            if "outline_color" in params:
                sl.setStrokeColor(parse_color(params["outline_color"]))
            if "outline_width" in params:
                sl.setStrokeWidth(float(params["outline_width"]))
            if "outline_style" in params:
                o_style = params["outline_style"]
                sl.setStrokeStyle(PEN_STYLES.get(o_style, Qt.SolidLine))

        # B. 线 (Line) - SimpleLine
        elif isinstance(symbol, QgsLineSymbol):
            # 线颜色
            if "line_color" in params:
                sl.setColor(parse_color(params["line_color"]))
            # 线宽 (如果在顶层设置了，这里通常会自动同步，但显式设置更安全)
            if "line_width" in params:
                sl.setWidth(float(params["line_width"]))

            # 线型样式
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

        # C. 面 (Fill) - SimpleFill
        elif isinstance(symbol, QgsFillSymbol):
            # 填充颜色
            if "fill_color" in params:
                sl.setColor(parse_color(params["fill_color"]))
            # 填充样式 (Solid, Cross, etc.)
            if "fill_style" in params:
                sl.setBrushStyle(BRUSH_STYLES.get(params["fill_style"], Qt.SolidPattern))

            # 边框 (Fill 层的 stroke)
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


# --- 样式模糊修改处理函数 ---
def modify_symbol_by_edit_config(symbol: QgsSymbol, edit_config: Dict[str, Any]):
    """
    根据 edit_style_config 修改已有符号
    支持 edit_intent × edit_scope × edit_strength 的组合
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

        # ---------- 颜色相关 ----------
        def adjust_color(color: QColor) -> QColor:
            if not color.isValid():
                return color

            # 提取颜色的HSL系数
            h, s, l, a = color.getHsl()
            s /= 255.0
            l /= 255.0

            # 颜色调整逻辑
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

        # ---------- 尺寸 / 线宽 ----------
        def scale_value(v: float) -> float:
            if intent in ["larger", "thicker", "more_prominent"]:
                return v * scale_up
            elif intent in ["smaller", "thinner", "less_prominent"]:
                return v * scale_down
            return v

        # 点 size
        if "size" in scopes and isinstance(symbol, QgsMarkerSymbol):
            if hasattr(sl, "size") and hasattr(sl, "setSize"):
                sl.setSize(scale_value(sl.size()))

        # 线 width
        if "line_width" in scopes and hasattr(sl, "width") and hasattr(sl, "setWidth"):
            sl.setWidth(scale_value(sl.width()))

        # 面 / 点 outline width
        if "outline_width" in scopes and hasattr(sl, "strokeWidth") and hasattr(sl, "setStrokeWidth"):
            sl.setStrokeWidth(scale_value(sl.strokeWidth()))


# --- 创建基础符号函数 ---
def create_base_symbol(geometry_type: int, params: Dict[str, Any]) -> QgsSymbol:
    """创建一个基础符号并应用初始参数"""
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


# --- 注记处理函数 ---
def apply_annotation_style(layer: QgsVectorLayer, field_name: str, config: Dict[str, Any]) -> str:
    """
    应用注记样式
    :param config: 对应 Schema 中的 'annotation_config' 部分

    """
    target_field = field_name
    if not target_field:
        return "Error: No valid field found for annotation."

    # 配置字体格式 (QgsTextFormat)
    text_format = QgsTextFormat()
    font = QFont(config.get("font_family", "Microsoft YaHei"))  # 字体族
    font.setBold(config.get("is_bold", False))  # 加粗
    font.setItalic(config.get("is_italic", False))  # 斜体
    text_format.setFont(font)
    text_format.setSize(float(config.get("font_size", 10.0)))  # 字号 (Schema通常返回Points单位)
    text_format.setColor(parse_color(config.get("font_color", "#000000")))  # 颜色

    # 配置描边/晕圈 (Buffer)
    if config.get("draw_buffer", True):
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(float(config.get("buffer_size", 1.0)))
        buffer_settings.setColor(parse_color(config.get("buffer_color", "#FFFFFF")))
        text_format.setBuffer(buffer_settings)

    # 配置布局设置 (QgsPalLayerSettings)
    settings = QgsPalLayerSettings()
    settings.setFormat(text_format)
    settings.fieldName = target_field

    mode_str = config.get("mode", "free").lower()

    # 映射位置模式
    if mode_str in LABEL_PLACEMENT_MAP:
        settings.placement = LABEL_PLACEMENT_MAP[mode_str]
    else:
        # 默认回退逻辑
        geom_type = layer.geometryType()
        if geom_type == 0:  # Point
            settings.placement = QgsPalLayerSettings.OrderedPositionsAroundPoint
        elif geom_type == 1:  # Line
            settings.placement = QgsPalLayerSettings.Curved
        else:  # Polygon
            settings.placement = QgsPalLayerSettings.Horizontal

    # 偏移量处理 (offset_xy)
    offset = config.get("offset_xy", [0.0, 0.0])
    if isinstance(offset, list) and len(offset) >= 2:
        # 对于大多数模式，xOffset/yOffset 属性控制偏移
        settings.xOffset = float(offset[0])
        settings.yOffset = float(offset[1])
        # 注意: 周围点模式可能使用 dist 属性，此处简化处理

    # 应用设置
    labeling = QgsVectorLayerSimpleLabeling(settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()

    return f"Success: Annotation added on field '{target_field}'."


# --- 栅格渲染处理函数 ---
def apply_raster_style(layer: QgsRasterLayer, config: Dict[str, Any]) -> str:
    """
    应用栅格样式逻辑
    :param layer: QgsRasterLayer 对象
    :param config: 对应 Schema 中的 'raster_config' 部分
    """
    raster_type = config.get("raster_type", "single_band_pseudocolor")
    band_no = config.get("band_no", 1)
    
    # 辅助函数：获取拉伸统计值
    def get_min_max(layer, band):
        stats = layer.dataProvider().bandStatistics(band, QgsRasterBandStats.All)
        return stats.minimumValue, stats.maximumValue

    try:
        if raster_type == "gray":
            min_val, max_val = get_min_max(layer, band_no)
            renderer = QgsSingleBandGrayRenderer(layer.dataProvider(), band_no)
            
            # 创建对比度增强对象
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
            
            # 创建着色器
            shader = QgsRasterShader()
            color_ramp_shader = QgsColorRampShader(min_val, max_val)
            
            # 插值方式
            interp_map = {
                "linear": QgsColorRampShader.Interpolated,
                "discrete": QgsColorRampShader.Discrete,
                "exact": QgsColorRampShader.Exact
            }
            color_ramp_shader.setColorRampType(interp_map.get(config.get("interpolation", "linear"), QgsColorRampShader.Interpolated))
            
            # 获取色带
            ramp_name = config.get("color_ramp_name", "Spectral")
            style = QgsStyle.defaultStyle()
            ramp = style.colorRamp(ramp_name)
            if not ramp:
                ramp = style.colorRamp("Spectral") # 回退
            
            if config.get("invert_ramp", False):
                ramp.invert()
                
            # 分类模式与分类
            mode_map = {
                "continuous": QgsColorRampShader.Continuous,
                "equal_interval": QgsColorRampShader.EqualInterval,
                "quantile": QgsColorRampShader.Quantile
            }
            class_mode = mode_map.get(config.get("classification_mode", "continuous"), QgsColorRampShader.Continuous)
            classes_count = config.get("classes_count", 5)
            
            # 关键：针对 DEM 优化的 Quantile 逻辑 (等间距色带 + 分位数取值)
            # 先设置 Shader 的属性
            color_ramp_shader.setSourceColorRamp(ramp)
            color_ramp_shader.setClassificationMode(class_mode)
            
            # 在 PyQGIS 中，classifyColorRamp 会根据 mode 自动处理
            color_ramp_shader.classifyColorRamp(classes_count, band_no, layer.extent(), layer.dataProvider())
            
            shader.setRasterShaderFunction(color_ramp_shader)
            renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), band_no, shader)
            layer.setRenderer(renderer)

        elif raster_type == "unique":
            classes = []
            
            classes = QgsPalettedRasterRenderer.classDataFromRaster(layer.dataProvider(), band_no)
                
            # 为每个分类重新分配随机颜色
            for cls in classes:
                # 生成随机 RGB 颜色
                cls.color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            
            # 创建渲染器
            renderer = QgsPalettedRasterRenderer(layer.dataProvider(), band_no, classes)
            layer.setRenderer(renderer)

        layer.triggerRepaint()
        return f"Success: Applied raster style '{raster_type}' to layer."

    except Exception as e:
        return f"Error in raster styling: {str(e)}"

# 主入口函数
def set_layer_style(layer_name: str, full_config: Dict[str, Any]) -> str:
    """
    主要入口函数
    :param layer_name: 图层名称
    :param full_config: 对应 Schema 中的整个 JSON 对象 (含 style_type, style_config)
    """
    project = QgsProject.instance()
    layers = project.mapLayersByName(layer_name)
    if not layers:
        return f"Error: Layer '{layer_name}' not found."

    layer = layers[0]
    # 解包配置
    style_type = full_config.get("style_type", "single")
    config = full_config.get("style_config", {})
    base_params = config.get("symbol_layer_params", {})  # 基础样式参数

    # 处理矢量图层样式
    if isinstance(layer, QgsVectorLayer):
        # 获取几何类型 (0:Point, 1:Line, 2:Polygon)
        geom_type = layer.geometryType()

        try:
            # 1. Single Symbol (单一符号)
            if style_type == "single":
                # 获取修改样式配置
                edit_config = config.get("edit_style_config", {})

                renderer = layer.renderer()

                # 是否为“修改现有样式”
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
                    return f"Error: Failed to create symbol for geometry type {geom_type}"

            # 2. Categorized (分类渲染)
            elif style_type == "categorized":
                field_name = config.get("target_field_actual")  # 注意：这里使用 Agent C 解析后的实际字段名
                if not field_name:
                    return "Error: Categorized style requires a valid field (match failed)."

                cat_config = config.get("categories_config", {})
                cat_data_list = cat_config.get("categories_data", [])
                target_attr = cat_config.get("categories_attribute", "color")  # color | size | width
                color_palette = cat_config.get("color_palette", [])

                categories = []

                # 获取该字段的所有唯一值
                f_idx = layer.fields().indexOf(field_name)
                if f_idx == -1:
                    return f"Error: Field '{field_name}' not found in layer."
                unique_values = layer.dataProvider().uniqueValues(f_idx)

                # 为每个唯一值创建符号
                for i, val in enumerate(unique_values):
                    # 查找是否有针对该值的特定配置
                    specific_conf = next((item for item in cat_data_list if str(item.get("value")) == str(val)), None)

                    if specific_conf and "symbol_params" in specific_conf:
                        # 如果有特定配置，合并参数后创建符号
                        merged_params = {**base_params, **specific_conf["symbol_params"]}
                        symbol = create_base_symbol(geom_type, merged_params)
                    else:
                        # 使用基础参数创建符号
                        symbol = create_base_symbol(geom_type, base_params)

                        # 如果没有特定配置，且属性是颜色，则赋予随机颜色或使用色板
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

            # 3. Graduated (分级渲染)
            elif style_type == "graduated":
                field_name = config.get("target_field_actual")
                if not field_name:
                    return "Error: Graduated style requires a valid field."

                grad_config = config.get("graduated_config", {})
                method_str = grad_config.get("classification_method", "Quantile")
                classes_count = grad_config.get("classes_count", 5)
                ramp_colors = grad_config.get("ramp_colors", ["#FFFFFF", "#FF0000"])  #

                # 1. 创建渐变色带
                c1 = parse_color(ramp_colors[0])
                c2 = parse_color(ramp_colors[-1] if len(ramp_colors) > 1 else ramp_colors[0])
                ramp = QgsGradientColorRamp(c1, c2)

                # 2. 创建基础符号
                base_symbol = create_base_symbol(geom_type, base_params)

                # 3. 初始化渲染器
                renderer = QgsGraduatedSymbolRenderer(field_name, [QgsRendererRange(0, 0, base_symbol, "Legend")])
                renderer.setSourceColorRamp(ramp)

                # 4. 设置分类方法
                if method_str == "NaturalBreaks":
                    renderer.setClassificationMethod(QgsClassificationJenks())
                elif method_str == "EqualInterval":
                    renderer.setClassificationMethod(QgsClassificationEqualInterval())
                else:
                    renderer.setClassificationMethod(QgsClassificationQuantile())

                # 5. 计算分类并应用
                renderer.updateClasses(layer, classes_count)

                # 6. 处理 Size/Width 渐变
                scale_attr = grad_config.get("symbol_scale_attribute", "color")
                if scale_attr in ["size", "width"]:
                    ramp_size = grad_config.get("ramp_size", [])
                    if not ramp_size or len(ramp_size) < 2:
                        ramp_size = [1.0, 5.0]
                    else:
                        # 简单的字符串清洗 "float: 1.0" -> 1.0
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

            # 4. Annotation (添加注记)
            elif style_type == "annotation":
                field_name = config.get("target_field_actual")
                if not field_name:
                    return "Error: Categorized style requires a valid field (match failed)."

                anno_config = config.get("annotation_config", {})
                return apply_annotation_style(layer, field_name, anno_config)
            
            else:
                return f"Error: Unsupported style type '{style_type}'"

            layer.triggerRepaint()
            project.layerTreeRoot().findLayer(layer.id()).setExpanded(True)
            project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(True)
            return f"Success: Applied '{style_type}' style to layer '{layer_name}'."

        except Exception as e:
            import traceback
            return f"Error setting style: {str(e)}\n{traceback.format_exc()}"


    # 处理栅格图层样式
    if isinstance(layer, QgsRasterLayer):
        if style_type == "raster":
            try: 
                raster_config = config.get("raster_config", {})
                return apply_raster_style(layer, raster_config)
            except Exception as e:
                import traceback
                return f"Error setting raster style: {str(e)}\n{traceback.format_exc()}"
        else:
            return f"Error: Unsupported style type '{style_type}'"




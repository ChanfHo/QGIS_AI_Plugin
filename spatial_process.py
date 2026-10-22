from .error_handling import failure, execution_boundary, sanitize, ToolResult
import logging
from typing import Dict, Any, List
from qgis import processing
from qgis.core import QgsProject, QgsMapLayer, QgsVectorLayer, QgsMessageLog, Qgis, QgsApplication, QgsProcessingContext, QgsProcessingParameterDefinition
from qgis.utils import iface  # 导入 iface 用于地图刷新


def get_layer_by_name(layer_name: str) -> QgsMapLayer or None:
    """根据图层名称获取图层对象，如果找不到则返回 None。"""
    layers = QgsProject.instance().mapLayersByName(layer_name)
    return layers[0] if layers else None


@execution_boundary("agent_b", "PROCESSING_FAILED")
def execute_geoprocessing_task(alg_id: str, params: Dict[str, Any]) -> ToolResult:
    """
    执行 QGIS 空间分析算法。这是 Agent B 的核心执行函数。
    :param alg_id: QGIS Processing 算法ID，如 'native:buffer'。
    :param params: LLM 解析出的参数字典，其中的图层名称已经被 run_agent_b 模糊匹配并校正。
                   必须包含 'CUSTOM_LAYER_NAME' 键来命名输出图层。
    :return: 成功摘要或包含error_state的结构化失败结果。
    """
    project = QgsProject.instance()
    if not isinstance(alg_id, str) or not isinstance(params, dict):
        return failure("INVALID_PARAMETER", "agent_b", "alg_id必须为文本，params必须为对象")
    algorithm = QgsApplication.processingRegistry().algorithmById(alg_id)
    if algorithm is None:
        return failure("ALGORITHM_NOT_FOUND", "agent_b", "算法未注册", failed_action=alg_id)
    exec_params = params.copy()

    # 1. 提取自定义图层名称
    target_layer_name = exec_params.pop('CUSTOM_LAYER_NAME', f"result_{alg_id.split(':')[-1]}")

    # 2. 转换图层名称字符串为 QgsMapLayer 对象
    # 遍历参数，识别所有需要图层对象的地方
    for k, v in exec_params.items():
        # 如果值是字符串，并且键名可能代表一个图层输入
        if isinstance(v, str) and (k.upper() in ['INPUT', 'OVERLAY', 'JOIN', 'CLIP'] or k.endswith('_LAYER')):
            layer_obj = get_layer_by_name(v)
            if not layer_obj:
                # 理论上 run_agent_b 已做模糊匹配，这里是双重保障
                return failure("LAYER_NOT_FOUND", "agent_b", "输入图层不存在", target_layer=v)
            exec_params[k] = layer_obj  # 替换为 QgsMapLayer 对象

    # 3. 指定输出目标
    # 查找算法的输出参数名，并将其设置为 'memory:' (矢量) 或 'TEMPORARY_OUTPUT' (栅格)
    output_param_name = 'OUTPUT'  # 默认输出参数名
    is_raster_output = False

    # 尝试更准确地获取输出参数名（处理如 'DISSOLVE' 算法可能使用 'OUTPUT'）
    try:
        alg = processing.algorithmFromString(alg_id)
        if alg:
            for param in alg.outputParameters():
                # 寻找输出参数
                if param.type() in [param.Type.MapLayer, param.Type.VectorLayer, param.Type.RasterLayer]:
                    output_param_name = param.name()
                    if param.type() == param.Type.RasterLayer or alg_id.startswith('gdal:'):
                        is_raster_output = True
                    break
    except Exception:
        if alg_id.startswith('gdal:'):
             is_raster_output = True

    # 如果是原地修改数据的算法 (如字段计算器，它将输入图层作为输出)，则不使用 'memory:'
    # 而是让它默认修改 'INPUT' 图层（如果算法支持）
    is_inplace_mod = alg_id.endswith('fieldcalculator')

    if not is_inplace_mod:
        if is_raster_output:
            # GDAL 算法处理栅格数据不能输出为 memory:，需要指定为 'TEMPORARY_OUTPUT'
            exec_params[output_param_name] = 'TEMPORARY_OUTPUT'
        else:
            exec_params[output_param_name] = 'memory:'

    # 4. 执行算法
    try:
        missing = [definition.name() for definition in algorithm.parameterDefinitions()
                   if definition.name() not in exec_params and definition.defaultValue() is None
                   and not definition.flags() & QgsProcessingParameterDefinition.FlagOptional]
        if missing:
            return failure("MISSING_PARAMETER", "agent_b", "缺少算法必需参数", missing_fields=missing)
        context = QgsProcessingContext()
        context.setProject(project)
        valid, reason = algorithm.checkParameterValues(exec_params, context)
        if not valid:
            return failure("INVALID_PARAMETER", "agent_b", reason, parameters=params)
        result = processing.run(alg_id, exec_params)

        # 6. 处理输出结果
        if output_param_name in result and not is_inplace_mod:
            # 处理生成新图层的算法
            output_layer_path = result[output_param_name]
            
            output_layer = None
            if isinstance(output_layer_path, QgsMapLayer):
                output_layer = output_layer_path
            elif isinstance(output_layer_path, str):
                # 针对栅格TEMPORARY_OUTPUT或特定输出，会返回文件路径
                if is_raster_output:
                    from qgis.core import QgsRasterLayer
                    output_layer = QgsRasterLayer(output_layer_path, target_layer_name)
                else:
                    output_layer = QgsVectorLayer(output_layer_path, target_layer_name, "ogr")

            if output_layer and output_layer.isValid():
                project.addMapLayer(output_layer, True)
                output_layer.setName(target_layer_name)

                # 刷新地图画布
                # if iface and iface.mapCanvas():
                #     iface.mapCanvas().setExtent(output_layer.extent())
                #     iface.mapCanvas().refresh()

                return f"Success: 空间分析 '{alg_id.split(':')[-1]}' 成功执行，已生成新图层 '{target_layer_name}'。"
            else:
                return failure("LAYER_LOAD_FAILED", "agent_b", f"Error: 算法 '{alg_id}' 执行成功，但无法加载输出图层（格式无效或损坏）。")

        else:
            # 处理原地修改的算法 (例如 fieldcalculator, 或统计类算法)

            # 如果是原地修改，需要手动刷新目标图层
            if is_inplace_mod and 'INPUT' in exec_params:
                target_layer = exec_params['INPUT']
                if isinstance(target_layer, QgsVectorLayer):
                    target_layer.dataProvider().reloadData()
                    target_layer.triggerRepaint()

            return f"Success: 空间分析 '{alg_id.split(':')[-1]}' 成功执行。"

    except Exception as e:
        return failure("PROCESSING_FAILED", "agent_b", f"Error: 执行 QGIS 算法 '{alg_id}' 失败: {str(e)}")

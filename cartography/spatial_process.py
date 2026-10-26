from ..core.error_handling import failure, execution_boundary, ToolResult
from typing import Dict, Any
from qgis import processing
from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsApplication,
    QgsProcessingContext,
    QgsProcessingParameterDefinition,
)


def get_layer_by_name(layer_name: str) -> QgsMapLayer or None:
    """Get a layer by name; return None if it is not found."""
    layers = QgsProject.instance().mapLayersByName(layer_name)
    return layers[0] if layers else None


@execution_boundary("agent_b", "PROCESSING_FAILED")
def execute_geoprocessing_task(alg_id: str, params: Dict[str, Any]) -> ToolResult:
    """Execute QGIS spatial analysis for Agent B.

    :param alg_id: QGIS Processing algorithm ID, such as 'native:buffer'.
    :param params: LLM-parsed parameters with layer names fuzzy-matched by run_agent_b.
        Must include CUSTOM_LAYER_NAME for output naming.
    :return: A success summary or a structured failure containing error_state.
    """
    project = QgsProject.instance()
    if not isinstance(alg_id, str) or not isinstance(params, dict):
        return failure("INVALID_PARAMETER", "agent_b", 'alg_id must be text and params must be an object')
    algorithm = QgsApplication.processingRegistry().algorithmById(alg_id)
    if algorithm is None:
        return failure("ALGORITHM_NOT_FOUND", "agent_b", 'Algorithm not registered', failed_action=alg_id)
    exec_params = params.copy()

    # 1. Extract the custom layer name.
    target_layer_name = exec_params.pop('CUSTOM_LAYER_NAME', f"result_{alg_id.split(':')[-1]}")

    # 2. Convert layer names to QgsMapLayer objects.
    # Inspect parameters to find every location requiring a layer object.
    for k, v in exec_params.items():
        # If the value is a string and the key may identify a layer input.
        if isinstance(v, str) and (k.upper() in ['INPUT', 'OVERLAY', 'JOIN', 'CLIP'] or k.endswith('_LAYER')):
            layer_obj = get_layer_by_name(v)
            if not layer_obj:
                # run_agent_b should already have fuzzy-matched names; check again here.
                return failure("LAYER_NOT_FOUND", "agent_b", 'The input layer does not exist', target_layer=v)
            exec_params[k] = layer_obj  # Replace with a QgsMapLayer object.

    # 3. Specify the output target.
    # Find the output parameter and use memory: for vectors or TEMPORARY_OUTPUT for rasters.
    output_param_name = 'OUTPUT'  # Default output parameter name.
    is_raster_output = False

    # Resolve the output parameter more accurately; algorithms such as DISSOLVE may use 'OUTPUT'.
    try:
        alg = processing.algorithmFromString(alg_id)
        if alg:
            for param in alg.outputParameters():
                # Find the output parameter.
                if param.type() in [param.Type.MapLayer, param.Type.VectorLayer, param.Type.RasterLayer]:
                    output_param_name = param.name()
                    if param.type() == param.Type.RasterLayer or alg_id.startswith('gdal:'):
                        is_raster_output = True
                    break
    except Exception:
        if alg_id.startswith('gdal:'):
             is_raster_output = True

    # Do not use memory: for in-place algorithms such as field calculation that output the input layer.
    # Let it modify INPUT by default if the algorithm supports this.
    is_inplace_mod = alg_id.endswith('fieldcalculator')

    if not is_inplace_mod:
        if is_raster_output:
            # GDAL raster algorithms require 'TEMPORARY_OUTPUT' rather than memory:.
            exec_params[output_param_name] = 'TEMPORARY_OUTPUT'
        else:
            exec_params[output_param_name] = 'memory:'

    # 4. Run the algorithm.
    try:
        missing = [definition.name() for definition in algorithm.parameterDefinitions()
                   if definition.name() not in exec_params and definition.defaultValue() is None
                   and not definition.flags() & QgsProcessingParameterDefinition.FlagOptional]
        if missing:
            return failure("MISSING_PARAMETER", "agent_b", 'Missing required algorithm parameters', missing_fields=missing)
        context = QgsProcessingContext()
        context.setProject(project)
        valid, reason = algorithm.checkParameterValues(exec_params, context)
        if not valid:
            return failure("INVALID_PARAMETER", "agent_b", reason, parameters=params)
        result = processing.run(alg_id, exec_params)

        # 6. Handle output results.
        if output_param_name in result and not is_inplace_mod:
            # Handle algorithms that create a new layer.
            output_layer_path = result[output_param_name]
            
            output_layer = None
            if isinstance(output_layer_path, QgsMapLayer):
                output_layer = output_layer_path
            elif isinstance(output_layer_path, str):
                # Raster TEMPORARY_OUTPUT and certain other outputs return a file path.
                if is_raster_output:
                    from qgis.core import QgsRasterLayer
                    output_layer = QgsRasterLayer(output_layer_path, target_layer_name)
                else:
                    output_layer = QgsVectorLayer(output_layer_path, target_layer_name, "ogr")

            if output_layer and output_layer.isValid():
                project.addMapLayer(output_layer, True)
                output_layer.setName(target_layer_name)

                return "Success: Spatial analysis '{v0}' completed; new layer '{v1}' created.".format(v0=alg_id.split(':')[-1], v1=target_layer_name)
            else:
                return failure("LAYER_LOAD_FAILED", "agent_b", "Error: Algorithm '{v0}' succeeded, but its output layer could not be loaded (invalid or corrupt format).".format(v0=alg_id))

        else:
            # Handle in-place algorithms, such as field calculation or statistics.

            # Refresh the target layer manually after an in-place edit.
            if is_inplace_mod and 'INPUT' in exec_params:
                target_layer = exec_params['INPUT']
                if isinstance(target_layer, QgsVectorLayer):
                    target_layer.dataProvider().reloadData()
                    target_layer.triggerRepaint()

            return "Success: Spatial analysis '{v0}' completed.".format(v0=alg_id.split(':')[-1])

    except Exception as e:
        return failure("PROCESSING_FAILED", "agent_b", "Error: QGIS algorithm '{v0}' failed: {v1}".format(v0=alg_id, v1=str(e)))

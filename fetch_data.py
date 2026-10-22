from .error_handling import failure, execution_boundary, sanitize, ToolResult
import os
import tempfile
import requests

from typing import Dict, Any

from .database import configure_qgis_uri, connect_database, get_database_config

from qgis._core import QgsRasterLayer
from qgis.core import Qgis, QgsVectorLayer, QgsProject, QgsMapLayer, QgsDataSourceUri, QgsMessageLog

LOG_TAG = 'AI_AGENT_DEBUG'
NETWORK_MAX_ATTEMPTS = 3


def _get_with_retry(url: str, **kwargs):
    """执行只读网络请求，失败时总计尝试3次。"""
    last_error = None
    for attempt in range(1, NETWORK_MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, **kwargs)
            if response.status_code < 500:
                return response
            last_error = requests.HTTPError(f"HTTP {response.status_code}")
            response.close()
        except requests.RequestException as exc:
            last_error = exc
        if attempt < NETWORK_MAX_ATTEMPTS:
            QgsMessageLog.logMessage(
                sanitize(f"远程请求失败，准备第{attempt + 1}次尝试: {last_error}"),
                tag=LOG_TAG,
                level=Qgis.Warning,
            )
    error = requests.RequestException(f"网络请求连续{NETWORK_MAX_ATTEMPTS}次失败: {sanitize(str(last_error))}")
    error.attempts = NETWORK_MAX_ATTEMPTS
    raise error

def add_layer_to_project(layer: QgsMapLayer, target_name: str) -> ToolResult:
    """内部辅助函数：将图层添加到 QGIS 项目并设置名称。"""
    if layer and layer.isValid():
        project = QgsProject.instance()

        # 清理同名旧图层
        existing_layers = project.mapLayersByName(target_name)
        if existing_layers:
            project.removeMapLayers([l.id() for l in existing_layers])

        # 添加图层
        project.addMapLayer(layer)
        layer.setName(target_name)
        return f"Success: 数据 '{target_name}' 已成功获取并加载。"
    else:
        return failure("LAYER_LOAD_FAILED", "agent_a", f"Error: 无法加载数据或数据无效。")


def fetch_local_file(file_path: str, target_name: str) -> ToolResult:
    """加载本地矢量文件。"""
    if not file_path:
        return failure("MISSING_PARAMETER", "agent_a", "Error: 缺少文件路径参数。")
    if not os.path.exists(file_path):
        # 在实际部署中，可能需要特殊的路径映射，但这里必须假设路径有效
        return failure("FILE_NOT_FOUND", "agent_a", f"Error: 找不到本地文件: {file_path}")

    # 使用 QgsVectorLayer(uri, baseName, providerName) 构造函数
    layer = QgsVectorLayer(file_path, target_name, 'ogr')
    if not layer.isValid():
        return failure("FILE_INVALID", "agent_a", "文件无法识别为有效矢量数据", target_layer=target_name)

    return add_layer_to_project(layer, target_name)


def fetch_local_raster(file_path: str, target_name: str) -> ToolResult:
    """加载本地栅格文件。"""
    if not file_path: return failure("MISSING_PARAMETER", "agent_a", "Error: 缺少文件路径参数。")
    if not os.path.exists(file_path): return failure("FILE_NOT_FOUND", "agent_a", f"Error: 找不到本地文件: {file_path}")

    # 使用 QgsRasterLayer 加载
    layer = QgsRasterLayer(file_path, target_name)
    if layer.isValid():
        return add_layer_to_project(layer, target_name)
    return failure("FILE_INVALID", "agent_a", "Error: 文件存在但无法识别为栅格数据。")


def fetch_cloud_shp(sql_query: str, target_name: str) -> ToolResult:
    """
    【AI 工具】根据 SQL 语句从 PostGIS 数据库直接加载图层。
    """
    from qgis.core import QgsMessageLog, Qgis
    
    QgsMessageLog.logMessage("准备执行PostGIS矢量查询", tag=LOG_TAG, level=Qgis.Info)

    uri = QgsDataSourceUri()
    configure_qgis_uri(uri)
    
    # 将 SQL 作为子查询作为数据源，必须指定几何列 'geom' 和主键 'gid'
    uri.setDataSource("", f"({sql_query})", "geom", "", "gid")
    
    uri_string = uri.uri()
    QgsMessageLog.logMessage(sanitize("已构造PostGIS图层数据源"), tag=LOG_TAG, level=Qgis.Info)
    
    layer = QgsVectorLayer(uri_string, target_name, "postgres")
    
    if layer.isValid():
        QgsMessageLog.logMessage(sanitize(f"图层验证成功! 坐标系: {layer.crs().authid()}, 要素数量: {layer.featureCount()}"), tag=LOG_TAG, level=Qgis.Success)
        if layer.featureCount() == 0:
            QgsMessageLog.logMessage(sanitize("警告：图层要素数量为 0，这可能是由于 SQL 查询条件未匹配到任何数据，或者是 QGIS 解析子查询时出错。"), tag=LOG_TAG, level=Qgis.Warning)
            return failure("SQL_EMPTY_RESULT", "agent_a", "Error: 查询结果为空，未找到符合条件的矢量要素。")
    else:
        error_msg = layer.dataProvider().error().message() if layer.dataProvider() else "未知错误"
        return failure("DATABASE_FAILED", "agent_a", error_msg, provider_message=sanitize(error_msg),
                       target_layer=target_name, source_type="cloud_shp")
    
    return add_layer_to_project(layer, target_name)


def fetch_cloud_raster(sql_query: str, target_name: str, progress_callback=None) -> ToolResult:
    """从云端索引表查询路径，并下载加载栅格数据"""

    QgsMessageLog.logMessage("准备执行云端栅格索引查询", tag=LOG_TAG, level=Qgis.Info)
    try:
        # 连接数据库获取文件路径
        try:
            with connect_database() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql_query)
                    result = cursor.fetchone()
        except Exception as exc:
            return failure("DATABASE_FAILED", "agent_a", str(exc), target_layer=target_name,
                           source_type="cloud_raster")
        
        if not result or not result[0]:
            return failure("SQL_EMPTY_RESULT", "agent_a", "Error: 查询结果为空，未能找到对应的栅格文件路径。")
            
        dir_path = result[0] # 例如: data/dem/dem_guangdong.tif
        QgsMessageLog.logMessage(sanitize(f"获取到栅格路径: {dir_path}"), tag=LOG_TAG, level=Qgis.Info)
        
        # 假设服务器上搭建了简单的 HTTP 服务暴露该目录
        database_host = get_database_config()["host"]
        base_url = f"http://{database_host}/{dir_path.replace(chr(92), '/').lstrip('/')}"
        
        # 将文件下载到本地临时目录
        temp_dir = tempfile.gettempdir()
        base_filename = os.path.basename(dir_path)
        local_tif_path = os.path.join(temp_dir, base_filename)
        
        QgsMessageLog.logMessage(sanitize(f"开始从 {base_url} 下载数据..."), tag=LOG_TAG, level=Qgis.Info)
        resp = _get_with_retry(base_url, stream=True, timeout=10)
        if resp.status_code == 200:
            total_size = int(resp.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(local_tif_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_percent = int(downloaded_size * 100 / total_size)
                            progress_callback(f"{target_name} ({base_filename})", progress_percent)
                            
            if progress_callback:
                progress_callback(f"{target_name} ({base_filename})", 100)
                    
            # 尝试下载附属文件 (.tfw, .aux.xml, .cpg 等)
            extensions = ['.tfw', '.aux.xml', '.xml', '.vat.dbf', '.ovr', '.cpg']
            for ext in extensions:
                aux_url_1 = base_url[:-4] + ext 
                aux_local_path_1 = local_tif_path[:-4] + ext
                aux_url_2 = base_url + ext
                aux_local_path_2 = local_tif_path + ext
                
                for a_url, a_path in [(aux_url_1, aux_local_path_1), (aux_url_2, aux_local_path_2)]:
                    try:
                        aux_resp = _get_with_retry(a_url, stream=True, timeout=5)
                        if aux_resp.status_code == 200:
                            aux_filename = os.path.basename(a_url)
                            aux_total_size = int(aux_resp.headers.get('content-length', 0))
                            aux_downloaded_size = 0
                            
                            with open(a_path, 'wb') as f:
                                for chunk in aux_resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                                        aux_downloaded_size += len(chunk)
                                        if progress_callback and aux_total_size > 0:
                                            progress_percent = int(aux_downloaded_size * 100 / aux_total_size)
                                            progress_callback(f"{target_name} ({aux_filename})", progress_percent)
                                            
                            if progress_callback:
                                progress_callback(f"{target_name} ({aux_filename})", 100)
                    except:
                        pass
            
            QgsMessageLog.logMessage(sanitize(f"下载完成，准备加载: {local_tif_path}"), tag=LOG_TAG, level=Qgis.Info)
            return fetch_local_raster(local_tif_path, target_name)
        else:
            return failure("NETWORK_FAILED", "agent_a", f"HTTP {resp.status_code}",
                           http_status=resp.status_code, target_layer=target_name)
            
    except requests.RequestException as e:
        return failure("NETWORK_FAILED", "agent_a", str(e), retry_count=getattr(e, "attempts", 1),
                       target_layer=target_name)
    except Exception as e:
        return failure("DATA_ACCESS_FAILED", "agent_a", f"Error: 云端栅格获取失败 - {str(e)}")


@execution_boundary("agent_a", "DATA_ACCESS_FAILED")
def execute_fetch_task(source_type: str, query_params: Dict[str, Any], progress_callback=None) -> ToolResult:
    """
    Agent A 的核心执行函数：根据类型调用对应的数据获取函数。
    """
    target_name = query_params.get('target_name')

    if not target_name:
        return failure("MISSING_PARAMETER", "agent_a", "Error: 必须为新图层指定一个名称 (target_name)。")

    if source_type == 'local_shp':
        return fetch_local_file(query_params.get('file_path'), target_name)

    elif source_type == 'local_raster':
        return fetch_local_raster(query_params.get('file_path'), target_name)

    elif source_type == 'cloud_shp':
        sql_query = query_params.get('sql_query')
        if not sql_query:
            return failure("MISSING_PARAMETER", "agent_a", "Error: 缺少 sql_query 参数")
        return fetch_cloud_shp(sql_query, target_name)
        
    elif source_type == 'cloud_raster':
        sql_query = query_params.get('sql_query')
        if not sql_query:
            return failure("MISSING_PARAMETER", "agent_a", "Error: 缺少 sql_query 参数")
        return fetch_cloud_raster(sql_query, target_name, progress_callback)

    else:
        return failure("INVALID_PARAMETER", "agent_a", f"Error: 不支持或未知的 source_type '{source_type}'。")


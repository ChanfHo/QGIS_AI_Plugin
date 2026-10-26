from ..core.runtime_support import log_message, download_directory
from ..core.error_handling import failure, execution_boundary, sanitize, ToolResult
import os
import requests

from typing import Dict, Any

from .database import configure_qgis_uri, connect_database, get_database_config

from qgis._core import QgsRasterLayer
from qgis.core import Qgis, QgsVectorLayer, QgsProject, QgsMapLayer, QgsDataSourceUri

LOG_TAG = 'AI_AGENT_DEBUG'
NETWORK_MAX_ATTEMPTS = 3


def _get_with_retry(url: str, **kwargs):
    """Run a read-only network request with up to 3 attempts on failure."""
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
            log_message(
                sanitize('Remote request failed; preparing attempt {v0}: {v1}'.format(v0=attempt + 1, v1=last_error)),
                tag=LOG_TAG,
                level=Qgis.Warning,
            )
    error = requests.RequestException('Network request failed on {v0} consecutive attempts: {v1}'.format(v0=NETWORK_MAX_ATTEMPTS, v1=sanitize(str(last_error))))
    error.attempts = NETWORK_MAX_ATTEMPTS
    raise error

def add_layer_to_project(layer: QgsMapLayer, target_name: str) -> ToolResult:
    """Add a layer to the QGIS project and set its name."""
    if layer and layer.isValid():
        project = QgsProject.instance()

        # Remove old layers with the same name.
        existing_layers = project.mapLayersByName(target_name)
        if existing_layers:
            project.removeMapLayers([l.id() for l in existing_layers])

        # Add the layer.
        project.addMapLayer(layer)
        layer.setName(target_name)
        return "Success: Data '{v0}' was acquired and loaded.".format(v0=target_name)
    else:
        return failure("LAYER_LOAD_FAILED", "agent_a", "Error: Unable to load data or data is invalid.")


def fetch_local_file(file_path: str, target_name: str) -> ToolResult:
    """Load a local vector file."""
    if not file_path:
        return failure("MISSING_PARAMETER", "agent_a", 'Error: Missing file path parameter.')
    if not os.path.exists(file_path):
        # Deployment may require path mapping; assume the path is valid here.
        return failure("FILE_NOT_FOUND", "agent_a", 'Error: Local file not found: {v0}'.format(v0=file_path))

    # Use the QgsVectorLayer(uri, baseName, providerName) constructor.
    layer = QgsVectorLayer(file_path, target_name, 'ogr')
    if not layer.isValid():
        return failure("FILE_INVALID", "agent_a", 'The file is not recognized as valid vector data', target_layer=target_name)

    return add_layer_to_project(layer, target_name)


def fetch_local_raster(file_path: str, target_name: str) -> ToolResult:
    """Load a local raster file."""
    if not file_path: return failure("MISSING_PARAMETER", "agent_a", 'Error: Missing file path parameter.')
    if not os.path.exists(file_path): return failure("FILE_NOT_FOUND", "agent_a", 'Error: Local file not found: {v0}'.format(v0=file_path))

    # Load using QgsRasterLayer.
    layer = QgsRasterLayer(file_path, target_name)
    if layer.isValid():
        return add_layer_to_project(layer, target_name)
    return failure("FILE_INVALID", "agent_a", 'Error: The file exists but is not recognized as raster data.')


def fetch_cloud_shp(sql_query: str, target_name: str) -> ToolResult:
    """AI tool: load a layer directly from PostGIS using SQL."""
    log_message('Preparing a PostGIS vector query', tag=LOG_TAG, level=Qgis.Info)

    uri = QgsDataSourceUri()
    configure_qgis_uri(uri)
    
    # Use SQL as a source subquery with geometry column 'geom' and primary key 'gid'.
    uri.setDataSource("", f"({sql_query})", "geom", "", "gid")
    
    uri_string = uri.uri()
    log_message(sanitize('PostGIS layer source constructed'), tag=LOG_TAG, level=Qgis.Info)
    
    layer = QgsVectorLayer(uri_string, target_name, "postgres")
    
    if layer.isValid():
        log_message(sanitize('Layer validated! CRS: {v0}, feature count: {v1}'.format(v0=layer.crs().authid(), v1=layer.featureCount())), tag=LOG_TAG, level=Qgis.Success)
        if layer.featureCount() == 0:
            log_message(sanitize('Warning: Layer feature count is 0. The SQL conditions may match no data, or QGIS may have failed to parse the subquery.'), tag=LOG_TAG, level=Qgis.Warning)
            return failure("SQL_EMPTY_RESULT", "agent_a", 'Error: The query returned no rows; no matching vector features were found.')
    else:
        error_msg = layer.dataProvider().error().message() if layer.dataProvider() else 'Unknown error'
        return failure("DATABASE_FAILED", "agent_a", error_msg, provider_message=sanitize(error_msg),
                       target_layer=target_name, source_type="cloud_shp")
    
    return add_layer_to_project(layer, target_name)


def fetch_cloud_raster(sql_query: str, target_name: str, progress_callback=None) -> ToolResult:
    """Query paths from the cloud index, then download and load raster data."""

    log_message('Preparing a cloud raster index query', tag=LOG_TAG, level=Qgis.Info)
    try:
        # Connect to the database to get file paths.
        try:
            with connect_database() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql_query)
                    result = cursor.fetchone()
        except Exception as exc:
            return failure("DATABASE_FAILED", "agent_a", str(exc), target_layer=target_name,
                           source_type="cloud_raster")
        
        if not result or not result[0]:
            return failure("SQL_EMPTY_RESULT", "agent_a", 'Error: The query returned no rows; no matching raster file path was found.')
            
        dir_path = result[0] # Example: data/dem/dem_guangdong.tif.
        log_message(sanitize('Retrieved raster path: {v0}'.format(v0=dir_path)), tag=LOG_TAG, level=Qgis.Info)
        
        # Assume a simple HTTP service exposes this directory on the server.
        database_host = get_database_config()["host"]
        base_url = f"http://{database_host}/{dir_path.replace(chr(92), '/').lstrip('/')}"
        
        # Download files to a local temporary directory.
        temp_dir = download_directory()
        base_filename = os.path.basename(dir_path)
        local_tif_path = os.path.join(temp_dir, base_filename)
        
        log_message(sanitize('Starting download from {v0}...'.format(v0=base_url)), tag=LOG_TAG, level=Qgis.Info)
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
                    
            # Try downloading companion files (.tfw, .aux.xml, .cpg, etc.).
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
            
            log_message(sanitize('Download completed; preparing to load: {v0}'.format(v0=local_tif_path)), tag=LOG_TAG, level=Qgis.Info)
            return fetch_local_raster(local_tif_path, target_name)
        else:
            return failure("NETWORK_FAILED", "agent_a", f"HTTP {resp.status_code}",
                           http_status=resp.status_code, target_layer=target_name)
            
    except requests.RequestException as e:
        return failure("NETWORK_FAILED", "agent_a", str(e), retry_count=getattr(e, "attempts", 1),
                       target_layer=target_name)
    except Exception as e:
        return failure("DATA_ACCESS_FAILED", "agent_a", 'Error: Cloud raster acquisition failed - {v0}'.format(v0=str(e)))


@execution_boundary("agent_a", "DATA_ACCESS_FAILED")
def execute_fetch_task(source_type: str, query_params: Dict[str, Any], progress_callback=None) -> ToolResult:
    """Agent A execution: dispatch data acquisition according to source type."""
    target_name = query_params.get('target_name')

    if not target_name:
        return failure("MISSING_PARAMETER", "agent_a", 'Error: A name (target_name) is required for the new layer.')

    if source_type == 'local_shp':
        return fetch_local_file(query_params.get('file_path'), target_name)

    elif source_type == 'local_raster':
        return fetch_local_raster(query_params.get('file_path'), target_name)

    elif source_type == 'cloud_shp':
        sql_query = query_params.get('sql_query')
        if not sql_query:
            return failure("MISSING_PARAMETER", "agent_a", 'Error: Missing sql_query parameter')
        return fetch_cloud_shp(sql_query, target_name)
        
    elif source_type == 'cloud_raster':
        sql_query = query_params.get('sql_query')
        if not sql_query:
            return failure("MISSING_PARAMETER", "agent_a", 'Error: Missing sql_query parameter')
        return fetch_cloud_raster(sql_query, target_name, progress_callback)

    else:
        return failure("INVALID_PARAMETER", "agent_a", "Error: Unsupported or unknown source_type '{v0}'.".format(v0=source_type))

# Installation guide / 安装指南

[User manual](README.md) · [中文手册](README.zh-CN.md)

## English

### Prepare QGIS and a Qwen Key

Install QGIS 3.36 with Qt5/PyQt5. The reference environment is Windows, QGIS 3.36.1 and Python 3.9.18. QGIS supplies the PyQGIS, GDAL, Processing and Qt libraries used by the plugin. Prepare a personal Qwen API Key with access to `qwen-plus` and `text-embedding-v4`, together with available service credit.

### Install Python dependencies

Download `requirements.txt` from the [1.0.0 release](https://github.com/ChanfHo/QGIS_AI_Plugin/releases/tag/v1.0.0). Open the OSGeo4W Shell supplied with your QGIS installation. In the directory containing that file, run:

```bash
python -m pip install -r requirements.txt
python -c "import openai, httpx, langgraph, langchain_core, requests, numpy, psycopg2; print('Dependencies OK')"
```

When several Python installations are present, use QGIS's environment. The `bin/python-qgis.bat` launcher in the QGIS installation also runs commands with QGIS's Python configuration; launch it from that installation's `bin` directory and pass the same Python arguments. Dependencies installed into a separate Anaconda or system Python are separate from QGIS's packages.

Keep the QGIS-provided Qt, PyQGIS and GDAL versions. The reference installation includes NumPy 1.24.1 and psycopg2 2.9.3. If your QGIS Python lacks psycopg2, install a compatible `psycopg2-binary` into that same environment. [requirements.txt](requirements.txt) pins direct service dependencies; [requirements.lock](requirements.lock) records the reference Python dependency set.

### Install the plugin ZIP

1. Download `qgis_ai-1.0.0.zip` from the release assets.
2. Open QGIS → Plugins → Manage and Install Plugins → Install from ZIP.
3. Select the ZIP and install it, then enable QGIS-AI-Mapper.
4. Enter and verify your Key, then open the plugin panel.

The installable ZIP contains one `qgis_ai/` directory with `__init__.py`, `metadata.txt` and its supporting packages. GitHub's automatically generated Source code archives contain a repository snapshot. For manual source installation, open Settings → User Profiles → Open Active Profile Folder and place the plugin source in `python/plugins/qgis_ai/`. Keep all subdirectories together. When replacing an older installation manually, replace the complete plugin directory, then reload the plugin.

### Configure and start working

Choose Follow QGIS, Chinese or English. Each plugin load requires Key verification; during that load the verified Key is reused. Windows local saving uses DPAPI protection, and session-only use is available. The panel provides controls to configure, replace or clear the Key.

The bundled public connection reads remote data and style references. Terrain uses HTTP download. Local spatial analysis, styling and export run in QGIS. Connection settings and self-hosting are described in [DATABASE_ACCESS.md](DATABASE_ACCESS.md). Begin with the local river example in the [user manual](README.md#3-follow-complete-examples).

## 中文

### 准备QGIS和千问Key

安装配备Qt5／PyQt5的QGIS3.36。参考环境为Windows、QGIS3.36.1和Python3.9.18。插件使用QGIS提供的PyQGIS、GDAL、Processing和Qt运行库。准备个人千问APIKey，开通`qwen-plus`与`text-embedding-v4`权限，并保持服务额度可用。

### 安装Python依赖

从[1.0.0发布页面](https://github.com/ChanfHo/QGIS_AI_Plugin/releases/tag/v1.0.0)下载`requirements.txt`。打开QGIS安装附带的OSGeo4W Shell，进入文件所在目录，执行：

```bash
python -m pip install -r requirements.txt
python -c "import openai, httpx, langgraph, langchain_core, requests, numpy, psycopg2; print('Dependencies OK')"
```

多套Python共存时，使用QGIS对应的环境。也可以在QGIS安装目录的`bin`文件夹中启动`python-qgis.bat`，传入相同的Python命令参数。Anaconda或系统Python中的安装结果与QGIS环境相互独立。

保留QGIS提供的Qt、PyQGIS和GDAL版本。参考安装中NumPy为1.24.1、psycopg2为2.9.3；当前QGIS缺少psycopg2时，在同一环境安装兼容的`psycopg2-binary`。[requirements.txt](requirements.txt)固定直接服务依赖，[requirements.lock](requirements.lock)记录参考环境的Python依赖集合。

### 安装插件ZIP

1. 从发布附件下载`qgis_ai-1.0.0.zip`。
2. 打开QGIS“插件→管理并安装插件→从ZIP安装”。
3. 选择ZIP进行安装，启用QGIS-AI-Mapper。
4. 输入并验证个人Key，打开插件面板。

安装包内只有一个`qgis_ai/`根目录，包含`__init__.py`、`metadata.txt`和各业务子目录。GitHub自动生成的Source code压缩包是源码快照。手动安装源码时，通过“设置→用户配置→打开当前用户配置文件夹”找到配置目录，将完整插件放入`python/plugins/qgis_ai/`。手动替换旧安装时，应整体替换插件目录，再重新加载插件。

### 配置与开始使用

选择跟随QGIS、中文或English。每次加载插件重新验证Key，同一次加载内复用。Windows本地保存使用DPAPI保护，也可以仅在当前会话使用。面板提供配置、更换和清除Key的入口。

随包公共连接读取远程数据和样式参考，地形通过HTTP下载。本地分析、样式设置和导出由QGIS执行。连接及自建服务见[DATABASE_ACCESS.md](DATABASE_ACCESS.md#中文)，可从[中文手册](README.zh-CN.md#三完整使用示例)的本地河流示例开始。

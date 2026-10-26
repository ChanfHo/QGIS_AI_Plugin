# Data access / 数据访问

## English

### Public data connection

The plugin bundles `config/database_public.json` with the dedicated `qgis_ai_public_reader` account. Its address and password are public connection settings. Database permissions grant access to nine application tables: `china_admin_center`, `china_city`, `china_county`, `china_dem_index`, `china_province`, `highway`, `style_knowledge`, `water_line` and `water_polygon`, together with public PostGIS metadata.

The account has read access to the application tables. Plugin database connections also use read-only sessions. You can load these resources into QGIS, process them locally, set styles, build layouts and export images. Terrain is located through the database index and downloaded through HTTP. SSH access is not required.

The current data service supplies administrative features, roads, water features, terrain indexes and style references. Requests use the datasets available in that service. You can also work with local files or a self-hosted service. Remote datasets retain their own usage and redistribution terms.

### Self-hosted services

Set the following environment variables before starting QGIS to override the public connection:

|Variable|Purpose|
|---|---|
|`QGIS_AI_PUBLIC_DB_HOST`|Database host|
|`QGIS_AI_PUBLIC_DB_PORT`|Database port|
|`QGIS_AI_PUBLIC_DB_NAME`|Database name|
|`QGIS_AI_PUBLIC_DB_USER`|Read-only database user|
|`QGIS_AI_PUBLIC_DB_PASSWORD`|That user's password|
|`QGIS_AI_PUBLIC_DB_CONNECT_TIMEOUT`|Connection timeout in seconds|

Empty variables retain the bundled values. Configure SELECT permissions on the server for the public role. Use a compatible PostgreSQL/PostGIS schema matching [the table reference](knowledge_base/postgis_schema.txt); the style table uses 1024-dimensional vectors. Terrain index paths must be served over HTTP on the database host, as expected by the download adapter. Public mode uses only its public profile and `QGIS_AI_PUBLIC_DB_` overrides.

## 中文

### 公共数据连接

插件随包提供`config/database_public.json`，使用独立的`qgis_ai_public_reader`账号，其中的地址和密码属于公开连接配置。数据库授权该账号读取9张应用表：`china_admin_center`、`china_city`、`china_county`、`china_dem_index`、`china_province`、`highway`、`style_knowledge`、`water_line`和`water_polygon`，以及公开的PostGIS元数据。

该账号只读业务表，插件也使用只读数据库会话。用户可以加载资源，在本地分析、设置样式、制作布局和导出图片。地形通过数据库索引定位，经HTTP下载，无需SSH登录。

当前服务提供行政区划及行政中心、道路、水系、地形索引和样式参考，请求使用服务中已有的数据。也可以加载本地文件或连接自建服务。远程数据的使用及再分发遵循其自身条件。

### 自建服务

在启动QGIS前设置以下环境变量，覆盖公共连接配置：

|变量|用途|
|---|---|
|`QGIS_AI_PUBLIC_DB_HOST`|数据库主机|
|`QGIS_AI_PUBLIC_DB_PORT`|数据库端口|
|`QGIS_AI_PUBLIC_DB_NAME`|数据库名|
|`QGIS_AI_PUBLIC_DB_USER`|只读数据库账号|
|`QGIS_AI_PUBLIC_DB_PASSWORD`|该账号密码|
|`QGIS_AI_PUBLIC_DB_CONNECT_TIMEOUT`|连接超时秒数|

空变量保留随包值。在服务器端为公共角色授予SELECT权限。PostgreSQL／PostGIS表结构应与[表结构说明](knowledge_base/postgis_schema.txt)兼容，样式表使用1024维向量。地形索引中的路径需要通过数据库主机上的HTTP服务提供，供现有下载适配器读取。公共模式只读取公共配置和`QGIS_AI_PUBLIC_DB_`覆盖值。

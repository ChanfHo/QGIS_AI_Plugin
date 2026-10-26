# Credentials and security / 凭据与安全

## English

Configure your personal Qwen API Key through the plugin dialog. On Windows, local saving uses DPAPI protection. A new plugin load starts a new verification session. Share diagnostic information with personal Keys and private data removed.

`config/database_public.json` contains the intentionally public `qgis_ai_public_reader` connection. Server permissions enforce read access to application tables, and plugin connections use read-only sessions. Keep this public connection separate from service administration accounts. Terrain downloads use HTTP and require no SSH management credentials.

For security reports, contact the maintainer through the email in [plugin metadata](metadata.txt). Describe the affected version, reproduction steps and impact. Send credentials through neither public issues nor screenshots.

## 中文

通过插件配置窗口输入个人千问APIKey。Windows本地保存使用DPAPI保护，每次重新加载插件建立新的验证会话。分享诊断信息时，去除个人Key和私有数据。

`config/database_public.json`中的`qgis_ai_public_reader`是有意公开的连接。服务器授权限制业务表为只读，插件也使用只读会话。公共数据访问与服务管理账号分开使用。地形通过HTTP下载，无需SSH管理凭据。

安全问题请通过[插件元数据](metadata.txt)中的邮箱联系维护者，说明受影响版本、复现步骤和影响。公开Issue和截图中请去除凭据。

# Project Overview & Core Logic Guide (For AI)

## 1. 项目定位与目标

本项目是一个基于 **QGIS Python API** 与 **CAMEL 多智能体框架** 的 QGIS AI 插件，目标是：通过自然语言对话，让用户在 QGIS 中完成复杂 GIS 操作。

---

## 2. 核心功能模块

项目当前支持的主要能力包括：

- **数据获取**
  - 加载本地矢量/栅格数据
  - 从私有或预置数据源中检索常用数据（行政区划、路网等）

- **空间分析**
  - 缓冲区分析、叠加分析、裁剪等常见地理处理操作
  - 基于 QGIS `processing` 框架执行

- **样式管理**
  - 通过自然语言修改图层样式
  - 包括颜色、符号、分类渲染、分级渲染等

- **项目与布局管理**
  - 管理 QGIS 项目状态
  - 自动生成或调整地图布局

---

## 3. 总体逻辑架构

项目整体遵循以下执行链路：**用户输入 → 意图识别 → 多智能体分发 → JSON 指令生成 → QGIS API 执行**

具体流程如下：

1. **前端交互（PyQt）**
   - 用户在插件提供的聊天窗口中输入自然语言指令

2. **多智能体协作（CAMEL Framework）**
   - 后台线程根据任务类型，将请求分发给不同 Agent：
     - Agent A：数据获取（Data Fetching）
     - Agent B：空间分析（Spatial Analysis）
     - Agent C：样式管理（Style Management）
     - Agent D：项目管理（Project Management）
     - Agent E：布局管理（Layout Management）

3. **指令解析（LLM）**
   - 各 Agent 使用大模型（当前配置为 Qwen）, 将自然语言转化为标准化的 JSON 指令

4. **执行层（QGIS API）**
   - Python 代码解析 JSON
   - 通过模糊匹配定位目标图层或算法
   - 调用 QGIS API 执行真实操作

---

## 4. 核心代码文件速览（AI 阅读导航）

以下文件是理解和修改项目逻辑的关键入口：

- **`qgis_ai.py`**  
  插件入口文件  
  负责插件初始化、工具栏加载以及与 QGIS 主界面的连接。

- **`chat_box.py`**  
  UI 与调度核心  
  实现聊天窗口界面，并包含后台线程 `AgentsWorkgroupThread`，用于调度各智能体协作运行。

- **`workflow_graph.py`**
  LangGraph框架编排文件
  多智能体协作核心逻辑。  

- **`agents.py`**  
  智能体逻辑实现  
  定义各个 Agent（A/B/C/D/E）的工作流程，包括：
  - Prompt 构建
  - LLM 调用
  - JSON 解析
  - 执行函数触发

- **`agent_prompts.py`**  
  提示词仓库  
  存储所有 Agent 的 System Prompt，约束大模型：
  - 如何理解用户意图
  - 如何输出标准 JSON 结构

- **`spatial_process.py`**  
  空间分析执行器  
  接收 Agent B 的参数，调用 QGIS `processing` 模块执行地理分析。

- **`style_management.py`**  
  样式渲染执行器  
  接收 Agent C 的指令，操作 QGIS 渲染体系（如 `QgsSingleSymbolRenderer`）修改图层样式。

- **`fetch_data.py`**  
  数据加载执行器  
  接收 Agent A 的指令， 处理本地路径或网络请求，并将数据加载为 QGIS 图层。

---

## 5. 使用说明（给 AI）

- 当需求涉及 **UI 或调度流程**，优先阅读 `chat_box.py`
- 当需求涉及 **意图解析或智能体行为**，优先阅读 `agents.py` 与 `agent_prompts.py`
- 当需求涉及 **具体 GIS 操作**，定位到对应执行器文件：
  - 空间分析 → `spatial_process.py`
  - 样式控制 → `style_management.py`
  - 数据加载 → `fetch_data.py`

本文件用于帮助 AI **快速理解项目边界与核心逻辑，并定位应优先阅读的代码文件**。

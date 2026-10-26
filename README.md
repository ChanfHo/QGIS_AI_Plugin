# QGIS-AI-Mapper

[English](README.md) | [简体中文](README.zh-CN.md)

**Describe your map in natural language and build it inside QGIS.**

QGIS-AI-Mapper brings a conversational mapping assistant to QGIS Desktop. Ask a question, adjust a layer, or describe a complete map: the plugin interprets your request, uses the layers and fields in your current project, and carries out data loading, spatial processing, styling and layout operations. Results appear as QGIS layers and print layouts that you can inspect, edit and save with the tools you already use.

|How you want to work|What to ask for|
|---|---|
|Simple chat|Ask for an explanation, terminology or help planning your work|
|A single operation|Load a boundary, change a river's color, create a buffer or update a map title|
|A compound mapping task|Combine data acquisition, processing, styling and layout into one request|

[Download 1.0.0](https://github.com/ChanfHo/QGIS_AI_Plugin/releases/tag/v1.0.0) · [Installation guide](SETUP.md) · [Data access](DATABASE_ACCESS.md) · [Report an issue](https://github.com/ChanfHo/QGIS_AI_Plugin/issues)

## 1. Install and get ready

### Environment

Use **QGIS 3.36 with Qt5/PyQt5**. The reference installation is Windows with QGIS 3.36.1 and Python 3.9.18. The plugin runs inside QGIS and uses its PyQGIS, Processing, GDAL and Qt libraries.

You also need a personal **Qwen API Key**, access to Qwen services, and the Python packages listed in [requirements.txt](requirements.txt). Text interpretation and planning use `qwen-plus`; style-reference retrieval uses `text-embedding-v4`. Enable these models for your account and keep sufficient service credit for your requests. Voice input is disabled in version 1.0.0.

### Installation

1. Download **`qgis_ai-1.0.0.zip`** and **`requirements.txt`** from [Releases](https://github.com/ChanfHo/QGIS_AI_Plugin/releases/tag/v1.0.0). Select the named plugin ZIP in the release assets.
2. Open the **OSGeo4W Shell supplied with your QGIS installation**. Change to the folder containing the downloaded requirements file and install the dependencies:

   ```bash
   python -m pip install -r requirements.txt
   python -c "import openai, httpx, langgraph, langchain_core, requests, numpy, psycopg2; print('Dependencies OK')"
   ```

   These packages must be available to QGIS's Python. See [SETUP.md](SETUP.md) for the QGIS Python launcher and manual source installation.
3. Start QGIS and open **Plugins → Manage and Install Plugins → Install from ZIP**. Select the plugin ZIP, install it, and enable **QGIS-AI-Mapper**.
4. Enter your Qwen API Key in the configuration dialog, verify it, and open the plugin from its toolbar icon or Plugins menu.

The configuration dialog provides masked input, show/hide, verification, saving, replacement and clearing. Verification enables chat and task execution. Each plugin load starts a new Key verification session; another message, a new task or reopening the panel uses the verified Key from that session. On Windows, local Key saving uses DPAPI protection. The panel's **Configure / change API Key** button opens the dialog again.

### Data and language

Start with your own QGIS project or request data through the bundled **public read-only connection**. Available resources include administrative boundaries and centers, roads, rivers, terrain indexes and cartographic style references. Terrain files are downloaded through HTTP. Users can read the public data, process it locally and create maps; no server login is needed. [DATABASE_ACCESS.md](DATABASE_ACCESS.md) explains the connection and self-hosted services.

Select **Follow QGIS / 中文 / English** in the panel or Key dialog. You can also ask for a particular reply language, such as “Please answer in English.” Keep actual layer names, field names and paths as they appear in your project, including Chinese identifiers in an English request.

## 2. Work in the conversation panel

### Simple chat

Use the panel for explanations and short questions as well as mapping. An ordinary conversational request receives a text answer. For example:

```text
Hello! Briefly introduce yourself.
Explain the difference between a general map and a thematic map, without changing my project.
What should I consider when choosing colors for a river map? Please only explain.
```

When you want an explanation, state that directly. When you want to change the project, name the operation and its target.

### Single-step tasks and adjustments

Single-step requests let you build a map gradually or refine an existing result. Each line below is a separate request:

```text
Load the provincial boundary of 广西壮族自治区 and name it 广西壮族自治区省界.
Set the line color of 示例河流 to blue and the line width to 0.6 mm.
Create a 100-meter buffer around 示例河流 and name it 河流缓冲区.
Clip 湖北省高速公路 to the boundary of 武汉市 and name the output 武汉市高速公路.
Reproject 武汉市高速公路 to EPSG:4547.
Change the title of the River map layout to River buffer analysis.
```

Copy loaded layer names from QGIS's Layers panel. For thematic rendering or labels, include the actual field name. For a buffer, use a suitable projected coordinate system with meter units. When several layouts exist, identify the one you want to adjust by name.

Each message is interpreted using the current project and its layers. A self-contained instruction such as “Set 示例河流 to dark blue” gives a clear target. Ordinary chat messages do not form a persistent conversation memory; state the context needed by each request.

### Multi-step tasks

A compound request expresses an intended result and its requirements. The plugin displays a plan and executes steps in order, making earlier outputs available to later steps. You can combine loading, clipping, rendering and page requirements in one message.

|Capability|What you can request|
|---|---|
|Acquire data|Local vector/raster files; available public administrative, road, river and terrain data|
|Process layers|QGIS Processing operations such as clipping, buffering and reprojection|
|Style a map|Symbols, line/fill properties, categorized or graduated rendering, labels and raster styles|
|Arrange a layout|A page, map, title, legend, scale bar and north arrow; view adjustments|
|Export|Save a print layout as PNG through the output dialog|

Follow the plan and step progress in the panel. Open the Layers panel and print layout to inspect the result; they remain normal QGIS objects for further editing.

## 3. Follow complete examples

### Example A: local river buffer map

Use the included [synthetic river line](examples/local_river.geojson) to practice with a small dataset. Download the file, drag it into QGIS, and rename the layer **示例河流**. Its coordinate system is EPSG:3857, with meter units.

Send the following as one message:

```text
Create a 100-meter buffer around 示例河流 and name the result 河流缓冲区.
Style 河流缓冲区 with a pale-blue fill and a blue outline.
Style 示例河流 as a dark-blue line with a width of 0.6 mm.
Zoom to 河流缓冲区.
Create an A4 landscape print layout titled River buffer map.
Add a legend, scale bar and north arrow, then export the layout as PNG.
```

The task combines spatial analysis, two layer styles, view adjustment, layout creation and export. Select legend entries when the selection dialog opens, then choose a PNG destination in the save dialog. The project will contain the original river, its buffer and a print layout named **River buffer map**.

To refine the result, send a single-step request:

```text
Set the fill of 河流缓冲区 to pale yellow and its outline to orange.
```

You can also edit symbols or move layout elements manually in QGIS. The synthetic line is a practice dataset rather than a real river survey.

### Example B: a regional general map

Combine public data retrieval with a complete map layout. Begin with a new project and request:

```text
Create a general map of 广西壮族自治区.
Load its provincial boundary, prefecture-level city boundaries,
city administrative centers and river lines.
Use a light background, subtle gray administrative boundaries and blue rivers.
Label the city administrative centers with their names.
Set the map extent to 广西壮族自治区.
Create an A4 landscape layout titled 广西壮族自治区普通地图,
with a legend, scale bar and north arrow, and export it as PNG.
```

The plugin separates the data requests, prepares the layers, applies their styles and labels, then creates the layout. Administrative identifiers stay in Chinese to match the public datasets. Select the layers and categories you want in the legend dialog. Save the QGIS project after export to retain your layers, symbology and layout.

### Example C: a thematic map from your own data

Load a polygon dataset and confirm the numeric field to map. State the layer and field names, classification method, number of classes, color ramp and layout title.

For a layer named **区县统计** containing a numeric field named **population**, send:

```text
Create a population thematic map from 区县统计 using the population field.
Use five quantile classes with a light-to-dark orange color ramp
and thin white boundaries between polygons.
Zoom to 区县统计 and create an A4 portrait layout titled Population by county.
Add a legend, scale bar and north arrow, then export the layout as PNG.
```

This task uses the values already present in your dataset. Apply the same pattern to other indicators by specifying their actual fields and meaningful titles.

### Write clearer requests

Describe the **target, operation and result** together. For loading, give the path or administrative region. For processing, identify input layers and distance units. For styling, name the layer, field and desired appearance. For layouts, include paper size, orientation, title and export format.

For example, “Clip 湖北省高速公路 to 武汉市 and name the result 武汉市高速公路” identifies the input, extent and output in one sentence. For a full map, state the overall subject first, followed by data, styling and page requirements.

## 4. Controls, recovery and help

### Everyday controls

|Control|Action|
|---|---|
|Enter / Send|Submit the message|
|Shift+Enter|Insert a line break|
|Thinking panel|Expand or collapse the explanation|
|Step progress|Follow the current task and completed steps|
|Stop|Stop subsequent execution; completed changes remain in the project|
|Key configuration|Verify, replace or clear the current Key|
|Language selector|Choose English, Chinese or the QGIS language|

An active model or network request may finish before Stop takes effect. Save your QGIS project to retain the map work you want to keep.

### Correct a failed step and continue

An error card identifies the affected step and provides available recovery actions. For a missing layer, field, path or parameter, supply corrected information in the input box and continue. For a temporary connection problem, use retry. The active task retains its completed steps while you repair the failed operation.

For example, if a buffer step cannot find the road layer, check its name in QGIS and reply:

```text
Continue this step using 湖北省高速公路 as the input layer,
with a distance of 100 meters and output name 公路缓冲区.
```

To replace a pending task, use the error card's new-task action or start a message with **`New task:`**. Recovery state belongs to the current plugin process; after restarting QGIS, start a new task from the saved project.

### Troubleshooting

|Situation|Next step|
|---|---|
|Missing Python module|Install requirements in QGIS's Python environment and restart QGIS|
|Key verification fails|Check the Key, service balance, model access and network|
|Chat works but style retrieval fails|Check access to `text-embedding-v4`|
|Remote data cannot be loaded|Check the network and data service, or load local data|
|Layer or field cannot be found|Use the exact name shown in QGIS|
|Buffer distances look wrong|Check the input CRS and processing units|
|Key dialog returns after reload|Verify the Key for the new plugin session|
|Voice control is disabled|Use text input in version 1.0.0|

See [SETUP.md](SETUP.md) for installation and [DATABASE_ACCESS.md](DATABASE_ACCESS.md) for connections. Open an [issue](https://github.com/ChanfHo/QGIS_AI_Plugin/issues) with your plugin/QGIS/Python versions, request, reproduction steps and error details. Remove personal Keys and private data before sharing diagnostics; see [SECURITY.md](SECURITY.md).

Distributed under **GPL-2.0-or-later**. See [LICENSE](LICENSE), [NOTICE.md](NOTICE.md) and [release notes](RELEASE_NOTES.md). External datasets and dependencies retain their respective licenses and usage terms.

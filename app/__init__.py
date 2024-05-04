import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from graphviz import Digraph
from loguru import logger

from .config import settings
from .crawler import MODE, Export, crawler
from .utils import repeat_every


@repeat_every(
    seconds=settings.refresh_seconds,
    wait_first=False,
    raise_exceptions=True,
)  # every two minutes
async def refresh_map():
    try:
        logger.info("Refreshing map")
        await crawler.refresh()
        logger.info("Refreshing map ok")
    except Exception as ex:
        logger.warning(f"Map refresh exc: {ex!r}")


@asynccontextmanager
async def init(ap: FastAPI):
    logger.info("Staring init")
    async with crawler:
        logger.info(f"Starting refresh task every {settings.refresh_seconds} seconds")
        refresh_task = asyncio.create_task(refresh_map())
        try:
            yield
        except Exception as ex:
            logger.warning(f"Shutdown exception: {ex}")
            # raise # ??


app = FastAPI(lifespan=init)


base_resp = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <title>Network</title>
    <script
      type="text/javascript"
      src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"
    ></script>
    <style type="text/css">
      #mynetwork {
        width: 1200px;
        height: 800px;
        border: 2px solid lightgray;
      }
    </style>
  </head>
  <body>
    <div id="mynetwork"></div>
    <script type="text/javascript">
      raw_data = {data};
    </script>
    <script type="text/javascript">
      // create a network
      var container = document.getElementById("mynetwork");
      var data = {
        nodes: new vis.DataSet(raw_data["nodes"]),
        edges: new vis.DataSet(raw_data["edges"]),
      };
      var options = {
        physics: {
            solver: "repulsion",
            repulsion: {
                nodeDistance: 100,
                springLength: 200,
            },
            barnesHut: {
                gravitationalConstant: -500,
                springLength: 500,
                springConstant: 0.001
            }
        }
      };
      var network = new vis.Network(container, data, options);
    </script>
  </body>
</html>
"""


@app.get("/")
async def index(mode: MODE = "path") -> HTMLResponse:
    data = crawler.export(mode).model_dump_json(by_alias=True)
    resp = base_resp.replace("{data}", data)

    return HTMLResponse(content=resp)


@app.get("/graphviz")
async def get_graphviz(mode: MODE = "peers"):
    base_graph = Digraph(
        format="png",
    )
    base_graph.attr(compound="true")
    base_graph.attr("edge", dir="both")

    peers = crawler.export(mode)  # json.loads(await crawl("peers"))

    clusters = {cluster: Digraph(f"cluster_{cluster}", comment=cluster) for cluster in peers.clusters}
    logger.info(f"{peers.clusters = }")

    for node in peers.nodes:
        node_shape = "ellipse"
        node_color = "black"
        bp = node.buildplatform
        if bp == "windows":
            node_shape = "box"
            node_color = "red"
        if bp == "darwin":
            node_shape = "diamond"
            node_color = "green"
        if bp == "linux":
            node_shape = "cylinder"
            node_color = "blue"

        graph = base_graph
        if node.cluster:
            graph = clusters[node.cluster]

        graph.attr("node", shape=node_shape, color=node_color)
        graph.node(str(node.id), f"{node.buildversion} {node.label}")

    for cluster in clusters.values():
        cluster.attr(label=cluster.comment)
        base_graph.subgraph(cluster)

    for edge in peers.edges:
        dir = None
        color = None
        if mode == "peers":
            match edge.arrows:
                case None:
                    dir = "forward"
                    color = "red"
                case "to;forward":
                    dir = "both"

        base_graph.edge(str(edge.to), str(edge.from_), dir=dir, color=color)

    return StreamingResponse(
        BytesIO(base_graph.pipe(format="png")),
        media_type="image/png",
    )


@app.get("/state")
async def state(mode: MODE = "path") -> Export:
    return crawler.export(mode)


@app.get("/refresh")
async def refresh(mode: MODE = "path") -> Export:
    await crawler.refresh()
    return crawler.export(mode)


@app.get("/info")
async def info() -> PlainTextResponse:
    return PlainTextResponse(crawler.crawling_status())


def start():
    """Launched with `poetry run start` at root level"""
    uvicorn.run("my_package.main:app", host="0.0.0.0", port=8000, reload=True)

from typing import Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .crawler import MODE, crawl
from loguru import logger

app = FastAPI()


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
    data = await crawl(mode)
    logger.trace(data)
    resp = base_resp.replace("{data}", data)

    return HTMLResponse(content=resp)


import json
import graphviz
import io


@app.get("/graphviz")
async def get_graphviz():
    graph = graphviz.Digraph(
        format="png",
    )
    peers = json.loads(await crawl("peers"))
    graph.attr("edge", dir="both")

    for node in peers["nodes"]:
        node_shape = "ellipse"
        node_color = "black"
        bp = node["buildplatform"]
        if bp == "windows":
            node_shape = "box"
            node_color = "red"
        if bp == "darwin":
            node_shape = "diamond"
            node_color = "green"
        if bp == "linux":
            node_shape = "cylinder"
            node_color = "blue"
        graph.attr("node", shape=node_shape, color=node_color)
        graph.node(str(node["id"]), f"{node['buildversion']} {node['label']}")

    for edge in peers["edges"]:
        graph.edge(str(edge["to"]), str(edge["from"]))

    return StreamingResponse(
        io.BytesIO(graph.pipe(format="png")), media_type="image/png"
    )

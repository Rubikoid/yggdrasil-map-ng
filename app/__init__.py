from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from .crawler import crawl

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
async def index() -> HTMLResponse:
    data = await crawl()
    resp = base_resp.replace("{data}", data)

    return HTMLResponse(content=resp)

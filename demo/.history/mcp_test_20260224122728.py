from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio


mcp_client = MultiServerMCPClient(
    {
        "amap-maps": {
              "command": "cmd",
              "args": [
                "/c",
                "npx",
                "-y",
                "@amap/amap-maps-mcp-server"
              ],
              "env": {
                "AMAP_MAPS_API_KEY": "b391959983380e4a4dc5dd6d5a2131da"
              },
              'transport': 'stdio'
            }
    }
)


async def get_server_tools():
    tools = await mcp_client.get_tools()
    print(f"加载了{len(tools)}: {[t.name for t in tools]}")


# if __name__ == "__main__":
tools = await mcp_client.get_tools()
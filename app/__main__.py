import asyncio
from .crawler import crawl


async def main():
    res = await crawl()
    print(res)


if __name__ == "__main__":
    asyncio.run(main())

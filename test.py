import asyncio
import time

async def task1():
    print("Task 1 starts")
    await asyncio.sleep(2)  # Non-blocking sleep
    print("Task 1 ends")

async def task2():
    print("Task 2 starts")
    await asyncio.sleep(5)  # Non-blocking sleep
    print("Task 2 ends")

async def main():
    await asyncio.gather(task1(), task2())

asyncio.run(main())

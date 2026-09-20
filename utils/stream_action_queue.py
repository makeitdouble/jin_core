import asyncio


class StreamActionQueue:
    """Run a message's actions in order without holding its visible text."""

    def __init__(self):
        self.tasks = []

    def submit(self, callback):
        previous = self.tasks[-1] if self.tasks else None

        async def run():
            if previous is not None:
                await previous
            return await callback()

        self.tasks.append(asyncio.create_task(run()))

    async def drain(self):
        if self.tasks:
            await self.tasks[-1]

    async def close(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

from abc import ABC, abstractmethod

class BaseNode(ABC):

    @abstractmethod
    async def run(
            self,
            state,
            context,
    ):
        pass
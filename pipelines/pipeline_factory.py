from pipelines.brain_pipeline import (
    BrainPipeline,
)

from pipelines.agent_pipeline import (
    AgentPipeline,
)

from utils.language import (
    contains_cyrillic,
)


def get_pipeline(
        user_text: str,
):

    if contains_cyrillic(
            user_text
    ):

        return AgentPipeline()

    return BrainPipeline()

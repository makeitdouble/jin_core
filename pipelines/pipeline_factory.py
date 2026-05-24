from pipelines.translation_pipeline import (
    TranslationPipeline,
)

from pipelines.service_pipeline import (
    ServicePipeline,
)

from pipelines.brain_pipeline import (
    BrainPipeline,
)

from utils.language import (
    contains_cyrillic,
)
from pipelines.agent_pipeline import (
    AgentPipeline,
)

def get_pipeline(
        user_text: str,
):

    if contains_cyrillic(
            user_text
    ):

        return AgentPipeline()

    return BrainPipeline()

def get_pipeline_old(
    user_text: str,
):



    if contains_cyrillic(user_text):

        return TranslationPipeline()

    return ServicePipeline()

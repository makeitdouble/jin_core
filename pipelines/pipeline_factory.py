import config

from pipelines.translation_pipeline import (
    TranslationPipeline,
)

from pipelines.service_pipeline import (
    ServicePipeline,
)

from pipelines.bypass_pipeline import (
    BypassPipeline,
)

from utils.language import (
    contains_cyrillic,
)


def get_pipeline(
    user_text: str,
):

    if config.BYPASS_BRAIN:

        return BypassPipeline()

    if contains_cyrillic(user_text):

        return TranslationPipeline()

    return ServicePipeline()

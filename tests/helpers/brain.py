from types import SimpleNamespace


def brain_runtime_config():
    return {
        "runtime_id": "brain",
        "label": "brain",
        "context_window": 8192,
        "log_method": "log_brain",
        "runtime_actions": {
            "CAN_WEB_SEARCH": True,
            "CAN_USE_ASSETS": True,
            "CAN_SAVE_DELAYED_MEMORY": True,
            "CAN_SAVE_ACTIVE_MEMORY": True,
        },
    }


def brain_context_stub():
    return SimpleNamespace(
        logger=SimpleNamespace(),
        clients={"brain": object()},
        runtime_search_queries=[],
        runtime_search_calls=[],
        runtime_asset_results=[],
        runtime_delayed_memory_results=[],
        runtime_loaded_skills=[],
        runtime_action_events=[],
    )


async def async_noop():
    return None

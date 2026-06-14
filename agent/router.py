class Router:

    PLAN_INDEX_KEY = "current_plan_index"

    @classmethod
    def next(
            cls,
            state,
            current,
    ):

        if current == "planner":
            if not state.current_plan:
                return "END"

            state.metadata[cls.PLAN_INDEX_KEY] = 0

            return state.current_plan[0]

        current_index = state.metadata.get(
            cls.PLAN_INDEX_KEY
        )

        if (
                not isinstance(
                    current_index,
                    int,
                )
                or current_index >= len(
                    state.current_plan
                )
                or state.current_plan[current_index] != current
        ):
            if current not in state.current_plan:
                return "END"

            current_index = state.current_plan.index(
                current
            )

        next_index = current_index + 1

        if next_index >= len(
            state.current_plan
        ):
            state.metadata.pop(
                cls.PLAN_INDEX_KEY,
                None,
            )

            return "END"

        state.metadata[cls.PLAN_INDEX_KEY] = next_index

        return state.current_plan[
            next_index
        ]

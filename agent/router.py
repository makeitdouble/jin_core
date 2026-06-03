class Router:

    @staticmethod
    def next(
            state,
            current,
    ):

        if current == "planner":
            if not state.current_plan:
                return "END"

            return state.current_plan[0]

        if current in state.current_plan:
            current_index = state.current_plan.index(
                current
            )

            next_index = current_index + 1

            if next_index >= len(
                state.current_plan
            ):
                return "END"

            return state.current_plan[
                next_index
            ]

        return "END"

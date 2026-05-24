class Router:

    def next(
            self,
            state,
            current,
    ):

        if current == "planner":
            return "translator"

        if current == "translator":
            return "brain"

        if current == "brain":
            return "validator"

        if current == "validator":

            if state.final_answer:
                return "END"

            return "END"

        return "END"
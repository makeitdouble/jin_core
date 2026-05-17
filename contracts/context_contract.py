from datetime import datetime
from xml.sax.saxutils import escape

class ContextContract:

    def __init__(
        self,
        user_input,
        original_user_input="",
        compressed_history="",
        system_state="ACTIVE",
    ):

        self.user_input = escape(user_input)
        self.original_user_input = escape(original_user_input)
        self.compressed_history = escape(compressed_history)
        self.system_state = escape(system_state)

        self.timestamp = datetime.now().isoformat()

    def to_xml(self):

        return f"""
<CONTEXT_INTERFACE>

    <SYSTEM_IDENTITY>

        You are JIN Core Engine.

        You operate as an isolated cognition node inside a layered runtime system.

        Your task:
        - analyze user intent
        - produce coherent responses
        - maintain stable personality
        - avoid hallucinations
        - avoid meta-commentary
        - avoid corporate tone

        Output plain natural english text only.

    </SYSTEM_IDENTITY>


    <RUNTIME_STATE>

        {self.system_state}

    </RUNTIME_STATE>


    <TIMESTAMP>

        {self.timestamp}

    </TIMESTAMP>


    <COMPRESSED_HISTORY>

        {self.compressed_history}

    </COMPRESSED_HISTORY>


    <ACTIVE_USER_INPUT>

        {self.user_input}

    </ACTIVE_USER_INPUT>


    <ORIGINAL_USER_INPUT>

        {self.original_user_input}

    </ORIGINAL_USER_INPUT>

</CONTEXT_INTERFACE>
""".strip()

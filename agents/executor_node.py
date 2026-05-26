import asyncio
import contextlib
import os
import sys
import tempfile

from agents.base_node import BaseNode


class ExecutorNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        if not state.generated_code:
            state.execution_error = (
                "No generated code."
            )
            return

        with tempfile.NamedTemporaryFile(
                suffix=".py",
                delete=False,
                mode="w",
                encoding="utf-8",
        ) as temp:

            temp.write(
                state.generated_code
            )

            temp_path = temp.name

        try:

            process = (
                await asyncio.create_subprocess_exec(
                    sys.executable,
                    temp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            )

            stdout, stderr = (
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=20,
                )
            )

            state.execution_output = (
                stdout.decode()
            )

            error = stderr.decode().strip()

            state.execution_error = error

        except Exception as e:

            state.execution_error = str(e)

        finally:

            with contextlib.suppress(OSError):
                os.remove(temp_path)

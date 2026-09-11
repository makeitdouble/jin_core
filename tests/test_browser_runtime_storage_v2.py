import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_STORAGE_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-storage.js"
)

@unittest.skipUnless(shutil.which("node"), "node is required")
class BrowserRuntimeStorageV2Tests(unittest.TestCase):

    def test_migration_clear_and_multitab_contract(self):
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const source = fs.readFileSync(
              {str(RUNTIME_STORAGE_JS)!r},
              "utf8"
            );

            const LIVE = "jin.liveRuntimeMemory.v2";
            const CHECKPOINT = "jin.sessionCheckpoint.v2";
            const LEGACY_SAVE = "jin.latestSavedSessionSnapshot.v1";
            const LEGACY_RUNTIME = "jin.latestSavedRuntimeMemory.v1";
            const legacySessionKey = id => `jin.latestRuntimeMemory.${{id}}.v1`;
            let nextId = 0;

            class MemoryStorage {{
              constructor(seed = {{}}) {{
                this.values = new Map(
                  Object.entries(seed).map(([key, value]) => [
                    key,
                    typeof value === "string" ? value : JSON.stringify(value),
                  ])
                );
                this.failKey = null;
              }}

              get length() {{
                return this.values.size;
              }}

              key(index) {{
                return Array.from(this.values.keys())[index] ?? null;
              }}

              getItem(key) {{
                return this.values.has(key) ? this.values.get(key) : null;
              }}

              setItem(key, value) {{
                if (key === this.failKey) {{
                  throw new Error("forced storage failure");
                }}
                this.values.set(key, String(value));
              }}

              removeItem(key) {{
                this.values.delete(key);
              }}
            }}

            function boot(localStorage, sessionSeed = {{}}, anonymous = false) {{
              const sessionStorage = new MemoryStorage(sessionSeed);
              const window = {{
                localStorage,
                sessionStorage,
                crypto: {{
                  randomUUID: () => `runtime-${{++nextId}}`,
                }},
                JinRuntime: {{
                  anonymousMode: {{
                    shouldIsolateStorage: () => anonymous,
                    isEnabled: () => anonymous,
                  }},
                }},
              }};
              window.window = window;
              const context = vm.createContext({{
                window,
                console,
                Date,
                JSON,
                String,
                Number,
                Boolean,
                Object,
                Array,
                Set,
                Map,
                Math,
                RegExp,
                Promise,
                Uint8Array,
              }});
              vm.runInContext(source, context);
              return {{
                storage: window.JinRuntime.storage,
                sessionStorage,
              }};
            }}

            function parse(storage, key) {{
              const value = storage.getItem(key);
              return value === null ? null : JSON.parse(value);
            }}

            // A copied/reloaded sessionStorage value is never a bootstrap source.
            {{
              const local = new MemoryStorage({{
                [CHECKPOINT]: {{
                  version: 2,
                  state: "checkpoint",
                  session_id: "durable-session",
                  runtime_memory: "durable frame",
                }},
              }});
              const page = boot(local, {{
                [LIVE]: {{runtime_memory: "copied frame"}},
              }});
              assert.strictEqual(page.storage.readLatestRuntimeMemory(), null);
              assert.strictEqual(
                page.storage.readSessionCheckpoint().runtime_memory,
                "durable frame"
              );
              page.storage.writeLatestRuntimeMemory({{runtime_memory: "live"}});
              assert.strictEqual(
                parse(page.sessionStorage, LIVE).runtime_memory,
                "live"
              );
              assert.strictEqual(local.getItem(LIVE), null);
            }}

            // The common legacy SAVE owns migration; only its exact L1 may join it.
            {{
              const local = new MemoryStorage({{
                [LEGACY_SAVE]: {{
                  session_id: "session-a",
                  previous_session_id: "session-prev",
                  saved_at: "2026-08-28T01:00:00.000Z",
                  session_snapshot: {{dialogue: ["saved"]}},
                }},
                [LEGACY_RUNTIME]: {{
                  session_id: "session-b",
                  runtime_memory: "wrong owner",
                }},
                [legacySessionKey("session-a")]: {{
                  session_id: "session-a",
                  runtime_memory: "matching frame",
                  runtime_memory_updates: 7,
                }},
              }});
              const page = boot(local, {{
                [legacySessionKey("session-z")]: {{
                  session_id: "session-z",
                  runtime_memory: "session-only stale frame",
                }},
              }});
              const checkpoint = page.storage.readSessionCheckpoint();
              assert.strictEqual(checkpoint.version, 2);
              assert.strictEqual(checkpoint.state, "checkpoint");
              assert.strictEqual(checkpoint.session_id, "session-a");
              assert.strictEqual(checkpoint.runtime_memory, "matching frame");
              assert.strictEqual(checkpoint.runtime_memory_updates, 7);
              assert.deepStrictEqual(
                JSON.parse(JSON.stringify(checkpoint.session_snapshot)),
                {{dialogue: ["saved"]}}
              );
              assert.strictEqual(local.getItem(LEGACY_SAVE), null);
              assert.strictEqual(local.getItem(LEGACY_RUNTIME), null);
              assert.strictEqual(local.getItem(legacySessionKey("session-a")), null);
              assert.strictEqual(
                page.sessionStorage.getItem(legacySessionKey("session-z")),
                null
              );
            }}

            // A self-contained saved runtime is the sole no-common fallback.
            {{
              const local = new MemoryStorage({{
                [LEGACY_RUNTIME]: {{
                  session_id: "standalone-session",
                  saved_at: "2026-08-28T02:00:00.000Z",
                  runtime_memory: "standalone frame",
                }},
              }});
              const checkpoint = boot(local).storage.readSessionCheckpoint();
              assert.strictEqual(checkpoint.session_id, "standalone-session");
              assert.strictEqual(checkpoint.runtime_memory, "standalone frame");
            }}

            // Orphan per-session records are cleared, never selected by freshness.
            {{
              const local = new MemoryStorage({{
                [legacySessionKey("orphan")]: {{
                  session_id: "orphan",
                  saved_at: "2099-01-01T00:00:00.000Z",
                  runtime_memory: "must not restore",
                }},
              }});
              const page = boot(local);
              assert.strictEqual(page.storage.readSessionCheckpoint(), null);
              assert.strictEqual(
                page.storage.readSessionCheckpointRecord().state,
                "cleared"
              );
              assert.strictEqual(local.getItem(legacySessionKey("orphan")), null);
            }}

            // Failed v2 persistence leaves every legacy source available to retry.
            {{
              const local = new MemoryStorage({{
                [LEGACY_SAVE]: {{session_id: "retry-session"}},
                [LEGACY_RUNTIME]: {{
                  session_id: "retry-session",
                  runtime_memory: "retry frame",
                }},
              }});
              local.failKey = CHECKPOINT;
              const page = boot(local);
              assert.strictEqual(page.storage.readSessionCheckpoint(), null);
              assert.notStrictEqual(local.getItem(LEGACY_SAVE), null);
              assert.notStrictEqual(local.getItem(LEGACY_RUNTIME), null);
              local.failKey = null;
              assert.strictEqual(
                page.storage.readSessionCheckpoint().session_id,
                "retry-session"
              );
              assert.strictEqual(local.getItem(LEGACY_SAVE), null);
            }}

            // CLEAR wins over an old tab, including after a new USER move replaces
            // the tombstone with a checkpoint carrying the clear barrier.
            {{
              const local = new MemoryStorage();
              const oldTab = boot(local);
              oldTab.storage.markSessionCheckpointUserActivity();
              assert.strictEqual(oldTab.storage.writeSessionCheckpoint({{
                session_id: "old-session",
                runtime_memory: "old frame",
              }}), true);

              const clearTab = boot(local);
              assert.strictEqual(clearTab.storage.clearSessionCheckpoint(), true);
              assert.strictEqual(parse(local, CHECKPOINT).state, "cleared");
              assert.strictEqual(oldTab.storage.writeSessionCheckpoint({{
                session_id: "old-session",
                runtime_memory: "late old frame",
              }}), false);

              clearTab.storage.markSessionCheckpointUserActivity();
              assert.strictEqual(clearTab.storage.writeSessionCheckpoint({{
                session_id: "new-session",
                runtime_memory: "new frame",
              }}), true);
              assert.ok(parse(local, CHECKPOINT).clear_barrier_at);
              assert.strictEqual(oldTab.storage.writeSessionCheckpoint({{
                session_id: "old-session",
                runtime_memory: "even later old frame",
              }}), false);
              assert.strictEqual(parse(local, CHECKPOINT).session_id, "new-session");
            }}

            // Anonymous mode neither migrates nor writes the durable checkpoint.
            {{
              const local = new MemoryStorage({{
                [LEGACY_SAVE]: {{session_id: "private-session"}},
              }});
              const page = boot(local, {{}}, true);
              assert.strictEqual(page.storage.readSessionCheckpoint(), null);
              assert.strictEqual(page.storage.writeSessionCheckpoint({{
                session_id: "private-session",
                runtime_memory: "private",
              }}), false);
              assert.notStrictEqual(local.getItem(LEGACY_SAVE), null);
              assert.strictEqual(local.getItem(CHECKPOINT), null);
              page.storage.writeLatestRuntimeMemory({{runtime_memory: "ephemeral"}});
              assert.strictEqual(
                page.storage.readLatestRuntimeMemory().runtime_memory,
                "ephemeral"
              );
            }}
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()

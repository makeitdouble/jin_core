from pathlib import Path

from utils.mcp_skill_utils import parse_mcp_server_config
from utils.skills_asset_utils import list_skills, load_skill


def test_builtin_blender_mcp_skill_is_discoverable_and_uses_generic_stdio_adapter():
    root = Path(__file__).resolve().parents[1]
    skill_path = root / "assets" / "skills" / "blender_mcp" / "JIN_SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    config = parse_mcp_server_config(content)

    listed = list_skills("blender_mcp")
    loaded = load_skill("blender_mcp")

    assert listed["ok"] is True
    assert [item["name"] for item in listed["skills"]] == ["blender_mcp"]
    assert loaded["ok"] is True
    assert config is not None
    assert not config.get("_invalid")
    assert config["transport"] == "stdio"
    assert config["command"] == "uvx"
    assert config["args"] == ["mcp-for-blender"]
    assert config["read_timeout_seconds"] == 180.0
    assert "<CALL_MCP>" in content
    assert '"skill":"blender_mcp"' in content
    assert "viewport screenshot" in content.casefold()
    assert "user_prompt" in content
    assert "bpy.ops.mesh.primitive_uv_sphere_add" in content
    assert "bpy.ops.mesh.primitive_ico_sphere_add" in content
    assert "verify its exact name with `hasattr`" in content
    assert "material.diffuse_color" in content
    assert "Principled BSDF" in content
    assert "reusing an existing material" in content
    assert "successful edit call confirms only" in content

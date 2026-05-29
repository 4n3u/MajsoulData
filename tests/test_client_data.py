import json
import tempfile
import unittest
from pathlib import Path

from src.client_data import (
    build_client_data_outputs,
    is_client_data_asset_path,
    is_repository_support_lua_asset_path,
    parse_spot_script,
)


class ClientDataTests(unittest.TestCase):
    def test_client_data_asset_path_matches_requested_data_categories(self):
        self.assertTrue(is_client_data_asset_path("MyAssets/docs/config.json"))
        self.assertTrue(is_client_data_asset_path("MyAssets/docs_version/version.json"))
        self.assertTrue(is_client_data_asset_path("MyAssets/docs/spots/aiyin/aiyin04_kr.bytes"))
        self.assertTrue(is_client_data_asset_path("MyAssets/deco/illust_data/default.json"))
        self.assertTrue(is_client_data_asset_path("MyAssets/deco/character/laiya/laiya.json"))
        self.assertTrue(is_client_data_asset_path("MyAssets/spine/400107/_info_output.csv"))
        self.assertTrue(
            is_client_data_asset_path(
                "MyAssets/ui/common/main/pic/common/atlas_common_main_common_config.json"
            )
        )

        self.assertFalse(is_client_data_asset_path("MyAssets/docs/contact_us_kr.txt"))
        self.assertFalse(is_client_data_asset_path("MyAssets/spine/400107/yiji.skel.txt"))
        self.assertFalse(is_client_data_asset_path("LuaByte/Lua/Excels/Data/foo.lua.bytes"))

    def test_repository_support_lua_asset_path_matches_analysis_helpers(self):
        self.assertTrue(is_repository_support_lua_asset_path("LuaByte/Lua/Net/ProtoDeclare.lua.bytes"))
        self.assertTrue(is_repository_support_lua_asset_path("LuaByte/Lua/Net/ExcelDeclare.lua.bytes"))
        self.assertTrue(
            is_repository_support_lua_asset_path(
                "LuaByte/Lua/Game/Amulet/Data/Amulet_Data.lua.bytes"
            )
        )
        self.assertTrue(
            is_repository_support_lua_asset_path(
                "LuaByte/Lua/Game/UIData/UI_Treasure_New_Data.lua.bytes"
            )
        )

        self.assertFalse(
            is_repository_support_lua_asset_path("LuaByte/Lua/Game/MJ/Actions/ActionHule.lua.bytes")
        )
        self.assertFalse(
            is_repository_support_lua_asset_path("LuaByte/Lua/Other/Data/Other_Data.lua.bytes")
        )

    def test_parse_spot_script_keeps_ordered_numbered_lines(self):
        self.assertEqual(
            parse_spot_script("1:hello\n2:player\nbad\n4:text:with:colon\n"),
            [
                {"line": 1, "text": "hello"},
                {"line": 2, "text": "player"},
                {"line": 4, "text": "text:with:colon"},
            ],
        )

    def test_build_client_data_outputs_writes_normalized_json_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "data"
            raw = root / "raw" / "assets"
            (raw / "MyAssets" / "docs" / "spots" / "aiyin").mkdir(parents=True)
            (raw / "MyAssets" / "docs").mkdir(parents=True, exist_ok=True)
            (raw / "MyAssets" / "docs_version").mkdir(parents=True)
            (raw / "MyAssets" / "deco" / "illust_data").mkdir(parents=True)
            (raw / "MyAssets" / "deco" / "character" / "laiya").mkdir(parents=True)
            (raw / "MyAssets" / "spine" / "400107").mkdir(parents=True)
            (
                raw
                / "MyAssets"
                / "ui"
                / "common"
                / "main"
                / "pic"
                / "common"
            ).mkdir(parents=True)

            (raw / "MyAssets" / "docs" / "config.json").write_text('{"a":1}', encoding="utf-8")
            (raw / "MyAssets" / "docs_version" / "version.json").write_text(
                '{"version":"1"}',
                encoding="utf-8",
            )
            (raw / "MyAssets" / "docs" / "spots" / "aiyin" / "aiyin04_kr.bytes").write_text(
                "1:안녕\n2:player\n",
                encoding="utf-8",
            )
            (raw / "MyAssets" / "deco" / "illust_data" / "default.json").write_text(
                '{"default":{"x":1}}',
                encoding="utf-8",
            )
            (raw / "MyAssets" / "deco" / "character" / "laiya" / "laiya.json").write_text(
                '{"w":2541}',
                encoding="utf-8",
            )
            (raw / "MyAssets" / "spine" / "400107" / "_info_output.csv").write_text(
                "spine_width,spine_height\r\n4093,5000\r\n",
                encoding="utf-8",
            )
            (
                raw
                / "MyAssets"
                / "ui"
                / "common"
                / "main"
                / "pic"
                / "common"
                / "atlas_common_main_common_config.json"
            ).write_text('{"button":0}', encoding="utf-8")

            counts = build_client_data_outputs(output, root / "raw")

            self.assertEqual(counts["docs_json"], 1)
            self.assertEqual(counts["docs_version_json"], 1)
            self.assertEqual(counts["spot_scripts"], 1)
            self.assertEqual(counts["deco_illust_json"], 1)
            self.assertEqual(counts["deco_character_json"], 1)
            self.assertEqual(counts["spine_info_csv"], 1)
            self.assertEqual(counts["ui_atlas_json"], 1)

            spot = json.loads(
                (output / "client" / "spot_scripts" / "aiyin" / "aiyin04_kr.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(spot[0], {"line": 1, "text": "안녕"})
            spine = json.loads(
                (output / "client" / "spine" / "info" / "400107" / "_info_output.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(spine[0]["spine_width"], "4093")


if __name__ == "__main__":
    unittest.main()

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.protocol import (
    build_protocol_outputs,
    parse_protocol_sources,
    render_proto_module,
)


class ProtocolTests(unittest.TestCase):
    def test_parse_protocol_sources_resolves_fields_nested_messages_and_imported_types(self):
        sources = {
            "Protol.com_struct_pb": (
                'local a=require"protobuf.protobuf"module("Protol.com_struct_pb")'
                "ERROR=a.Descriptor()"
                'ERROR_CODE_FIELD=a.FieldDescriptor()ERROR_CODE_FIELD.name="code"'
                'ERROR_CODE_FIELD.full_name=".lq.Error.code"ERROR_CODE_FIELD.number=1;'
                "ERROR_CODE_FIELD.label=1;ERROR_CODE_FIELD.type=13;"
                'ERROR.name="Error"ERROR.full_name=".lq.Error"'
                "ERROR.fields={ERROR_CODE_FIELD}ERROR.nested_types={}"
                "Error=a.Message(ERROR)"
            ),
            "Protol.cli_game_pb": (
                'local a=require"protobuf.protobuf"local b=require("Protol.com_struct_pb")'
                'module("Protol.cli_game_pb")'
                "REQAUTHGAME=a.Descriptor()"
                "REQAUTHGAME_DETAIL=a.Descriptor()"
                "REQAUTHGAME_ERROR_FIELD=a.FieldDescriptor()"
                "REQAUTHGAME_TAGS_FIELD=a.FieldDescriptor()"
                "REQAUTHGAME_DETAIL_FIELD=a.FieldDescriptor()"
                'REQAUTHGAME_ERROR_FIELD.name="error"'
                'REQAUTHGAME_ERROR_FIELD.full_name=".lq.ReqAuthGame.error"'
                "REQAUTHGAME_ERROR_FIELD.number=1;"
                "REQAUTHGAME_ERROR_FIELD.label=1;"
                "REQAUTHGAME_ERROR_FIELD.message_type=b.ERROR;"
                "REQAUTHGAME_ERROR_FIELD.type=11;"
                'REQAUTHGAME_TAGS_FIELD.name="tags"'
                'REQAUTHGAME_TAGS_FIELD.full_name=".lq.ReqAuthGame.tags"'
                "REQAUTHGAME_TAGS_FIELD.number=2;"
                "REQAUTHGAME_TAGS_FIELD.label=3;"
                "REQAUTHGAME_TAGS_FIELD.default_value={}"
                "REQAUTHGAME_TAGS_FIELD.type=9;"
                'REQAUTHGAME_DETAIL_FIELD.name="detail"'
                'REQAUTHGAME_DETAIL_FIELD.full_name=".lq.ReqAuthGame.detail"'
                "REQAUTHGAME_DETAIL_FIELD.number=3;"
                "REQAUTHGAME_DETAIL_FIELD.label=1;"
                "REQAUTHGAME_DETAIL_FIELD.message_type=REQAUTHGAME_DETAIL;"
                "REQAUTHGAME_DETAIL_FIELD.type=11;"
                'REQAUTHGAME_DETAIL.name="Detail"'
                'REQAUTHGAME_DETAIL.full_name=".lq.ReqAuthGame.Detail"'
                "REQAUTHGAME_DETAIL.fields={}"
                "REQAUTHGAME_DETAIL.nested_types={}"
                "REQAUTHGAME_DETAIL.containing_type=REQAUTHGAME;"
                'REQAUTHGAME.name="ReqAuthGame"'
                'REQAUTHGAME.full_name=".lq.ReqAuthGame"'
                "REQAUTHGAME.fields={REQAUTHGAME_ERROR_FIELD,REQAUTHGAME_TAGS_FIELD,REQAUTHGAME_DETAIL_FIELD}"
                "REQAUTHGAME.nested_types={REQAUTHGAME_DETAIL}"
                "ReqAuthGame=a.Message(REQAUTHGAME)"
            ),
        }

        modules = {module.name: module for module in parse_protocol_sources(sources)}
        game = modules["Protol.cli_game_pb"]
        message = game.messages[0]

        self.assertEqual(game.package, "lq")
        self.assertEqual(message.name, "ReqAuthGame")
        self.assertEqual([field.name for field in message.fields], ["error", "tags", "detail"])
        self.assertEqual(message.fields[0].type_name, ".lq.Error")
        self.assertEqual(message.fields[0].raw_type_ref, "b.ERROR")
        self.assertTrue(message.fields[1].is_repeated)
        self.assertEqual(message.fields[1].proto_type, "string")
        self.assertEqual(message.fields[2].type_name, ".lq.ReqAuthGame.Detail")
        self.assertEqual(message.nested_messages[0].name, "Detail")

    def test_render_proto_module_emits_human_readable_proto3_schema(self):
        sources = {
            "Protol.com_struct_pb": (
                'local a=require"protobuf.protobuf"module("Protol.com_struct_pb")'
                'ERROR=a.Descriptor()ERROR.name="Error"ERROR.full_name=".lq.Error"'
                "ERROR.fields={}ERROR.nested_types={}Error=a.Message(ERROR)"
            ),
            "Protol.cli_game_pb": (
                'local a=require"protobuf.protobuf"local b=require("Protol.com_struct_pb")'
                'module("Protol.cli_game_pb")REQ=a.Descriptor()REQ_ERROR_FIELD=a.FieldDescriptor()'
                'REQ_ERROR_FIELD.name="error"REQ_ERROR_FIELD.full_name=".lq.Req.error"'
                "REQ_ERROR_FIELD.number=1;REQ_ERROR_FIELD.label=1;"
                "REQ_ERROR_FIELD.message_type=b.ERROR;REQ_ERROR_FIELD.type=11;"
                'REQ.name="Req"REQ.full_name=".lq.Req"REQ.fields={REQ_ERROR_FIELD}'
                "REQ.nested_types={}Req=a.Message(REQ)"
            ),
        }
        modules = {module.name: module for module in parse_protocol_sources(sources)}

        proto = render_proto_module(modules["Protol.cli_game_pb"])

        self.assertIn('syntax = "proto3";', proto)
        self.assertIn("package lq;", proto)
        self.assertIn('import "com_struct.proto";', proto)
        self.assertIn("message Req {", proto)
        self.assertIn(".lq.Error error = 1;", proto)

    def test_parse_protocol_sources_resolves_enums_and_enum_fields(self):
        sources = {
            "Protol.com_const_pb": (
                'local protobuf=require"protobuf.protobuf"module("Protol.com_const_pb")'
                "ENERRORCODE=protobuf.EnumDescriptor();"
                "ENERRORCODE_OK_ENUM=protobuf.EnumValueDescriptor();"
                "ENERRORCODE_ERR_UNKNOWN_ENUM=protobuf.EnumValueDescriptor();"
                'ENERRORCODE_OK_ENUM.name="OK"'
                "ENERRORCODE_OK_ENUM.index=0"
                "ENERRORCODE_OK_ENUM.number=0"
                'ENERRORCODE_ERR_UNKNOWN_ENUM.name="ERR_UNKNOWN"'
                "ENERRORCODE_ERR_UNKNOWN_ENUM.index=1"
                "ENERRORCODE_ERR_UNKNOWN_ENUM.number=1"
                'ENERRORCODE.name="EnErrorCode"'
                'ENERRORCODE.full_name=".lq.EnErrorCode"'
                "ENERRORCODE.values={ENERRORCODE_OK_ENUM,ENERRORCODE_ERR_UNKNOWN_ENUM}"
                "EnErrorCode=protobuf.Enum(ENERRORCODE)"
            ),
            "Protol.cli_game_pb": (
                'local a=require"protobuf.protobuf"local b=require("Protol.com_const_pb")'
                'module("Protol.cli_game_pb")'
                "NOTIFY=a.Descriptor()NOTIFY_STATE_FIELD=a.FieldDescriptor()"
                'NOTIFY_STATE_FIELD.name="state"'
                'NOTIFY_STATE_FIELD.full_name=".lq.Notify.state"'
                "NOTIFY_STATE_FIELD.number=2;"
                "NOTIFY_STATE_FIELD.label=1;"
                "NOTIFY_STATE_FIELD.enum_type=b.ENERRORCODE;"
                "NOTIFY_STATE_FIELD.type=14;"
                'NOTIFY.name="Notify"NOTIFY.full_name=".lq.Notify"'
                "NOTIFY.fields={NOTIFY_STATE_FIELD}NOTIFY.nested_types={}"
                "Notify=a.Message(NOTIFY)"
            ),
        }

        modules = {module.name: module for module in parse_protocol_sources(sources)}
        const = modules["Protol.com_const_pb"]
        game = modules["Protol.cli_game_pb"]

        self.assertEqual(const.enums[0].name, "EnErrorCode")
        self.assertEqual([value.name for value in const.enums[0].values], ["OK", "ERR_UNKNOWN"])
        self.assertEqual(game.messages[0].fields[0].type_name, ".lq.EnErrorCode")

        self.assertIn("enum EnErrorCode {", render_proto_module(const))
        self.assertIn("OK = 0;", render_proto_module(const))
        self.assertIn(".lq.EnErrorCode state = 2;", render_proto_module(game))

    def test_build_protocol_outputs_runs_protoc_gen_doc_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "data"
            raw_root = root / "raw"
            protol_dir = raw_root / "lua" / "LuaByte" / "Lua" / "Protol"
            assets_dir = raw_root / "assets" / "MyAssets" / "docs"
            protol_dir.mkdir(parents=True)
            assets_dir.mkdir(parents=True)
            (protol_dir / "client_pb.lua").write_text(
                'local a=require"protobuf.protobuf"module("Protol.client_pb")'
                'PING=a.Descriptor()PING_ID_FIELD=a.FieldDescriptor()'
                'PING_ID_FIELD.name="id"PING_ID_FIELD.full_name=".lq.Ping.id"'
                "PING_ID_FIELD.number=1;PING_ID_FIELD.label=1;PING_ID_FIELD.type=13;"
                'PING.name="Ping"PING.full_name=".lq.Ping"'
                "PING.fields={PING_ID_FIELD}PING.nested_types={}Ping=a.Message(PING)",
                encoding="utf-8",
            )
            (protol_dir / "pong_pb.lua").write_text(
                'local a=require"protobuf.protobuf"module("Protol.pong_pb")'
                'PONG=a.Descriptor()PONG_ID_FIELD=a.FieldDescriptor()'
                'PONG_ID_FIELD.name="id"PONG_ID_FIELD.full_name=".lq.Pong.id"'
                "PONG_ID_FIELD.number=1;PONG_ID_FIELD.label=1;PONG_ID_FIELD.type=13;"
                'PONG.name="Pong"PONG.full_name=".lq.Pong"'
                "PONG.fields={PONG_ID_FIELD}PONG.nested_types={}Pong=a.Message(PONG)",
                encoding="utf-8",
            )
            (assets_dir / "proto_config.bytes").write_text(
                json.dumps(
                    {
                        "service": {
                            "Lobby": {
                                "ping": {
                                    "request": "Ping",
                                    "response": "Pong",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                out_index = command.index("--doc_out") + 1
                opt_index = command.index("--doc_opt") + 1
                out_dir = Path(command[out_index])
                out_name = command[opt_index].split(",", 1)[1]
                (out_dir / out_name).write_text(
                    "# Protocol Documentation  \n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(command, 0)

            with patch("src.protocol.shutil.which", return_value="protoc-gen-doc"):
                with patch("src.protocol.subprocess.run", side_effect=fake_run):
                    counts = build_protocol_outputs(output, raw_root)

            self.assertEqual(counts["doc"], "protoc-gen-doc")
            self.assertTrue((output / "protocol" / "protocol.md").exists())
            self.assertEqual(
                (output / "protocol" / "protocol.md").read_text(encoding="utf-8"),
                "# Protocol Documentation\n",
            )
            self.assertTrue((output / "protocol" / "services.json").exists())
            self.assertFalse((output / "protocol" / "services.md").exists())
            self.assertTrue((output / "protocol" / "proto" / "services.proto").exists())
            self.assertFalse((output / "protocol" / "index.md").exists())
            self.assertEqual(calls[0][0], "protoc")
            self.assertIn("--doc_opt", calls[0])
            self.assertIn("services.proto", calls[0])


if __name__ == "__main__":
    unittest.main()

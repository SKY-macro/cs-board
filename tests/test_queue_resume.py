import importlib.util
import inspect
import json
import queue
import sys
import tempfile
import threading
import time
import unittest
import wave
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from starlette.requests import Request


RELEASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_ROOT))
SPEC = importlib.util.spec_from_file_location("whiteboard_release_server", RELEASE_ROOT / "webapp" / "server.py")
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class QueueResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        SERVER.JOBS_DIR = Path(self.temporary.name)
        SERVER.CHARACTER_LIBRARY_DIR = Path(self.temporary.name) / "character-library"
        SERVER.JOBS = {}
        SERVER.VOICE_QUEUE = queue.Queue()
        SERVER.MODEL_QUEUE = queue.Queue()
        SERVER.ensure_pipeline_workers = lambda: None
        if hasattr(SERVER, "MODEL_CATALOG_CACHE"):
            SERVER.MODEL_CATALOG_CACHE.clear()
        SERVER.IMAGE_NODE_POOL.reset(Path(self.temporary.name) / "image-node-stats.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def job(self, job_id: str) -> dict:
        return {
            "id": job_id,
            "status": "queued",
            "stage": "等待语音克隆",
            "progress": 1,
            "created_at": 1.0,
            "started_at": 1.0,
            "queue_order": 1,
            "queue_stage": "voice",
            "job_type": "generate",
            "copy": "这是一段用于验证任务断点恢复的测试文案。",
            "style": SERVER.DEFAULT_STYLE,
            "scenes_per_image": 1,
            "pen_text": "",
            "include_key_text": True,
            "include_subtitles": True,
            "stroke_detail": "detailed",
            "timings": {},
        }

    def test_task_name_defaults_to_first_fifteen_script_characters(self) -> None:
        name = SERVER.normalized_task_name("", "  一二三四五六七八九十\n十一十二十三十四十五十六  ", "job-test")
        self.assertEqual(name, "一二三四五六七八九十十一十二十")

    def test_explicit_task_name_is_preserved(self) -> None:
        self.assertEqual(SERVER.normalized_task_name("  我的任务  ", "备用文案", "job-test"), "我的任务")

    def test_task_name_can_be_changed_without_touching_other_job_data(self) -> None:
        job_id = "rename-test"
        SERVER.JOBS[job_id] = {**self.job(job_id), "task_name": "旧名称", "status": "done"}
        response = TestClient(SERVER.app).patch(f"/api/jobs/{job_id}/name", json={"task_name": " 新名称 "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["task_name"], "新名称")
        self.assertEqual(SERVER.JOBS[job_id]["copy"], self.job(job_id)["copy"])

    def test_rerender_copies_history_and_assigns_incrementing_default_versions(self) -> None:
        from PIL import Image

        job_id = "rerender-source"
        source_dir = SERVER.JOBS_DIR / job_id
        source_dir.mkdir(parents=True)
        (source_dir / "voice.wav").write_bytes(b"voice")
        (source_dir / "plan.json").write_text("[]", encoding="utf-8")
        (source_dir / "boards.json").write_text("[]", encoding="utf-8")
        Image.new("RGB", (64, 64), "white").save(source_dir / "board-01.png")
        SERVER.JOBS[job_id] = {**self.job(job_id), "task_name": "测试故事", "status": "done", "can_rerender": True}
        original = dict(SERVER.JOBS[job_id])

        with mock.patch.object(SERVER, "start_render_task"):
            first = TestClient(SERVER.app).post(f"/api/jobs/{job_id}/rerender", json={})
            second = TestClient(SERVER.app).post(f"/api/jobs/{job_id}/rerender", json={})

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["task_name"], "测试故事+重新渲染第1版")
        self.assertEqual(second.json()["task_name"], "测试故事+重新渲染第2版")
        self.assertEqual(first.json()["rerender_version"], 1)
        self.assertEqual(second.json()["rerender_version"], 2)
        self.assertEqual(SERVER.JOBS[job_id], original)
        self.assertNotEqual(first.json()["id"], job_id)
        self.assertTrue((SERVER.JOBS_DIR / first.json()["id"] / "board-01.png").is_file())

    def test_all_generated_images_download_as_named_zip(self) -> None:
        from PIL import Image

        job_id = "gallery-zip"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        Image.new("RGB", (64, 64), "red").save(job_dir / "board-01.png")
        Image.new("RGB", (64, 64), "blue").save(job_dir / "board-02.png")
        SERVER.JOBS[job_id] = {**self.job(job_id), "task_name": "图片测试", "status": "done"}

        response = TestClient(SERVER.app).get(f"/api/jobs/{job_id}/images.zip")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers["content-disposition"])
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(archive.namelist(), ["图片测试/第01张.png", "图片测试/第02张.png"])

    def test_custom_reference_prompt_replaces_default_character(self) -> None:
        prompt = SERVER.build_board_prompt(
            [{"title": "相遇", "concept": "小昌和小林交谈", "elements": ["小昌挥手", "小林回应"], "text": "两个人见面了。"}],
            "自定义参考",
            "输入图1是风格参考。输入图2定义人物“小昌”，输入图3定义人物“小林”。",
            True,
        )
        self.assertIn("人物“小昌”", prompt)
        self.assertIn("人物“小林”", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)
        self.assertIn("小昌挥手", prompt)
        self.assertLessEqual(len(prompt), 1200)

    def test_paper_metaphor_routes_process_copy_to_machine_reference(self) -> None:
        paths, instruction = SERVER.paper_metaphor_reference_context([
            {"title": "自动化流程", "concept": "把生产系统变成稳定流程", "text": "系统自动完成每个步骤。"}
        ])
        self.assertEqual(paths[0].name, "03-process-machine.png")
        self.assertIn("流程", instruction)
        self.assertIn("禁止照搬", instruction)

    def test_paper_metaphor_prompt_keeps_story_character(self) -> None:
        prompt = SERVER.build_board_prompt(
            [{"title": "小猴改正", "concept": "小猴向大家道歉", "elements": ["小猴低头道歉"], "text": "小猴认识到了错误。"}],
            SERVER.PAPER_METAPHOR_STYLE,
            "输入图仅作为纸艺风格参考。",
        )
        self.assertIn("小猴低头道歉", prompt)
        self.assertIn(SERVER.IDENTITY_PROMPTS["consistent"], prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_unknown_style_never_silently_falls_back(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "后台未加载画面风格"):
            SERVER.style_recipe("不存在的风格")

    def test_style_catalog_exposes_the_exact_prompt_recipe_for_the_ui(self) -> None:
        catalog = SERVER.get_style_catalog()
        styles = {item["name"]: item["recipe"] for item in catalog["styles"]}

        self.assertEqual(styles["水墨写意"], SERVER.style_recipe("水墨写意"))
        self.assertEqual(len(styles), len(SERVER.STYLE_PRESETS) - 1)
        self.assertNotIn(SERVER.INFOGRAPHIC_STYLE, styles)

    def test_style_prompt_preview_matches_the_real_provider_prompt_compaction(self) -> None:
        preview = SERVER.preview_style_prompt({
            "page_mode": "standard",
            "style": "水墨写意",
            "scenes_per_image": 2,
            "aspect_ratio": "9:16",
            "presentation_mode": "whiteboard",
            "identity_mode": "female",
        })

        self.assertIn("{{分镜1的事件与画面概念}}", preview["full_prompt"])
        self.assertIn("{{分镜2对应原文}}", preview["full_prompt"])
        self.assertIn(SERVER.IDENTITY_PROMPTS["female"], preview["full_prompt"])
        self.assertEqual(preview["sent_prompt"], SERVER.compact_image_prompt(preview["full_prompt"]))
        self.assertEqual(preview["full_length"], len(preview["full_prompt"]))
        self.assertEqual(preview["sent_length"], len(preview["sent_prompt"]))
        self.assertEqual(preview["request"]["size"], SERVER.aspect_api_size("9:16"))

    def test_story_handdrawn_library_adds_exactly_twenty_styles(self) -> None:
        self.assertEqual(len(SERVER.HANDDRAWN_STYLE_PRESETS), 20)
        self.assertIn("彩铅日记漫画（默认）", SERVER.HANDDRAWN_STYLE_PRESETS)
        self.assertIn("粗粝木刻社论插画", SERVER.HANDDRAWN_STYLE_PRESETS)

    def test_story_handdrawn_recipe_keeps_positive_and_negative_constraints(self) -> None:
        recipe = SERVER.style_recipe("水墨写意")
        self.assertIn("浓淡干湿", recipe)
        self.assertIn("禁止", recipe)
        self.assertIn("内容边界", recipe)

    def test_handdrawn_visual_recipes_do_not_seed_people_or_places(self) -> None:
        contaminated_terms = ("elderly", "hospital", "clinic", "school", "老人", "孩子", "儿童", "医院", "诊所", "学校", "教室", "家庭")
        for name, recipe in SERVER.HANDDRAWN_STYLE_PRESETS.items():
            with self.subTest(style=name):
                normalized = recipe.lower()
                self.assertFalse(any(term in normalized for term in contaminated_terms))
                self.assertIn("只能来自当前分镜", recipe)

    def test_colored_pencil_diary_uses_clean_visual_profile(self) -> None:
        recipe = SERVER.style_recipe("彩铅日记漫画（默认）")
        self.assertIn("黑色毡尖笔轮廓", recipe)
        self.assertIn("干性彩铅笔触", recipe)
        self.assertIn("年龄特征必须服从分镜", recipe)

    def test_clear_japanese_storybook_style_is_visual_only(self) -> None:
        recipe = SERVER.style_recipe("清透日系生活绘本")
        self.assertIn("黑灰墨线", recipe)
        self.assertIn("成年人约 5～6 头身", recipe)
        self.assertIn("儿童约 4～5 头身", recipe)
        self.assertIn("小型黑色竖椭圆或圆点眼", recipe)
        self.assertIn("哑光平涂", recipe)
        self.assertIn("颜色只用于人物服装和剧情核心道具", recipe)
        self.assertIn("背景建筑、家具、地面、天空和植物一律不着色", recipe)
        self.assertIn("剧情必要的小面积语义色", recipe)
        self.assertIn("细微纸张颗粒", recipe)
        self.assertIn("禁止水彩晕染", recipe)
        self.assertIn("纯白面积不少于 80%", recipe)
        self.assertIn("蜡笔或炭笔颗粒", recipe)
        self.assertIn("禁止泛黄", recipe)
        self.assertIn("禁止 Q 版", recipe)
        self.assertIn("风景绘本式铺满背景", recipe)
        self.assertIn("只能来自当前分镜", recipe)
        self.assertNotIn("偏大的圆头", recipe)
        self.assertNotIn("短而紧凑的身体", recipe)
        self.assertNotIn("书包", recipe)
        self.assertNotIn("玄关", recipe)

    def test_clear_japanese_storybook_keeps_composition_scene_driven(self) -> None:
        prompt = SERVER.build_board_prompt(
            [{"title": "回家", "concept": "两人见面", "elements": ["两人站立交谈"], "text": "他终于回来了。"}],
            "清透日系生活绘本",
            aspect_ratio="9:16",
            presentation_mode="story-color",
        )
        self.assertIn("构图服从剧情", prompt)
        self.assertIn(SERVER.IDENTITY_PROMPTS["consistent"], prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_standard_character_bindings_select_only_current_scene_cast(self) -> None:
        from PIL import Image

        job_id = "library-cast"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        for index in range(1, 4):
            Image.effect_noise((128, 128), 20 + index).convert("RGB").save(job_dir / f"library-character-{index:02d}.png")
        SERVER.JOBS[job_id] = {
            **self.job(job_id),
            "style": "复古报纸拼贴风",
            "character_bindings": [
                {"role_id": "role_01", "story_name": "小满", "description": "8岁短发女孩", "core_personality": "勇敢好奇", "facial_persona": "灵动坚定", "image": "library-character-01.png"},
                {"role_id": "role_02", "story_name": "妈妈", "description": "低发髻青年女性", "image": "library-character-02.png"},
                {"role_id": "role_03", "story_name": "老师", "description": "戴眼镜中年女性", "image": "library-character-03.png"},
            ],
        }
        paths, instruction, context = SERVER.task_character_reference_context(
            job_id,
            [{"cast_ids": ["role_01", "role_02"], "concept": "小满和妈妈吃饭"}],
            input_offset=1,
        )
        self.assertEqual([path.name for path in paths], ["library-character-01.png", "library-character-02.png"])
        self.assertIn("输入图2定义人物“小满”", instruction)
        self.assertIn("核心性格：勇敢好奇", instruction)
        self.assertIn("固定脸相：灵动坚定", instruction)
        self.assertIn("输入图3定义人物“妈妈”", instruction)
        self.assertNotIn("老师", instruction)
        self.assertIn("role_01=小满", context)

    def test_character_prompt_compaction_keeps_current_scene_before_long_reference_manifest(self) -> None:
        reference = "\n".join(
            f"输入图{index + 1}定义人物‘角色{index}’：" + ("稳定身份特征" * 12)
            for index in range(8)
        )
        prompt = SERVER.build_board_prompt(
            [{"concept": "小满推门进入教室并向老师问好", "elements": ["小满推门", "老师回头"], "text": "第二天，小满走进教室。"}],
            SERVER.DEFAULT_STYLE,
            reference_instruction=reference,
            use_character_references=True,
            aspect_ratio="3:4",
        )
        compact = SERVER.compact_image_prompt(prompt)
        self.assertGreater(len(prompt), SERVER.IMAGE_PROMPT_LIMIT)
        self.assertIn("小满推门进入教室并向老师问好", compact)
        self.assertIn("第二天，小满走进教室", compact)

    def test_character_reference_selection_falls_back_to_names_when_cast_ids_missing(self) -> None:
        from PIL import Image

        job_id = "library-name-fallback"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 20).convert("RGB").save(job_dir / "library-character-01.png")
        Image.effect_noise((128, 128), 30).convert("RGB").save(job_dir / "library-character-02.png")
        SERVER.JOBS[job_id] = {
            **self.job(job_id),
            "character_bindings": [
                {"role_id": "role_01", "story_name": "小满", "description": "女孩", "image": "library-character-01.png"},
                {"role_id": "role_02", "story_name": "妈妈", "description": "女性", "image": "library-character-02.png"},
            ],
        }
        paths, _instruction, _context = SERVER.task_character_reference_context(
            job_id,
            [{"concept": "妈妈独自回到家", "elements": ["妈妈推门"]}],
        )
        self.assertEqual([path.name for path in paths], ["library-character-02.png"])

    def test_reference_image_nodes_are_filtered_by_verified_capacity(self) -> None:
        plan = {
            "configured_count": 2,
            "ready_count": 2,
            "ready": [
                {"position": 1, "service": {"id": "small", "max_input_images": 4}},
                {"position": 2, "service": {"id": "large", "max_input_images": 16}},
            ],
            "skipped": [],
        }
        with mock.patch.object(SERVER, "provider_service_plan", return_value=plan), mock.patch.object(
            SERVER.IMAGE_NODE_POOL,
            "call",
            return_value={"data": [{"b64_json": "AA=="}]},
        ) as call:
            SERVER.provider_image_edit({}, {"model": "gpt-image-2"}, [(f"{i}.png", b"x", "image/png") for i in range(6)])
        self.assertEqual(call.call_args.args[0]["id"], "large")

    def test_image_node_affinity_keeps_one_job_on_one_relay(self) -> None:
        job_id = "affinity-job"
        SERVER.JOBS[job_id] = self.job(job_id)
        ready = [
            {"id": "node-a", "base_url": "https://a.example/v1", "api_key": "a"},
            {"id": "node-b", "base_url": "https://b.example/v1", "api_key": "b"},
        ]
        used = []

        def fake_call(service, invoke, **_kwargs):
            used.append(service["id"])
            return invoke()

        with mock.patch.object(SERVER.IMAGE_NODE_POOL, "call", side_effect=fake_call) as call:
            first = SERVER.provider_image_affinity_call(ready, lambda service: {"node": service["id"]}, job_id)
            second = SERVER.provider_image_affinity_call(ready, lambda service: {"node": service["id"]}, job_id)
        self.assertEqual(first, second)
        self.assertEqual(used, [used[0], used[0]])
        self.assertEqual(SERVER.JOBS[job_id]["image_affinity_node_id"], used[0])
        self.assertTrue(all(item.kwargs["skip_cooldown"] for item in call.call_args_list))

    def test_single_image_node_is_recorded_as_job_affinity(self) -> None:
        job_id = "single-node-affinity"
        SERVER.JOBS[job_id] = self.job(job_id)
        ready = [{"id": "only-node", "base_url": "https://only.example/v1", "api_key": "a"}]
        with mock.patch.object(SERVER.IMAGE_NODE_POOL, "call_any", return_value={"ok": True}):
            SERVER.provider_image_affinity_call(ready, lambda service: {"node": service["id"]}, job_id)
        self.assertEqual(SERVER.JOBS[job_id]["image_affinity_node_id"], "only-node")

    def test_standard_job_freezes_approved_character_asset(self) -> None:
        from PIL import Image

        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 80).convert("RGB").save(asset_dir / "character-sheet.png")
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "青年男",
            "description": "短黑发青年男性，深色上衣", "status": "approved",
            "image": "character-sheet.png", "created_at": 1,
        })
        bindings = [{
            "role_id": "role_01", "story_name": "小林", "description": "短黑发青年男性，深色上衣",
            "core_personality": "温和可靠", "facial_persona": "眉眼温厚",
            "temporary_behavior": "认真写计划", "gender": "男", "age_group": "青年", "asset_id": asset_id,
        }]
        response = TestClient(SERVER.app).post("/api/jobs", data={
            "copy": "小林走进房间，随后坐在桌边认真写下今天的计划。",
            "voice_mode": "none", "style": SERVER.DEFAULT_STYLE,
            "character_bindings": json.dumps(bindings, ensure_ascii=False),
        })
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["id"]
        saved = SERVER.JOBS[job_id]["character_bindings"][0]
        self.assertEqual(saved["story_name"], "小林")
        self.assertEqual(saved["core_personality"], "温和可靠")
        self.assertEqual(saved["facial_persona"], "眉眼温厚")
        self.assertTrue((SERVER.JOBS_DIR / job_id / saved["image"]).exists())

    def test_interrupted_character_draw_becomes_visible_error(self) -> None:
        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id,
            "style": SERVER.DEFAULT_STYLE,
            "label": "候选",
            "description": "短发青年男性",
            "status": "queued",
            "image": None,
            "created_at": 1,
        })
        SERVER.recover_interrupted_character_draws()
        _manifest, saved = SERVER.character_asset_record(asset_id)
        self.assertEqual(saved["status"], "error")
        self.assertIn("后台重启中断", saved["error"])

    def test_character_draw_names_are_unique_within_one_style(self) -> None:
        client = TestClient(SERVER.app)
        with mock.patch.object(SERVER, "draw_character_asset", return_value=None):
            first = client.post("/api/character-assets/draw", json={
                "style": SERVER.DEFAULT_STYLE, "label": "青年女", "description": "青年女性，黑色中长发",
            })
            second = client.post("/api/character-assets/draw", json={
                "style": SERVER.DEFAULT_STYLE, "label": "青年女", "description": "青年女性，黑色中长发",
            })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["items"][0]["label"], "青年女")
        self.assertEqual(second.json()["items"][0]["label"], "青年女 2")

    def test_character_draw_can_freeze_an_existing_asset_as_its_identity_source(self) -> None:
        from PIL import Image

        source_id = "abcdef123456"
        source_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / source_id
        source_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 25).convert("RGB").save(source_dir / "character-sheet.png")
        SERVER.atomic_write_json(source_dir / "asset.json", {
            "id": source_id, "style": SERVER.DEFAULT_STYLE, "label": "青年男",
            "description": "青年男性，短黑发，朴素深色外套", "status": "approved",
            "image": "character-sheet.png", "created_at": 1,
        })

        with mock.patch.object(SERVER, "start_character_asset_worker") as start:
            response = TestClient(SERVER.app).post("/api/character-assets/draw", json={
                "style": SERVER.DEFAULT_STYLE,
                "label": "青年男变体",
                "description": "保留原人物脸型和短黑发，服装改为浅色针织衫",
                "source_asset_id": source_id,
            })

        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()["items"][0]
        manifest_path, saved = SERVER.character_asset_record(created["id"])
        self.assertEqual(saved["source_asset_id"], source_id)
        self.assertEqual(saved["source_asset_label"], "青年男")
        self.assertEqual(saved["source_image"], "source-character.png")
        self.assertEqual((manifest_path.parent / "source-character.png").read_bytes(), (source_dir / "character-sheet.png").read_bytes())
        start.assert_called_once_with(created["id"])

    def test_character_draw_uses_the_frozen_source_image_as_character_reference(self) -> None:
        from PIL import Image

        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 25).convert("RGB").save(asset_dir / "source-character.png")
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "青年男变体",
            "description": "保留原人物身份，服装改为浅色针织衫", "status": "queued",
            "image": None, "source_image": "source-character.png", "created_at": 1,
        })
        captured: dict[str, object] = {}

        def fake_generate(_config, prompt, target, references, *_args):
            captured["prompt"] = prompt
            captured["references"] = [path.name for path in references]
            Image.effect_noise((128, 128), 45).convert("RGB").save(target)

        with mock.patch.object(SERVER, "load_config", return_value={}), mock.patch.object(SERVER, "generate_image", side_effect=fake_generate):
            SERVER.draw_character_asset(asset_id)

        self.assertEqual(captured["references"], ["source-character.png"])
        self.assertIn("输入图1定义基础角色身份", str(captured["prompt"]))
        self.assertIn("只改变角色要求明确提出的属性", str(captured["prompt"]))

    def test_character_draw_stops_instead_of_losing_a_missing_identity_source(self) -> None:
        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "青年男变体",
            "description": "保留原人物身份，服装改为浅色针织衫", "status": "queued",
            "image": None, "source_image": "missing-source.png", "created_at": 1,
        })

        with mock.patch.object(SERVER, "generate_image") as generate:
            SERVER.draw_character_asset(asset_id)

        _manifest, saved = SERVER.character_asset_record(asset_id)
        self.assertEqual(saved["status"], "error")
        self.assertIn("来源角色图缺失", saved["error"])
        generate.assert_not_called()

    def test_character_match_returns_both_story_name_and_asset_label(self) -> None:
        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "青年女",
            "description": "青年女性，黑色中长发", "status": "approved", "image": "character-sheet.png", "created_at": 1,
        })
        model_result = [{
            "role_id": "role_01", "story_name": "我", "gender": "女", "age_group": "青年",
            "description": "青年女性，黑色中长发", "asset_id": None,
        }]
        with mock.patch.object(SERVER, "provider_text", return_value={"output_text": json.dumps(model_result, ensure_ascii=False)}):
            response = TestClient(SERVER.app).post("/api/character-matches", json={
                "copy": "我是一名青年女性，今天准备出门去公司上班。", "style": SERVER.DEFAULT_STYLE,
            })
        self.assertEqual(response.status_code, 200)
        binding = response.json()["bindings"][0]
        self.assertEqual(binding["story_name"], "我")
        self.assertEqual(binding["asset_label"], "青年女")

    def test_character_match_rejects_demographic_fit_when_fixed_persona_conflicts(self) -> None:
        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "精明青年男",
            "description": "青年男性，窄长脸，眼神精明，整体显得工于算计", "status": "approved",
            "image": "character-sheet.png", "created_at": 1,
        })
        model_result = [{
            "role_id": "role_01", "story_name": "他", "gender": "男", "age_group": "青年",
            "description": "青年男性，短黑发，眉眼温和真诚，衣着朴素",
            "core_personality": "真诚深情、克制付出", "facial_persona": "温和可靠、朴素克制",
            "temporary_behavior": "为了攒钱而节省开支",
            "asset_id": asset_id, "persona_compatible": False, "match_confidence": 0.42,
            "match_reason": "年龄性别相符，但精明算计脸与最终揭示的真诚付出冲突",
        }]
        captured: dict[str, str] = {}

        def fake_provider(_config, _model, prompt):
            captured["prompt"] = prompt
            return {"output_text": json.dumps(model_result, ensure_ascii=False)}

        with mock.patch.object(SERVER, "provider_text", side_effect=fake_provider):
            response = TestClient(SERVER.app).post("/api/character-matches", json={
                "copy": "他平时处处省钱，我以为他抠门，最后才发现他省了三个月，把自己能给的全给了我。",
                "style": SERVER.DEFAULT_STYLE,
            })
        self.assertEqual(response.status_code, 200)
        binding = response.json()["bindings"][0]
        self.assertIsNone(binding["asset_id"])
        self.assertEqual(binding["core_personality"], "真诚深情、克制付出")
        self.assertIn("最终揭示", captured["prompt"])
        self.assertIn("不得把节省等同于吝啬", captured["prompt"])
        self.assertIn("人格兼容", captured["prompt"])

    def test_character_match_accepts_high_confidence_fixed_persona(self) -> None:
        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "温厚青年男",
            "description": "青年男性，短黑发，眉眼温和真诚，神情朴素克制", "status": "approved",
            "image": "character-sheet.png", "created_at": 1,
        })
        model_result = [{
            "role_id": "role_01", "story_name": "他", "gender": "男", "age_group": "青年",
            "description": "青年男性，短黑发，眉眼温和真诚，衣着朴素",
            "core_personality": "真诚深情、克制付出", "facial_persona": "温和可靠、朴素克制",
            "temporary_behavior": "为了攒钱而节省开支",
            "asset_id": asset_id, "persona_compatible": True, "match_confidence": 0.91,
            "match_reason": "年龄、外观与温和克制的固定脸相均一致",
        }]
        captured: dict[str, str] = {}

        def fake_provider(_config, _model, prompt):
            captured["prompt"] = prompt
            return {"output_text": json.dumps(model_result, ensure_ascii=False)}

        with mock.patch.object(SERVER, "provider_text", side_effect=fake_provider):
            response = TestClient(SERVER.app).post("/api/character-matches", json={
                "copy": "他省下自己的生活费，最后把自己能给的全给了我。", "style": SERVER.DEFAULT_STYLE,
            })
        binding = response.json()["bindings"][0]
        self.assertEqual(binding["asset_id"], asset_id)
        self.assertEqual(binding["asset_label"], "温厚青年男")
        self.assertEqual(binding["match_confidence"], 0.91)
        self.assertNotIn("库中只有一个同类候选时，都必须填 null", captured["prompt"])
        self.assertIn("候选数量不影响匹配结论", captured["prompt"])

    def test_standard_job_accepts_unmatched_characters_for_automatic_preparation(self) -> None:
        response = TestClient(SERVER.app).post("/api/jobs", data={
            "copy": "小林走进房间，随后坐在桌边认真写下今天的计划。",
            "voice_mode": "none", "style": SERVER.DEFAULT_STYLE,
            "character_bindings": json.dumps([{"role_id": "role_01", "story_name": "小林", "asset_id": None}], ensure_ascii=False),
        })
        self.assertEqual(response.status_code, 200, response.text)
        saved = SERVER.JOBS[response.json()["id"]]
        self.assertFalse(saved["characters_prepared"])
        self.assertIsNone(saved["character_bindings"][0]["asset_id"])

    def test_automatic_character_preparation_draws_approves_and_freezes_missing_roles(self) -> None:
        from PIL import Image

        job_id = "auto-character"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        SERVER.JOBS[job_id] = {
            **self.job(job_id),
            "reference_mode": "standard",
            "character_bindings": [],
            "characters_prepared": False,
        }
        analyzed = {
            "role_id": "role_01", "story_name": "小林", "gender": "男性", "age_group": "青年",
            "description": "青年男性，短黑发，眉眼温和，身形清瘦，穿深色外套",
            "core_personality": "真诚可靠", "facial_persona": "温和克制",
            "temporary_behavior": "认真做计划", "asset_id": None,
        }

        def fake_generate(_config, _prompt, target, _references, _job_id, _aspect_ratio):
            Image.effect_noise((256, 384), 45).convert("RGB").save(target)

        with mock.patch.object(SERVER, "match_character_assets", return_value={"bindings": [analyzed]}), \
                mock.patch.object(SERVER, "load_config", return_value={}), \
                mock.patch.object(SERVER, "generate_image", side_effect=fake_generate):
            SERVER.ensure_standard_job_character_assets(job_id, SERVER.JOBS[job_id]["copy"], SERVER.DEFAULT_STYLE)

        saved = SERVER.JOBS[job_id]
        self.assertTrue(saved["characters_prepared"])
        self.assertEqual(saved["character_count"], 1)
        binding = saved["character_bindings"][0]
        self.assertTrue(binding["asset_id"])
        self.assertEqual(binding["story_name"], "小林")
        self.assertTrue((job_dir / binding["image"]).is_file())
        _manifest, asset = SERVER.character_asset_record(binding["asset_id"])
        self.assertEqual(asset["status"], "approved")
        self.assertEqual(asset["origin_job_id"], job_id)

    def test_automatic_character_preparation_preserves_a_complete_manual_binding(self) -> None:
        from PIL import Image

        asset_id = "manual123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.DEFAULT_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        Image.new("RGB", (96, 128), "white").save(asset_dir / "character-sheet.png")
        SERVER.atomic_write_json(asset_dir / "asset.json", {
            "id": asset_id, "style": SERVER.DEFAULT_STYLE, "label": "手选青年男",
            "description": "青年男性，短黑发，眉眼温和", "status": "approved",
            "image": "character-sheet.png", "created_at": 1,
        })
        job_id = "manual-character"
        (SERVER.JOBS_DIR / job_id).mkdir(parents=True)
        SERVER.JOBS[job_id] = {
            **self.job(job_id), "reference_mode": "standard", "characters_prepared": True,
            "character_bindings": [{
                "role_id": "role_01", "story_name": "小林", "asset_id": asset_id,
                "asset_label": "手选青年男", "description": "青年男性，短黑发，眉眼温和",
                "image": "library-character-01.png",
            }],
        }
        Image.new("RGB", (96, 128), "white").save(SERVER.JOBS_DIR / job_id / "library-character-01.png")

        with mock.patch.object(SERVER, "match_character_assets") as match:
            SERVER.ensure_standard_job_character_assets(job_id, SERVER.JOBS[job_id]["copy"], SERVER.DEFAULT_STYLE)

        match.assert_not_called()
        self.assertEqual(SERVER.JOBS[job_id]["character_bindings"][0]["asset_id"], asset_id)

    def test_legacy_frozen_bindings_are_marked_prepared_without_reanalysis(self) -> None:
        from PIL import Image

        job_id = "legacy-character"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        Image.effect_noise((256, 384), 30).convert("RGB").save(job_dir / "library-character-01.png")
        SERVER.JOBS[job_id] = {
            **self.job(job_id), "reference_mode": "standard",
            "character_bindings": [{
                "role_id": "role_01", "story_name": "小林", "asset_id": "removed-public-asset",
                "image": "library-character-01.png",
            }],
        }

        with mock.patch.object(SERVER, "match_character_assets") as match:
            SERVER.ensure_standard_job_character_assets(job_id, SERVER.JOBS[job_id]["copy"], SERVER.DEFAULT_STYLE)

        match.assert_not_called()
        self.assertTrue(SERVER.JOBS[job_id]["characters_prepared"])

    def test_character_plan_requires_scene_cast_ids(self) -> None:
        payload = [{"title": "小林进门", "key_text": "回到家", "concept": "小林走进房间", "elements": ["小林推门", "房间桌椅", "小林坐下"], "cast_ids": ["role_01"]}]
        with mock.patch.object(SERVER, "provider_text", return_value={"output_text": json.dumps(payload, ensure_ascii=False)}):
            scenes = SERVER.make_plan(
                {"text_model": "gpt-5"}, "小林走进房间，随后坐在桌边认真写下今天的计划。",
                8.0, SERVER.DEFAULT_STYLE, "role_01=小林（短黑发青年男性）",
            )
        self.assertEqual(scenes[0]["cast_ids"], ["role_01"])

    def test_clear_japanese_storybook_keeps_style_reference_for_character_draws_only(self) -> None:
        paths, instruction = SERVER.clear_storybook_reference_context()
        self.assertEqual(paths, [SERVER.CLEAR_STORYBOOK_REFERENCE_PATH])
        self.assertTrue(paths[0].is_file())
        self.assertIn("清透日系生活绘本视觉语言", instruction)
        self.assertIn("纯白留白背景", instruction)
        self.assertIn("纤细轻盈的黑灰墨线", instruction)
        self.assertIn("柔和低饱和局部设色", instruction)
        self.assertIn("自然修长的生活绘本头身比例", instruction)
        self.assertIn("简洁圆点五官", instruction)
        self.assertIn("不得复制", instruction)
        self.assertIn("人物身份、数量、服装、动作、道具、场景、事件或具体构图", instruction)

        draw_paths, draw_instruction = SERVER.style_only_reference_context(SERVER.CLEAR_STORYBOOK_STYLE)
        self.assertEqual(draw_paths, paths)
        self.assertEqual(draw_instruction, instruction)

        production_paths, production_instruction = SERVER.board_style_reference_context(
            SERVER.CLEAR_STORYBOOK_STYLE,
            [{"concept": "爸爸牵着七岁乐乐去公园"}],
        )
        self.assertEqual(production_paths, [])
        self.assertEqual(production_instruction, "")

        prompt = SERVER.build_board_prompt(
            [{
                "title": "出门",
                "concept": "爸爸牵着七岁乐乐去公园放风筝",
                "elements": ["爸爸背着风筝", "七岁乐乐牵着爸爸", "公园入口"],
                "text": "周六早晨，爸爸答应带七岁的乐乐去公园放风筝。",
            }],
            SERVER.CLEAR_STORYBOOK_STYLE,
            aspect_ratio="3:4",
            presentation_mode="story-color",
        )
        self.assertIn("纯白面积不少于 80%", prompt)
        self.assertIn("成年人约 5～6 头身", prompt)
        self.assertNotIn("参考图说明", prompt)
        self.assertNotIn("参考图已经提供完整视觉样式", prompt)
        self.assertIn("内容约束决定画什么；视觉配方决定如何画，二者必须同时满足", prompt)
        self.assertNotIn("优先级高于风格修饰", prompt)
        self.assertIn("爸爸背着风筝", prompt)
        self.assertIn(SERVER.IDENTITY_PROMPTS["consistent"], prompt)

    def test_clear_storybook_prompt_preview_uses_text_recipe_without_style_image(self) -> None:
        preview = SERVER.preview_style_prompt({
            "page_mode": "standard",
            "style": SERVER.CLEAR_STORYBOOK_STYLE,
            "scenes_per_image": 1,
            "aspect_ratio": "3:4",
            "presentation_mode": "story-color",
        })
        self.assertNotIn("清透日系生活绘本视觉语言参考", preview["full_prompt"])
        self.assertNotIn("参考图已经提供完整视觉样式", preview["full_prompt"])
        self.assertIn("纯白面积不少于 80%", preview["full_prompt"])
        self.assertFalse(preview["truncated"])

    def test_clear_storybook_board_spec_uses_cast_character_without_style_image(self) -> None:
        from PIL import Image

        job_id = "clear-board-spec"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 20).convert("RGB").save(job_dir / "library-character-01.png")
        SERVER.JOBS[job_id] = {
            **self.job(job_id),
            "style": SERVER.CLEAR_STORYBOOK_STYLE,
            "aspect_ratio": "3:4",
            "presentation_mode": "story-color",
            "character_bindings": [{
                "role_id": "role_01", "story_name": "乐乐", "description": "七岁短发女孩",
                "image": "library-character-01.png",
            }],
        }
        board = [{"concept": "乐乐撑伞回家", "elements": ["乐乐撑伞"], "text": "乐乐走进雨里。", "cast_ids": ["role_01"]}]
        images, instruction, prompt = SERVER.build_board_generation_spec(
            job_id, board, SERVER.CLEAR_STORYBOOK_STYLE, False, "3:4", "story-color", "consistent",
        )
        self.assertEqual([path.name for path in images], ["library-character-01.png"])
        self.assertIn("输入图1定义人物“乐乐”", instruction)
        self.assertNotIn("清透日系生活绘本视觉语言参考", instruction)
        self.assertIn("视觉配方：", prompt)
        self.assertIn("输入图1定义人物“乐乐”", prompt)
        self.assertNotIn("严格复现输入风格参考图", prompt)

    def test_character_only_references_do_not_masquerade_as_a_style_reference(self) -> None:
        from PIL import Image

        job_id = "retro-character-only"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 20).convert("RGB").save(job_dir / "library-character-01.png")
        SERVER.JOBS[job_id] = {
            **self.job(job_id),
            "style": "复古报纸拼贴风",
            "character_bindings": [{
                "role_id": "role_01", "story_name": "我", "description": "青年女性，黑色直发",
                "image": "library-character-01.png",
            }],
        }
        board = [{"concept": "我站在门口", "elements": ["我挥手"], "text": "我回来了。", "cast_ids": ["role_01"]}]
        images, instruction, prompt = SERVER.build_board_generation_spec(
            job_id, board, "复古报纸拼贴风", False, "3:4", "story-color", "consistent",
        )
        self.assertEqual([path.name for path in images], ["library-character-01.png"])
        self.assertIn("输入图1定义人物“我”", instruction)
        self.assertIn("视觉配方：", prompt)
        self.assertNotIn("严格复现输入风格参考图", prompt)

    def test_clear_storybook_recipe_has_a_version_for_automatic_upgrade(self) -> None:
        self.assertEqual(SERVER.style_recipe_version(SERVER.CLEAR_STORYBOOK_STYLE), "clear-storybook-text-v2")

    def test_old_clear_storybook_regeneration_auto_upgrades_prompt_and_keeps_cast_image(self) -> None:
        from PIL import Image

        job_id = "clear-auto-upgrade"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        scene = {"concept": "乐乐撑伞回家", "elements": ["乐乐撑伞"], "text": "乐乐走进雨里。", "cast_ids": ["role_01"], "key_text": "雨中回家"}
        (job_dir / "plan.json").write_text(json.dumps([scene], ensure_ascii=False), encoding="utf-8")
        (job_dir / "boards.json").write_text(json.dumps([{"scene_numbers": [1], "image_prompt": "旧版日系提示词"}], ensure_ascii=False), encoding="utf-8")
        Image.effect_noise((128, 128), 10).convert("RGB").save(job_dir / "board-01.png")
        Image.effect_noise((128, 128), 20).convert("RGB").save(job_dir / "board-01.source.png")
        Image.effect_noise((128, 128), 30).convert("RGB").save(job_dir / "library-character-01.png")
        SERVER.JOBS[job_id] = {
            **self.job(job_id),
            "status": "done",
            "style": SERVER.CLEAR_STORYBOOK_STYLE,
            "aspect_ratio": "3:4",
            "presentation_mode": "story-color",
            "include_key_text": False,
            "character_bindings": [{
                "role_id": "role_01", "story_name": "乐乐", "description": "七岁短发女孩",
                "image": "library-character-01.png",
            }],
        }
        captured = {}

        def fake_generate(_config, prompt, target, reference_images, *_args):
            captured["prompt"] = prompt
            captured["references"] = [path.name for path in reference_images]
            Image.effect_noise((128, 128), 40).convert("RGB").save(target)

        with mock.patch.object(SERVER, "load_config", return_value={"image_model": "gpt-image-2"}), mock.patch.object(SERVER, "generate_image", side_effect=fake_generate):
            SERVER.regenerate_board_image(job_id, 1, "旧版日系提示词")

        self.assertEqual(captured["references"], ["library-character-01.png"])
        self.assertIn("视觉配方：", captured["prompt"])
        self.assertNotIn("清透日系生活绘本视觉语言参考", captured["prompt"])
        self.assertEqual(SERVER.JOBS[job_id]["style_recipe_version"], "clear-storybook-text-v2")
        self.assertEqual(SERVER.JOBS[job_id]["image_generation_audit"]["board-01"]["reference_images"], ["library-character-01.png"])
        saved = json.loads((job_dir / "boards.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(saved["image_prompt"], captured["prompt"])
        self.assertEqual(saved["reference_images"], ["library-character-01.png"])

    def test_manual_prompt_edit_wins_over_clear_storybook_auto_upgrade(self) -> None:
        from PIL import Image

        job_id = "clear-manual-prompt"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        scene = {"concept": "女孩站在门口", "elements": ["女孩挥手"], "text": "她回来了。", "cast_ids": []}
        (job_dir / "plan.json").write_text(json.dumps([scene], ensure_ascii=False), encoding="utf-8")
        (job_dir / "boards.json").write_text(json.dumps([{"scene_numbers": [1], "image_prompt": "旧版提示词"}], ensure_ascii=False), encoding="utf-8")
        Image.effect_noise((128, 128), 10).convert("RGB").save(job_dir / "board-01.png")
        SERVER.JOBS[job_id] = {**self.job(job_id), "status": "done", "style": SERVER.CLEAR_STORYBOOK_STYLE, "include_key_text": False}
        captured = {}

        def fake_generate(_config, prompt, target, _reference_images, *_args):
            captured["prompt"] = prompt
            Image.effect_noise((128, 128), 20).convert("RGB").save(target)

        with mock.patch.object(SERVER, "load_config", return_value={"image_model": "gpt-image-2"}), mock.patch.object(SERVER, "generate_image", side_effect=fake_generate):
            SERVER.regenerate_board_image(job_id, 1, "我手动改写的提示词")
        self.assertEqual(captured["prompt"], "我手动改写的提示词")

    def test_new_clear_storybook_job_persists_current_recipe_version(self) -> None:
        response = TestClient(SERVER.app).post("/api/jobs", data={
            "copy": "女孩下班后撑着雨伞走回家，路灯照亮了门前的一小片路。",
            "voice_mode": "none",
            "style": SERVER.CLEAR_STORYBOOK_STYLE,
            "character_bindings": "[]",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(SERVER.JOBS[response.json()["id"]]["style_recipe_version"], "clear-storybook-text-v2")

    def test_character_redraw_archives_approved_sheet_before_review(self) -> None:
        from PIL import Image

        asset_id = "abcdef123456"
        asset_dir = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.CLEAR_STORYBOOK_STYLE) / asset_id
        asset_dir.mkdir(parents=True)
        Image.effect_noise((128, 128), 10).convert("RGB").save(asset_dir / "character-sheet.png")
        (asset_dir / "asset.json").write_text(json.dumps({
            "id": asset_id,
            "style": SERVER.CLEAR_STORYBOOK_STYLE,
            "label": "青年女",
            "description": "青年女性，黑色中长发，温和自然",
            "status": "approved",
            "image": "character-sheet.png",
        }, ensure_ascii=False), encoding="utf-8")

        def fake_generate(_config, _prompt, target, _reference_images, *_args):
            Image.effect_noise((128, 128), 40).convert("RGB").save(target)

        with mock.patch.object(SERVER, "load_config", return_value={}), mock.patch.object(SERVER, "generate_image", side_effect=fake_generate):
            SERVER.draw_character_asset(asset_id)

        item = json.loads((asset_dir / "asset.json").read_text(encoding="utf-8"))
        self.assertEqual(item["status"], "review")
        self.assertEqual(item["style_recipe_version"], "clear-storybook-text-v2")
        self.assertEqual(len(list((asset_dir / "revisions").glob("character-sheet-*.png"))), 1)

    def test_style_rebuild_queues_only_outdated_existing_character_sheets(self) -> None:
        from PIL import Image

        style_root = SERVER.CHARACTER_LIBRARY_DIR / SERVER.character_style_key(SERVER.CLEAR_STORYBOOK_STYLE)
        for asset_id, version in (("aaaaaaaaaaaa", ""), ("bbbbbbbbbbbb", "clear-storybook-text-v2")):
            asset_dir = style_root / asset_id
            asset_dir.mkdir(parents=True)
            Image.effect_noise((128, 128), 20).convert("RGB").save(asset_dir / "character-sheet.png")
            (asset_dir / "asset.json").write_text(json.dumps({
                "id": asset_id, "style": SERVER.CLEAR_STORYBOOK_STYLE, "label": asset_id,
                "description": "青年角色，黑色短发，普通日常衣着", "status": "approved",
                "image": "character-sheet.png", "style_recipe_version": version,
            }, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(SERVER, "start_character_asset_worker") as start:
            response = TestClient(SERVER.app).post("/api/character-assets/rebuild-style", json={"style": SERVER.CLEAR_STORYBOOK_STYLE})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["queued"], ["aaaaaaaaaaaa"])
        self.assertEqual(start.call_count, 1)
        outdated = json.loads((style_root / "aaaaaaaaaaaa" / "asset.json").read_text(encoding="utf-8"))
        current = json.loads((style_root / "bbbbbbbbbbbb" / "asset.json").read_text(encoding="utf-8"))
        self.assertTrue(outdated["rebuild_pending"])
        self.assertEqual(outdated["status"], "approved")
        self.assertNotIn("rebuild_pending", current)

    def test_identity_modes_are_mutually_exclusive_in_image_prompts(self) -> None:
        scene = [{"title": "相遇", "concept": "主角走进房间", "elements": ["主角推门"], "text": "主角回来了。"}]
        prompts = {
            mode: SERVER.build_board_prompt(scene, SERVER.DEFAULT_STYLE, identity_mode=mode)
            for mode in ("consistent", "male", "female")
        }
        self.assertIn(SERVER.IDENTITY_PROMPTS["consistent"], prompts["consistent"])
        self.assertIn(SERVER.IDENTITY_PROMPTS["male"], prompts["male"])
        self.assertIn(SERVER.IDENTITY_PROMPTS["female"], prompts["female"])
        for mode, prompt in prompts.items():
            for other_mode, other_prompt in SERVER.IDENTITY_PROMPTS.items():
                if other_mode != mode:
                    self.assertNotIn(other_prompt, prompt)

    def test_consistent_identity_mode_removes_the_legacy_long_paragraph(self) -> None:
        removed_text = (
            "同一角色跨分镜保持身份、基础脸型、眼睛形状、发色和标志性特征一致。"
            "年龄、身高、体型、发型、服装和当前状态默认延续上一分镜；只有原文明示或剧情必然包含时间跳跃、成长、衰老、换装、受伤等变化时才允许更新。"
            "发生变化时，只改变剧情要求改变的属性，其余身份锚点必须保留，确保仍能一眼认出是同一个人。"
        )
        self.assertEqual(SERVER.IDENTITY_PROMPTS["consistent"], "不得因为地点、动作或镜头变化而重新设计角色。")
        preview = SERVER.preview_style_prompt({"page_mode": "standard", "style": SERVER.DEFAULT_STYLE})
        self.assertNotIn(removed_text, preview["full_prompt"])
        self.assertNotIn(removed_text, preview["sent_prompt"])
        self.assertIn("输入图1定义人物“{{角色名称}}”（{{role_id}}）", preview["full_prompt"])
        self.assertIn("锁定身份、脸型、五官、发型、年龄体型和标志特征", preview["full_prompt"])
        self.assertIn("只使用人物参考组中定义的角色", preview["full_prompt"])

    def test_identity_mode_defaults_to_consistent_and_persists_in_job_parameters(self) -> None:
        with TestClient(SERVER.app) as client:
            response = client.post("/api/jobs", data={
                "copy": "这是一段用来验证默认人物身份策略的完整测试文案。",
                "voice_mode": "none",
            })
            self.assertEqual(response.status_code, 200, response.text)
            job_id = response.json()["id"]
            self.assertEqual(SERVER.JOBS[job_id]["identity_mode"], "consistent")
            parameters = client.get(f"/api/jobs/{job_id}/parameters")
        self.assertEqual(parameters.status_code, 200, parameters.text)
        self.assertEqual(parameters.json()["identity_mode"], "consistent")

    def test_specialized_codex_review_model_is_not_a_text_candidate(self) -> None:
        catalog = SERVER.build_model_catalog(
            {"gpt-5.4", "codex-auto-review", "text-embedding-3-small", "gpt-image-2"},
            "gpt-5.4",
            "gpt-image-2",
        )
        self.assertEqual(catalog["text_models"], ["gpt-5.4"])

    def test_model_stage_does_not_block_on_a_live_preflight_request(self) -> None:
        source = inspect.getsource(SERVER.model_stage)
        self.assertNotIn("verify_text_model", source)
        self.assertNotIn("select_working_text_model", source)

    def test_snapshot_keeps_reference_summary_private(self) -> None:
        job_id = "reference-snapshot"
        metadata = self.job(job_id)
        metadata.update(reference_mode="custom", character_count=2, visual_references={"style_image": "secret-name.png"})
        SERVER.JOBS[job_id] = metadata
        snapshot = SERVER.job_snapshot(job_id)
        self.assertEqual(snapshot["reference_mode"], "custom")
        self.assertEqual(snapshot["character_count"], 2)
        self.assertNotIn("visual_references", snapshot)

    def test_failed_snapshot_can_be_retried(self) -> None:
        job_id = "failed-snapshot"
        metadata = self.job(job_id)
        metadata.update(status="error", error="temporary model failure")
        SERVER.JOBS[job_id] = metadata
        self.assertTrue(SERVER.job_snapshot(job_id)["can_retry"])

    def test_manual_retry_requeues_same_job(self) -> None:
        job_id = "manual-retry"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        metadata = self.job(job_id)
        metadata.update(status="error", error="model failed", finished_at=2.0)
        SERVER.JOBS[job_id] = metadata
        captured = []
        original = SERVER.enqueue_job_from_checkpoint
        SERVER.enqueue_job_from_checkpoint = lambda current_id, item: captured.append((current_id, item["status"]))
        try:
            request = Request({"type": "http", "client": ("198.51.100.8", 1234), "headers": []})
            snapshot = SERVER.retry_failed_job(job_id, request)
        finally:
            SERVER.enqueue_job_from_checkpoint = original
        self.assertEqual(captured, [(job_id, "queued")])
        self.assertEqual(snapshot["status"], "queued")
        self.assertEqual(snapshot["manual_retry_count"], 1)
        self.assertIsNone(snapshot.get("error"))

    def test_provider_retries_transient_502(self) -> None:
        failed = mock.Mock(is_error=True, status_code=502, text="gateway")
        succeeded = mock.Mock(is_error=False, status_code=200)
        succeeded.json.return_value = {"output_text": "ok"}
        client = mock.MagicMock()
        client.__enter__.return_value.post.side_effect = [failed, failed, succeeded]
        with mock.patch.object(SERVER.httpx, "Client", return_value=client), mock.patch.object(SERVER.time, "sleep"):
            payload = SERVER.provider_post({"api_key": "test", "base_url": "https://example.test"}, "responses", {"model": "test"})
        self.assertEqual(payload["output_text"], "ok")
        self.assertEqual(client.__enter__.return_value.post.call_count, 3)

    def test_provider_does_not_retry_rate_limited_node(self) -> None:
        limited = mock.Mock(is_error=True, status_code=429, text="rate limit", headers={"Retry-After": "17"})
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = limited
        with mock.patch.object(SERVER.httpx, "Client", return_value=client), mock.patch.object(SERVER.time, "sleep") as sleep:
            with self.assertRaises(SERVER.ProviderHTTPError) as raised:
                SERVER.provider_post({"api_key": "test", "base_url": "https://example.test"}, "responses", {"model": "test"})
        self.assertEqual(client.__enter__.return_value.post.call_count, 1)
        self.assertEqual(raised.exception.retry_after, 17)
        sleep.assert_not_called()

    def test_image_node_drops_to_one_after_429_and_recovers_by_stable_tier(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "adaptive.json",
            3,
            window_seconds=0,
            promotion_window_seconds=0,
            promotion_successes=3,
        )
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 5}
        with self.assertRaises(SERVER.ProviderHTTPError):
            pool.call(
                config,
                lambda: (_ for _ in ()).throw(SERVER.ProviderHTTPError(429, "rate limited", retry_after=12)),
                retry_rate_limit=False,
                skip_cooldown=False,
            )
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["rpm"], 1)
        self.assertEqual(snapshot["rate_limit_count"], 1)
        self.assertGreaterEqual(snapshot["cooldown_seconds"], 11)
        self.assertNotIn("secret", json.dumps(snapshot))

        with pool.condition:
            pool.states[pool.node_key(config)]["cooldown_until"] = 0
        for _ in range(3):
            pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        self.assertEqual(pool.snapshot()[0]["rpm"], 3)
        for _ in range(3):
            pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        recovered = pool.snapshot()[0]
        self.assertEqual(recovered["rpm"], 5)
        self.assertEqual(recovered["success_count"], 6)

    def test_image_node_rpm_paces_starts_without_waiting_for_responses(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "shared.json", 3, window_seconds=0.12)
        config = {"id": "shared", "base_url": "https://relay.example/v1", "api_key": "secret"}
        release = threading.Event()
        lock = threading.Lock()
        active = 0
        starts: list[float] = []

        def invoke() -> dict:
            nonlocal active
            with lock:
                active += 1
                starts.append(time.monotonic())
            release.wait(2)
            with lock:
                active -= 1
            return {"ok": True}

        threads = [threading.Thread(target=lambda: pool.call(config, invoke, retry_rate_limit=False, skip_cooldown=False)) for _ in range(4)]
        for thread in threads:
            thread.start()
        deadline = time.time() + 2
        while time.time() < deadline:
            with lock:
                if active == 4:
                    break
            time.sleep(0.01)
        with lock:
            captured_starts = list(starts)
            captured_active = active
        release.set()
        for thread in threads:
            thread.join(2)
        self.assertEqual(captured_active, 4)
        self.assertEqual(len(captured_starts), 4)
        self.assertTrue(all(later - earlier >= 0.025 for earlier, later in zip(captured_starts, captured_starts[1:])))

    def test_image_nodes_actively_combine_independent_rpm_capacity(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "multi.json",
            3,
            window_seconds=0.12,
            global_rpm_limit=60,
        )
        configs = [
            {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "rpm_limit": 10},
            {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "rpm_limit": 10},
        ]
        release = threading.Event()
        started: list[str] = []
        lock = threading.Lock()

        def invoke(service: dict) -> dict:
            with lock:
                started.append(service["id"])
            release.wait(2)
            return {"ok": True}

        threads = [threading.Thread(target=lambda: pool.call_any(configs, invoke)) for _ in range(2)]
        for thread in threads:
            thread.start()
        deadline = time.time() + 1
        while time.time() < deadline:
            with lock:
                if len(started) == 2:
                    break
            time.sleep(0.01)
        with lock:
            selected = set(started)
        release.set()
        for thread in threads:
            thread.join(2)
        self.assertEqual(selected, {"first", "second"})

    def test_image_scheduler_releases_waiters_in_fifo_order(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "fifo.json",
            3,
            window_seconds=0,
            minimum_in_flight_limit=1,
            in_flight_minutes=0,
            global_in_flight_limit=1,
        )
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 3}
        permits = threading.Semaphore(0)
        starts: list[str] = []
        lock = threading.Lock()

        def worker(label: str) -> None:
            def invoke() -> dict:
                with lock:
                    starts.append(label)
                permits.acquire(timeout=2)
                return {"ok": True}

            pool.call(config, invoke, retry_rate_limit=False, skip_cooldown=False)

        threads: list[threading.Thread] = []
        for index, label in enumerate(("first", "second", "third")):
            thread = threading.Thread(target=worker, args=(label,))
            threads.append(thread)
            thread.start()
            deadline = time.time() + 1
            if index == 0:
                while time.time() < deadline:
                    with lock:
                        if starts == ["first"]:
                            break
                    time.sleep(0.005)
            else:
                while time.time() < deadline and pool.overview()["waiting"] < index:
                    time.sleep(0.005)

        for _ in threads:
            permits.release()
            time.sleep(0.03)
        for thread in threads:
            thread.join(2)
        self.assertEqual(starts, ["first", "second", "third"])

    def test_second_rate_limit_strike_forces_one_rpm_and_circuit_breaker(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "strikes.json", 3, window_seconds=0)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        with pool.condition:
            _key, state = pool._state(config)
            state["rpm"] = 10
        for strike in range(2):
            with self.assertRaises(SERVER.ProviderHTTPError):
                pool.call(
                    config,
                    lambda: (_ for _ in ()).throw(SERVER.ProviderHTTPError(429, "rate limited", retry_after=1)),
                    retry_rate_limit=False,
                    skip_cooldown=False,
                )
            if strike == 0:
                first = pool.snapshot()[0]
                self.assertEqual(first["rpm"], 5)
                self.assertEqual(first["rate_limit_strikes"], 1)
                with pool.condition:
                    state["cooldown_until"] = 0
                    state["next_request_at"] = 0
        second = pool.snapshot()[0]
        self.assertEqual(second["rpm"], 1)
        self.assertEqual(second["rate_limit_strikes"], 2)
        self.assertEqual(second["circuit_reason"], "rate_limit")
        self.assertGreaterEqual(second["cooldown_seconds"], 899)

    def test_failed_eight_rpm_tier_is_locked_at_five_for_thirty_minutes(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "tier-memory.json", 3, window_seconds=0)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        with pool.condition:
            key, state = pool._state(config)
            state["rpm"] = 8
            state["in_flight"] = 1
            pool.global_in_flight = 1
        pool._record_failure(key, SERVER.ProviderHTTPError(429, "limited"), None, attempted_rpm=8)
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["rpm"], 5)
        self.assertEqual(snapshot["effective_rpm_limit"], 5)
        self.assertEqual(snapshot["failed_tier"], 8)
        self.assertEqual(snapshot["tier_failure_count"], 1)
        self.assertGreaterEqual(snapshot["tier_lock_seconds"], 1799)
        self.assertTrue(snapshot["recovery_mode"])
        self.assertEqual(snapshot["promotion_required_seconds"], 1800)
        self.assertEqual(snapshot["promotion_required_successes"], 100)

    def test_repeated_high_tier_failures_lock_six_hours_then_cap_until_restart(self) -> None:
        stats = Path(self.temporary.name) / "tier-repeat.json"
        pool = SERVER.AdaptiveImageNodePool(stats, 3, window_seconds=0)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        with pool.condition:
            key, state = pool._state(config)
        for failure_number in range(1, 4):
            with pool.condition:
                state["in_flight"] += 1
                pool.global_in_flight += 1
            pool._record_failure(key, SERVER.ProviderHTTPError(429, "limited"), None, attempted_rpm=8)
            snapshot = pool.snapshot()[0]
            self.assertEqual(snapshot["tier_failure_count"], failure_number)
            if failure_number == 2:
                self.assertGreaterEqual(snapshot["tier_lock_seconds"], 21599)
                self.assertFalse(snapshot["runtime_rpm_capped"])
        capped = pool.snapshot()[0]
        self.assertTrue(capped["runtime_rpm_capped"])
        self.assertEqual(capped["effective_rpm_limit"], 5)

        restarted = SERVER.AdaptiveImageNodePool(stats, 3, window_seconds=0)
        with restarted.condition:
            restarted._state(config)
        after_restart = restarted.snapshot()[0]
        self.assertFalse(after_restart["runtime_rpm_capped"])
        self.assertEqual(after_restart["tier_failure_count"], 0)
        self.assertEqual(after_restart["effective_rpm_limit"], 10)

    def test_high_tier_failure_older_than_six_hours_does_not_count_again(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "tier-expiry.json", 3, window_seconds=0)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        with pool.condition:
            key, state = pool._state(config)
            state["rpm"] = 8
            state["failed_tier_failure_times"] = [time.monotonic() - 21601]
            state["failed_tier"] = 8
            state["in_flight"] = 1
            pool.global_in_flight = 1
        pool._record_failure(key, SERVER.ProviderHTTPError(429, "limited"), None, attempted_rpm=8)
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["tier_failure_count"], 1)
        self.assertGreaterEqual(snapshot["tier_lock_seconds"], 1799)
        self.assertLess(snapshot["tier_lock_seconds"], 1801)

    def test_failed_tier_memory_is_isolated_per_image_node(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "tier-isolation.json", 3, window_seconds=0)
        first = {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "rpm_limit": 10}
        second = {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "rpm_limit": 10}
        with pool.condition:
            first_key, first_state = pool._state(first)
            _second_key, second_state = pool._state(second)
            first_state["rpm"] = 8
            second_state["rpm"] = 8
            first_state["in_flight"] = 1
            pool.global_in_flight = 1
        pool._record_failure(first_key, SERVER.ProviderHTTPError(429, "limited"), None, attempted_rpm=8)
        snapshots = {item["node_id"]: item for item in pool.snapshot()}
        self.assertEqual(snapshots["first"]["effective_rpm_limit"], 5)
        self.assertEqual(snapshots["second"]["effective_rpm_limit"], 10)
        self.assertEqual(snapshots["second"]["tier_failure_count"], 0)

    def test_recovery_promotion_requires_the_stricter_observation_threshold(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "tier-recovery.json",
            3,
            window_seconds=0,
            promotion_window_seconds=0,
            promotion_successes=1,
            recovery_window_seconds=0,
            recovery_successes=3,
        )
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        with pool.condition:
            key, state = pool._state(config)
            state["rpm"] = 8
            state["in_flight"] = 1
            pool.global_in_flight = 1
        pool._record_failure(key, SERVER.ProviderHTTPError(429, "limited"), None, attempted_rpm=8)
        with pool.condition:
            state["cooldown_until"] = 0
            state["tier_lock_until"] = 0
            state["next_request_at"] = 0
        for _ in range(2):
            pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        self.assertEqual(pool.snapshot()[0]["rpm"], 5)
        pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        recovered = pool.snapshot()[0]
        self.assertEqual(recovered["rpm"], 8)
        self.assertFalse(recovered["recovery_mode"])

    def test_manual_reset_clears_failed_tier_memory_for_only_one_node(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "tier-reset.json", 3, window_seconds=0)
        configs = [
            {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "rpm_limit": 10},
            {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "rpm_limit": 10},
        ]
        for config in configs:
            with pool.condition:
                key, state = pool._state(config)
            for _ in range(3):
                with pool.condition:
                    state["in_flight"] += 1
                    pool.global_in_flight += 1
                pool._record_failure(key, SERVER.ProviderHTTPError(429, "limited"), None, attempted_rpm=8)
        self.assertTrue(all(item["runtime_rpm_capped"] for item in pool.snapshot()))
        self.assertTrue(pool.reset_failure_memory("first"))
        snapshots = {item["node_id"]: item for item in pool.snapshot()}
        self.assertFalse(snapshots["first"]["runtime_rpm_capped"])
        self.assertEqual(snapshots["first"]["tier_failure_count"], 0)
        self.assertTrue(snapshots["second"]["runtime_rpm_capped"])

    def test_manual_reset_endpoint_exposes_node_scoped_unlock(self) -> None:
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        with SERVER.IMAGE_NODE_POOL.condition:
            key, state = SERVER.IMAGE_NODE_POOL._state(config)
            state["failed_tier"] = 8
            state["failed_tier_failure_times"] = [time.monotonic()] * 3
            state["runtime_rpm_cap"] = 5
            state["recovery_mode"] = True
            state["recovery_target_rpm"] = 8
        response = TestClient(SERVER.app).post("/api/image-nodes/primary/reset-rpm-memory")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        snapshot = SERVER.IMAGE_NODE_POOL.snapshot()[0]
        self.assertFalse(snapshot["runtime_rpm_capped"])
        self.assertEqual(snapshot["tier_failure_count"], 0)

    def test_manual_clear_circuit_breaker_is_node_scoped_and_preserves_statistics(self) -> None:
        first = {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "rpm_limit": 10}
        second = {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "rpm_limit": 10}
        with SERVER.IMAGE_NODE_POOL.condition:
            _first_key, first_state = SERVER.IMAGE_NODE_POOL._state(first)
            _second_key, second_state = SERVER.IMAGE_NODE_POOL._state(second)
            first_state["cooldown_until"] = time.monotonic() + 3600
            first_state["circuit_reason"] = "authentication"
            first_state["rate_limit_count"] = 4
            first_state["last_status"] = 403
            second_state["cooldown_until"] = time.monotonic() + 300
            second_state["circuit_reason"] = "unavailable"

        response = TestClient(SERVER.app).post("/api/image-nodes/first/clear-circuit-breaker")

        self.assertEqual(response.status_code, 200)
        snapshots = {item["node_id"]: item for item in SERVER.IMAGE_NODE_POOL.snapshot()}
        self.assertEqual(snapshots["first"]["cooldown_seconds"], 0)
        self.assertEqual(snapshots["first"]["circuit_reason"], "")
        self.assertEqual(snapshots["first"]["rate_limit_count"], 4)
        self.assertEqual(snapshots["first"]["last_status"], 403)
        self.assertGreater(snapshots["second"]["cooldown_seconds"], 0)
        self.assertEqual(snapshots["second"]["circuit_reason"], "unavailable")

    def test_image_node_promotes_only_one_tier_after_stable_window(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "promotion.json",
            3,
            window_seconds=0,
            promotion_window_seconds=0,
            promotion_successes=3,
        )
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        for _ in range(3):
            pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["rpm"], 5)
        self.assertEqual(snapshot["tier_successes"], 0)

    def test_image_node_never_promotes_above_ten_rpm(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "maximum.json",
            3,
            window_seconds=0,
            max_rpm=10,
            promotion_window_seconds=0,
            promotion_successes=1,
        )
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 999}
        for _ in range(8):
            pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["rpm"], 10)
        self.assertEqual(snapshot["rpm_limit"], 10)

    def test_three_consecutive_503s_open_five_minute_circuit_without_lowering_rpm(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "unavailable.json", 3, window_seconds=0)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 10}
        for attempt in range(3):
            with self.assertRaises(SERVER.ProviderHTTPError):
                pool.call(
                    config,
                    lambda: (_ for _ in ()).throw(SERVER.ProviderHTTPError(503, "unavailable")),
                    retry_rate_limit=False,
                    skip_cooldown=False,
                )
            if attempt < 2:
                with pool.condition:
                    _key, state = pool._state(config)
                    state["cooldown_until"] = 0
                    state["next_request_at"] = 0
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["rpm"], 3)
        self.assertEqual(snapshot["consecutive_unavailable"], 3)
        self.assertEqual(snapshot["circuit_reason"], "unavailable")
        self.assertGreaterEqual(snapshot["cooldown_seconds"], 299)

    def test_image_node_emergency_in_flight_limit_pauses_then_resumes(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(
            Path(self.temporary.name) / "capacity.json",
            3,
            window_seconds=0,
            minimum_in_flight_limit=2,
            in_flight_minutes=0,
            global_in_flight_limit=10,
        )
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 3}
        permits = threading.Semaphore(0)
        lock = threading.Lock()
        active = 0
        maximum = 0

        def invoke() -> dict:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            permits.acquire(timeout=2)
            with lock:
                active -= 1
            return {"ok": True}

        threads = [threading.Thread(target=lambda: pool.call(config, invoke, retry_rate_limit=False, skip_cooldown=False)) for _ in range(3)]
        for thread in threads:
            thread.start()
        deadline = time.time() + 1
        while time.time() < deadline:
            with lock:
                if active == 2:
                    break
            time.sleep(0.01)
        time.sleep(0.05)
        with lock:
            self.assertEqual(active, 2)
        permits.release()
        deadline = time.time() + 1
        while time.time() < deadline:
            with lock:
                if maximum == 2 and active == 2:
                    break
            time.sleep(0.01)
        permits.release(2)
        for thread in threads:
            thread.join(2)
        self.assertEqual(maximum, 2)

    def test_text_provider_falls_back_to_chat_completions(self) -> None:
        unsupported = mock.Mock(is_error=True, status_code=404, text="responses endpoint not found")
        succeeded = mock.Mock(is_error=False, status_code=200)
        succeeded.json.return_value = {"choices": [{"message": {"content": "连接成功"}}]}
        client = mock.MagicMock()
        client.__enter__.return_value.post.side_effect = [unsupported, succeeded]
        with mock.patch.object(SERVER.httpx, "Client", return_value=client):
            payload = SERVER.provider_text(
                {"api_key": "test", "base_url": "https://relay.example/v1"},
                "model-name",
                "只回复：连接成功",
            )
        calls = client.__enter__.return_value.post.call_args_list
        self.assertEqual(calls[0].args[0], "https://relay.example/v1/responses")
        self.assertEqual(calls[1].args[0], "https://relay.example/v1/chat/completions")
        self.assertEqual(calls[1].kwargs["json"]["messages"][0]["content"], "只回复：连接成功")
        self.assertEqual(SERVER.extract_response_text(payload), "连接成功")

    def test_provider_models_treats_missing_optional_endpoint_as_unknown(self) -> None:
        missing = mock.Mock(is_error=True, status_code=404, text="not found")
        client = mock.MagicMock()
        client.__enter__.return_value.get.return_value = missing
        with mock.patch.object(SERVER.httpx, "Client", return_value=client):
            self.assertEqual(
                SERVER.provider_models({"api_key": "test", "base_url": "https://relay.example/v1"}),
                set(),
            )

    def test_provider_models_reuses_recent_catalog_without_second_network_call(self) -> None:
        response = mock.Mock(is_error=False)
        response.json.return_value = {"data": [{"id": "gpt-5.4"}, {"id": "gpt-image-2"}]}
        client = mock.MagicMock()
        client.__enter__.return_value.get.return_value = response
        config = {"api_key": "test", "base_url": "https://relay.example/v1"}
        with mock.patch.object(SERVER.httpx, "Client", return_value=client):
            first = SERVER.provider_models(config)
            second = SERVER.provider_models(config)
        self.assertEqual(first, {"gpt-5.4", "gpt-image-2"})
        self.assertEqual(second, first)
        self.assertEqual(client.__enter__.return_value.get.call_count, 1)

    def test_detect_models_reads_catalog_without_sending_generation_probe(self) -> None:
        with mock.patch.object(SERVER, "provider_models", return_value={"gpt-5.4", "gpt-5.5"}) as models, mock.patch.object(
            SERVER, "provider_text_once"
        ) as generate:
            catalog = SERVER.detect_models({"api_key": "test", "base_url": "https://relay.example/v1", "text_model": "gpt-5.4"})
        self.assertEqual(catalog["text_models"], ["gpt-5.4"])
        self.assertEqual(catalog["selected_text_model"], "gpt-5.4")
        self.assertGreaterEqual(models.call_count, 1)
        generate.assert_not_called()

    def test_text_provider_switches_to_next_enabled_relay_after_rate_limit(self) -> None:
        limited = SERVER.ProviderHTTPError(429, "Upstream rate limit exceeded")
        config = {
            "text_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-5.4", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-5.6-luna", "enabled": True},
            ]
        }
        with mock.patch.object(SERVER, "provider_text_once", side_effect=[limited, {"model": "gpt-5.6-luna", "output_text": "OK"}]) as request:
            result = SERVER.provider_text(config, "ignored", "hello")
        self.assertEqual(result["output_text"], "OK")
        self.assertEqual([call.args[0]["base_url"] for call in request.call_args_list], ["https://one.example/v1", "https://two.example/v1"])
        self.assertEqual([call.args[1] for call in request.call_args_list], ["gpt-5.4", "gpt-5.6-luna"])

    def test_image_provider_switches_to_next_enabled_relay_after_failure(self) -> None:
        unavailable = SERVER.ProviderHTTPError(503, "Service temporarily unavailable")
        config = {
            "image_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-image-1", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-image-2", "enabled": True},
            ]
        }
        with mock.patch.object(SERVER, "provider_image_single", side_effect=[unavailable, {"data": [{"url": "ok"}]}]) as request:
            result = SERVER.provider_image(config, "images/generations", {"prompt": "hello"})
        self.assertEqual(result["data"][0]["url"], "ok")
        self.assertEqual([call.args[0]["base_url"] for call in request.call_args_list], ["https://one.example/v1", "https://two.example/v1"])
        self.assertEqual([call.args[2]["model"] for call in request.call_args_list], ["gpt-image-1", "gpt-image-2"])

    def test_reference_image_provider_switches_to_next_enabled_relay(self) -> None:
        unavailable = SERVER.ProviderHTTPError(503, "Service temporarily unavailable")
        config = {
            "image_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-image-1", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-image-2", "enabled": True},
            ]
        }
        with mock.patch.object(SERVER, "provider_image_edit_once", side_effect=[unavailable, {"data": [{"url": "ok"}]}]) as request:
            result = SERVER.provider_image_edit(config, {"model": "ignored", "prompt": "hello"}, [("ref.png", b"png", "image/png")])
        self.assertEqual(result["data"][0]["url"], "ok")
        self.assertEqual([call.args[0]["base_url"] for call in request.call_args_list], ["https://one.example/v1", "https://two.example/v1"])
        self.assertEqual([call.args[1]["model"] for call in request.call_args_list], ["gpt-image-1", "gpt-image-2"])

    def test_relay_plan_reports_configured_ready_and_skipped_nodes(self) -> None:
        config = {
            "text_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-5.5", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-5.2", "enabled": True},
                {"id": "third", "base_url": "https://three.example/v1", "api_key": "", "model": "gpt-5", "enabled": True},
            ]
        }
        plan = SERVER.provider_service_plan(config, "text")
        self.assertEqual(plan["configured_count"], 3)
        self.assertEqual(plan["ready_count"], 2)
        self.assertEqual([item["position"] for item in plan["ready"]], [1, 2])
        self.assertEqual(plan["skipped"], [{"position": 3, "reason": "缺少 API Key"}])

    def test_image_relay_plan_clamps_each_node_rpm_limit(self) -> None:
        plan = SERVER.provider_service_plan({
            "image_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-image-2", "enabled": True, "rpm_limit": 5},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-image-2", "enabled": True, "rpm_limit": 999},
            ]
        }, "image")
        self.assertEqual([item["service"]["rpm_limit"] for item in plan["ready"]], [5, 300])

    def test_image_relay_plan_defaults_legacy_nodes_to_ten_rpm(self) -> None:
        plan = SERVER.provider_service_plan({
            "image_services": [
                {"id": "legacy", "base_url": "https://relay.example/v1", "api_key": "secret", "model": "gpt-image-2", "enabled": True},
            ]
        }, "image")

        self.assertEqual(plan["ready"][0]["service"]["rpm_limit"], 10)

    def test_high_capacity_plan_preserves_documented_rpm_rpd_and_safety_margin(self) -> None:
        plan = SERVER.provider_service_plan({
            "image_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-image-2", "enabled": True, "rpm_limit": 90, "rpd_limit": 1600, "utilization_percent": 80},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-image-2", "enabled": True, "rpm_limit": 110, "rpd_limit": 1800, "utilization_percent": 80},
            ]
        }, "image")
        services = [item["service"] for item in plan["ready"]]
        self.assertEqual([item["rpm_limit"] for item in services], [90, 110])
        self.assertEqual([item["rpd_limit"] for item in services], [1600, 1800])
        self.assertEqual([item["utilization_percent"] for item in services], [80, 80])

    def test_high_capacity_node_starts_at_safety_adjusted_target(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "high-capacity.json", 3, window_seconds=0, max_rpm=300)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 110, "rpd_limit": 1800, "utilization_percent": 80}
        pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        snapshot = pool.snapshot()[0]
        self.assertEqual(snapshot["rpm"], 88)
        self.assertEqual(snapshot["safe_rpm_target"], 88)
        self.assertEqual(snapshot["daily_budget"], 1440)
        self.assertEqual(snapshot["daily_used"], 1)
        self.assertEqual(snapshot["daily_remaining"], 1439)

    def test_image_dispatch_status_reports_each_real_node_and_runtime_rpm(self) -> None:
        job_id = "image-dispatch-status"
        SERVER.JOBS[job_id] = {**self.job(job_id), "status": "running", "current_phase": "images", "boards": 18, "completed_boards": 0}
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "dispatch-status.json", 3, window_seconds=0, max_rpm=300)
        configs = [
            {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "rpm_limit": 50, "rpd_limit": 800, "utilization_percent": 80, "_position": 1},
            {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "rpm_limit": 90, "rpd_limit": 1600, "utilization_percent": 80, "_position": 2},
        ]

        def invoke(service: dict) -> dict:
            if service["id"] == "first":
                raise SERVER.ProviderHTTPError(503, "temporarily unavailable")
            return {"ok": True}

        self.assertEqual(pool.call_any(configs, invoke, job_id=job_id), {"ok": True})
        activity = SERVER.JOBS[job_id]["image_node_activity"]
        self.assertEqual(activity["1"]["submitted"], 1)
        self.assertEqual(activity["1"]["failed"], 1)
        self.assertEqual(activity["2"]["submitted"], 1)
        self.assertEqual(activity["2"]["responses"], 1)
        self.assertIn("节点 1 40 RPM", SERVER.JOBS[job_id]["stage"])
        self.assertIn("节点 2 72 RPM", SERVER.JOBS[job_id]["stage"])
        self.assertNotIn("图片节点 3 RPM", SERVER.JOBS[job_id]["stage"])

    def test_exhausted_daily_budget_routes_to_another_node(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "daily-routing.json", 3, window_seconds=0, max_rpm=300)
        configs = [
            {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "rpm_limit": 90, "rpd_limit": 1, "utilization_percent": 100},
            {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "rpm_limit": 110, "rpd_limit": 1800, "utilization_percent": 80},
        ]
        selected: list[str] = []
        for _ in range(2):
            pool.call_any(configs, lambda service: selected.append(service["id"]) or {"ok": True})
        self.assertEqual(selected, ["first", "second"])
        snapshots = {item["node_id"]: item for item in pool.snapshot()}
        self.assertTrue(snapshots["first"]["daily_exhausted"])
        self.assertEqual(snapshots["first"]["daily_remaining"], 0)

    def test_all_daily_budgets_exhausted_fail_fast_instead_of_spinning(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "daily-stop.json", 3, window_seconds=0, max_rpm=300)
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 90, "rpd_limit": 1, "utilization_percent": 100}
        pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        started = time.monotonic()
        with self.assertRaisesRegex(SERVER.ImageDailyQuotaExhausted, "日请求安全额度"):
            pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        self.assertLess(time.monotonic() - started, 0.2)

    def test_runtime_global_capacity_can_be_changed_without_restart(self) -> None:
        pool = SERVER.AdaptiveImageNodePool(Path(self.temporary.name) / "global-console.json", 3, window_seconds=0, max_rpm=300, global_rpm_limit=200, global_in_flight_limit=80)
        pool.configure(global_rpm_limit=150, global_in_flight_limit=120)
        overview = pool.overview()
        self.assertEqual(overview["global_rpm_limit"], 150)
        self.assertEqual(overview["global_in_flight_limit"], 120)

    def test_daily_usage_persists_and_resets_on_a_new_local_day(self) -> None:
        stats = Path(self.temporary.name) / "daily-persist.json"
        config = {"id": "primary", "base_url": "https://relay.example/v1", "api_key": "secret", "rpm_limit": 90, "rpd_limit": 1600, "utilization_percent": 80}
        pool = SERVER.AdaptiveImageNodePool(stats, 3, window_seconds=0, max_rpm=300)
        pool.call(config, lambda: {"ok": True}, retry_rate_limit=False, skip_cooldown=False)
        restarted = SERVER.AdaptiveImageNodePool(stats, 3, window_seconds=0, max_rpm=300)
        with restarted.condition:
            _key, state = restarted._state(config)
            self.assertEqual(state["daily_used"], 1)
            state["daily_date"] = "2000-01-01"
        restarted.snapshot()
        self.assertEqual(restarted.snapshot()[0]["daily_used"], 0)

    def test_text_relay_switch_status_uses_total_configured_node_count(self) -> None:
        unavailable = SERVER.ProviderHTTPError(503, "Service temporarily unavailable")
        SERVER.JOBS["relay-status-job"] = self.job("relay-status-job")
        config = {
            "text_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-5.5", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-5.2", "enabled": True},
                {"id": "third", "base_url": "https://three.example/v1", "api_key": "", "model": "gpt-5", "enabled": True},
            ]
        }
        with mock.patch.object(SERVER, "provider_text_single", side_effect=[unavailable, {"output_text": "ok"}]):
            SERVER.provider_text(config, "ignored", "hello", job_id="relay-status-job")
        self.assertEqual(
            SERVER.JOBS["relay-status-job"]["stage"],
            "正在切换文本中转站 2/3（2 个可调用，节点 3 缺少 API Key）",
        )

    def test_image_relay_failure_lists_every_attempted_node(self) -> None:
        config = {
            "image_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-image-2", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-image-2", "enabled": True},
            ]
        }
        with mock.patch.object(
            SERVER,
            "provider_image_single",
            side_effect=[SERVER.ProviderHTTPError(429, "rate limited"), SERVER.ProviderHTTPError(503, "unavailable")],
        ):
            with self.assertRaisesRegex(RuntimeError, r"节点 1.*429.*节点 2.*503"):
                SERVER.provider_image(config, "images/generations", {"prompt": "hello"})

    def test_multiple_relays_switch_after_one_transient_attempt_per_node(self) -> None:
        unavailable = SERVER.ProviderHTTPError(503, "unavailable")
        config = {
            "text_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-5.5", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-5.2", "enabled": True},
            ],
            "image_services": [
                {"id": "first", "base_url": "https://one.example/v1", "api_key": "one", "model": "gpt-image-2", "enabled": True},
                {"id": "second", "base_url": "https://two.example/v1", "api_key": "two", "model": "gpt-image-2", "enabled": True},
            ],
        }
        with mock.patch.object(SERVER, "provider_text_single", side_effect=[unavailable, {"output_text": "ok"}]) as text_request:
            SERVER.provider_text(config, "ignored", "hello")
        with mock.patch.object(SERVER, "provider_image_single", side_effect=[unavailable, {"data": [{}]}]) as image_request:
            SERVER.provider_image(config, "images/generations", {"prompt": "hello"})
        self.assertEqual([call.kwargs["attempts"] for call in text_request.call_args_list], [1, 1])
        self.assertEqual([call.kwargs["attempts"] for call in image_request.call_args_list], [1, 1])

    def test_whiteboard_render_command_hides_drawing_hand(self) -> None:
        command = SERVER.whiteboard_render_command(
            Path("board.png"), Path("board.annotation.json"), Path("board.partial.mp4"), "detailed"
        )
        self.assertIn("--bare-tip", command)
        self.assertNotIn(str(SERVER.HAND), command)

    def test_uploaded_narration_command_normalizes_audio_without_tts(self) -> None:
        command = SERVER.uploaded_narration_command(Path("narration.mp3"), Path("voice.partial.wav"))
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("narration.mp3", command)
        self.assertIn("pcm_s16le", command)
        self.assertEqual(command[-1], "voice.partial.wav")

    def test_silent_mode_builds_an_internal_script_paced_track(self) -> None:
        copy = "这是一段无需旁白的测试文案，用来验证画面会按照文字长度安排节奏。"
        command = SERVER.silent_narration_command(copy, Path("voice.partial.wav"))
        self.assertIn("anullsrc=channel_layout=mono:sample_rate=44100", command)
        self.assertIn("-t", command)
        self.assertGreaterEqual(SERVER.script_paced_duration(copy), 8.0)

    def test_silent_mode_phrase_timeline_covers_the_whole_video(self) -> None:
        timeline = SERVER.script_paced_phrase_timeline("先理解问题。再拆分步骤。最后完成验证。", 12000)
        self.assertEqual(timeline["timing_source"], "script-paced-no-narration")
        self.assertFalse(timeline["estimated_fallback_used"])
        self.assertEqual(timeline["phrases"][0]["spoken_start_ms"], 0)
        self.assertEqual(timeline["phrases"][-1]["spoken_end_ms"], 12000)
        self.assertEqual([item["id"] for item in timeline["phrases"]], ["p001", "p002", "p003"])

    def test_silent_mode_uses_the_same_clause_boundaries_as_direct_narration(self) -> None:
        self.assertEqual(SERVER.narration_phrases("先观察，再判断：最后行动。"), ["先观察，", "再判断：", "最后行动。"])

    def test_job_upload_is_optional_for_no_narration_mode(self) -> None:
        parameter = inspect.signature(SERVER.create_job).parameters["reference"]
        self.assertIsNone(parameter.default.default)

    def test_no_narration_job_can_be_submitted_without_an_audio_part(self) -> None:
        with TestClient(SERVER.app) as client:
            response = client.post("/api/jobs", data={
                "copy": "这是一段不上传任何音频也可以正常提交的视频测试文案。",
                "voice_mode": "none",
            })
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["id"]
        self.assertEqual(SERVER.JOBS[job_id]["voice_mode"], "none")
        self.assertEqual(list((SERVER.JOBS_DIR / job_id).glob("reference.*")), [])
        task = SERVER.MODEL_QUEUE.get_nowait()
        self.assertEqual(task[0], "prepare_characters")
        self.assertIsNone(task[4])

    def test_model_catalog_classifies_and_selects_available_models(self) -> None:
        catalog = SERVER.build_model_catalog(
            {"gpt-4.1-mini", "text-embedding-3-small", "gpt-image-1", "dall-e-3"},
            "gpt-5",
            "gpt-image-2",
        )
        self.assertEqual(catalog["selected_text_model"], "gpt-4.1-mini")
        self.assertEqual(catalog["selected_image_model"], "gpt-image-1")
        self.assertNotIn("text-embedding-3-small", catalog["text_models"])
        self.assertIn("dall-e-3", catalog["image_models"])

    def test_model_catalog_keeps_configured_model_when_available(self) -> None:
        catalog = SERVER.build_model_catalog(
            {"claude-sonnet-4", "gpt-4.1-mini", "flux-1.1-pro"},
            "claude-sonnet-4",
            "flux-1.1-pro",
        )
        self.assertEqual(catalog["selected_text_model"], "claude-sonnet-4")
        self.assertEqual(catalog["selected_image_model"], "flux-1.1-pro")

    def test_invalid_image_provider_url_falls_back_to_shared_provider(self) -> None:
        resolved = SERVER.image_provider_config({
            "base_url": "https://relay.example/v1",
            "api_key": "shared-key",
            "image_base_url": "not-a-url",
            "image_api_key": "",
        })
        self.assertEqual(resolved["base_url"], "https://relay.example/v1")
        self.assertEqual(resolved["api_key"], "shared-key")

    def test_text_provider_falls_back_to_another_advertised_model_on_upstream_limit(self) -> None:
        limited = SERVER.ProviderHTTPError(429, "Upstream rate limit exceeded")
        with mock.patch.object(SERVER, "provider_text_once", side_effect=[limited, {"output_text": "ok"}]) as request:
            payload = SERVER.provider_text(
                {"api_key": "test", "base_url": "https://relay.example/v1", "_text_models": ["gpt-5.4", "gpt-4o"]},
                "gpt-5.4",
                "hello",
            )
        self.assertEqual(payload["output_text"], "ok")
        self.assertEqual([call.args[1] for call in request.call_args_list], ["gpt-5.4", "gpt-4o"])

    def test_text_provider_falls_back_on_generic_service_unavailable(self) -> None:
        unavailable = SERVER.ProviderHTTPError(503, "Service temporarily unavailable")
        with mock.patch.object(SERVER, "provider_text_once", side_effect=[unavailable, {"model": "gpt-5.5", "output_text": "ok"}]) as request:
            payload = SERVER.provider_text(
                {"api_key": "test", "base_url": "https://relay.example/v1", "_text_models": ["gpt-5.4", "gpt-5.5"]},
                "gpt-5.4",
                "hello",
            )
        self.assertEqual(payload["output_text"], "ok")
        self.assertEqual([call.args[1] for call in request.call_args_list], ["gpt-5.4", "gpt-5.5"])

    def test_resolved_models_follow_each_provider_response(self) -> None:
        config = {
            "api_key": "text-key",
            "base_url": "https://text.example/v1",
            "text_model": "manual-text-model",
            "image_api_key": "image-key",
            "image_base_url": "https://image.example/v1",
            "image_model": "manual-image-model",
        }
        with mock.patch.object(
            SERVER,
            "provider_models",
            side_effect=[{"gpt-5.5", "text-embedding-3-small"}, {"gpt-image-2", "dall-e-3"}],
        ):
            resolved = SERVER.resolve_configured_models(config)
        self.assertEqual(resolved["text_model"], "gpt-5.5")
        self.assertEqual(resolved["image_model"], "gpt-image-2")
        self.assertEqual(resolved["_text_models"], ["gpt-5.5"])
        self.assertEqual(resolved["_image_models"], ["gpt-image-2"])

    def test_image_provider_uses_only_selected_model_and_records_actual_model(self) -> None:
        SERVER.JOBS["image-job"] = self.job("image-job")
        with mock.patch.object(SERVER, "provider_post", return_value={"model": "gpt-image-1-live", "data": [{}]}) as request:
            payload = SERVER.provider_image(
                {"api_key": "test", "base_url": "https://relay.example/v1", "image_model": "gpt-image-1", "_image_models": ["gpt-image-1", "gpt-image-2"]},
                "images/generations",
                {"model": "gpt-image-1", "prompt": "hello"},
                job_id="image-job",
            )
        self.assertEqual(payload["model"], "gpt-image-1-live")
        self.assertEqual([call.args[2]["model"] for call in request.call_args_list], ["gpt-image-1"])
        self.assertEqual(request.call_args.kwargs["attempts"], 1)
        self.assertEqual(SERVER.JOBS["image-job"]["image_model"], "gpt-image-1-live")

    def test_config_returns_full_keys_for_plaintext_settings(self) -> None:
        visible = SERVER.safe_config({"api_key": "text-secret", "image_api_key": "image-secret"})
        self.assertEqual(visible["api_key"], "text-secret")
        self.assertEqual(visible["image_api_key"], "image-secret")

    def test_scene_durations_fit_voice_track_exactly(self) -> None:
        scenes = [
            {"text": "短句", "duration_ms": 2000},
            {"text": "这是一段明显更长的中间文案", "duration_ms": 12000},
            {"text": "结尾", "duration_ms": 2000},
        ]
        changed = SERVER.fit_scene_durations(scenes, 5.123)
        self.assertTrue(changed)
        self.assertEqual(sum(scene["duration_ms"] for scene in scenes), 5123)
        self.assertGreaterEqual(scenes[-1]["duration_ms"], 1000)

    def test_aspect_ratio_presets_cover_common_creator_formats(self) -> None:
        self.assertEqual(SERVER.normalize_aspect_ratio("3:4"), "3:4")
        self.assertEqual(SERVER.normalize_aspect_ratio("invalid"), "16:9")
        self.assertEqual(SERVER.aspect_video_dimensions("9:16"), (1080, 1920))
        self.assertEqual(SERVER.aspect_image_dimensions("1:1"), (1024, 1024))
        self.assertEqual(SERVER.aspect_api_size("3:4"), "1024x1536")

    def test_generated_image_is_cropped_to_selected_aspect_ratio(self) -> None:
        from PIL import Image

        image_path = Path(self.temporary.name) / "generated.png"
        Image.new("RGB", (1536, 1024), "white").save(image_path)
        SERVER.normalize_generated_image_aspect(image_path, "1:1")
        with Image.open(image_path) as result:
            self.assertEqual(result.size, (1024, 1024))

    def test_infographic_props_use_selected_video_dimensions(self) -> None:
        scenes = [{
            "start_frame": 0, "end_frame": 30, "timed_cues": [{
                "id": "cue-1", "anchor_text": "测试", "start_frame": 0, "end_frame": 30,
                "spoken_start_ms": 0, "spoken_end_ms": 1000, "enter_ids": ["page-title"],
                "focus_id": "page-title", "alignment_coverage": 1.0, "alignment_confidence": 1.0,
            }],
        }]
        props = SERVER.remotion_infographic_props(scenes, "极简粗线简笔白板风", 1000, False, "3:4")
        self.assertEqual((props["width"], props["height"]), (1080, 1440))

    def test_portrait_board_annotation_stacks_scenes_vertically(self) -> None:
        from PIL import Image

        image_path = Path(self.temporary.name) / "portrait.png"
        annotation_path = Path(self.temporary.name) / "portrait.json"
        Image.new("RGB", (864, 1536), "white").save(image_path)
        scenes = [{"title": "上", "duration_ms": 1000}, {"title": "下", "duration_ms": 1000}]
        SERVER.write_board_annotation(scenes, image_path, annotation_path, 1)
        elements = json.loads(annotation_path.read_text(encoding="utf-8"))["elements"]
        self.assertEqual(elements[0]["region"]["x"], elements[1]["region"]["x"])
        self.assertLess(elements[0]["region"]["y"], elements[1]["region"]["y"])

    def test_story_color_reserves_caption_space_and_passes_renderer_flag(self) -> None:
        from PIL import Image

        image_path = Path(self.temporary.name) / "story.png"
        annotation_path = Path(self.temporary.name) / "story.json"
        Image.new("RGB", (1024, 1366), "white").save(image_path)
        scenes = [{"title": "相遇", "text": "那天我们第一次见面。", "duration_ms": 2400}]
        SERVER.write_board_annotation(scenes, image_path, annotation_path, 1, "story-color")
        element = json.loads(annotation_path.read_text(encoding="utf-8"))["elements"][0]
        self.assertEqual(element["subtitle"], "那天我们第一次见面。")
        self.assertLess(element["captionRegion"]["y"], element["region"]["y"])
        command = SERVER.whiteboard_render_command(image_path, annotation_path, Path("out.mp4"), "detailed", "story-color", "3:4")
        self.assertTrue(str(command[1]).endswith("render_story_color.py"))
        self.assertNotIn("render_stream_whiteboard.py", " ".join(map(str, command)))
        self.assertNotIn("--ink-path", command)
        self.assertEqual(command[command.index("--width") + 1], "1080")
        self.assertEqual(command[command.index("--height") + 1], "1440")

    def test_story_color_prompt_reserves_top_space_but_forbids_generated_text(self) -> None:
        prompt = SERVER.build_board_prompt(
            [{"title": "相遇", "concept": "两人在门口相遇", "elements": ["青年挥手"], "text": "那天我们第一次见面。"}],
            SERVER.DEFAULT_STYLE,
            aspect_ratio="3:4",
            presentation_mode="story-color",
        )
        self.assertIn("上方保留约 25%", prompt)
        self.assertIn("字幕由程序后期准确添加", prompt)
        self.assertIn("图片模型不得写字", prompt)

    def test_two_minutes_allow_twenty_scenes(self) -> None:
        self.assertEqual(SERVER.scene_limit_for_duration(120), 20)
        self.assertEqual(SERVER.scene_limit_for_duration(180), 20)

    def test_old_scene_clip_with_extra_half_second_is_rejected(self) -> None:
        with mock.patch.object(SERVER, "valid_media_file", return_value=True), mock.patch.object(SERVER, "probe_duration", return_value=2.5):
            self.assertFalse(SERVER.valid_timed_video(Path("old.mp4"), 2000))
        with mock.patch.object(SERVER, "valid_media_file", return_value=True), mock.patch.object(SERVER, "probe_duration", return_value=2.04):
            self.assertTrue(SERVER.valid_timed_video(Path("current.mp4"), 2000))

    def test_restore_converts_running_job_back_to_queue(self) -> None:
        job_id = "restore-test"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        metadata = self.job(job_id)
        metadata.update(status="running", current_phase="images", phase_started_at=1.0)
        (job_dir / "job.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

        SERVER.restore_jobs()

        self.assertEqual(SERVER.JOBS[job_id]["status"], "queued")
        self.assertEqual(SERVER.JOBS[job_id]["resume_count"], 1)
        self.assertIsNone(SERVER.JOBS[job_id]["current_phase"])
        self.assertEqual(SERVER.JOBS[job_id]["task_name"], "这是一段用于验证任务断点恢复的")

    def test_missing_voice_returns_to_voice_queue(self) -> None:
        job_id = "voice-test"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "reference.wav").write_bytes(b"reference")
        SERVER.JOBS[job_id] = self.job(job_id)

        SERVER.resume_pending_jobs()

        self.assertEqual(SERVER.VOICE_QUEUE.qsize(), 1)
        self.assertEqual(SERVER.MODEL_QUEUE.qsize(), 0)

    def test_valid_voice_skips_to_model_queue(self) -> None:
        job_id = "model-test"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "reference.wav").write_bytes(b"reference")
        with wave.open(str(job_dir / "voice.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 16000)
        SERVER.JOBS[job_id] = self.job(job_id)

        with mock.patch.object(SERVER, "valid_media_file", side_effect=lambda path: Path(path).name == "voice.wav"):
            SERVER.resume_pending_jobs()

        self.assertEqual(SERVER.VOICE_QUEUE.qsize(), 0)
        self.assertEqual(SERVER.MODEL_QUEUE.qsize(), 1)


if __name__ == "__main__":
    unittest.main()

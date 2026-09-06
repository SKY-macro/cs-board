import importlib.util
import inspect
import json
import queue
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

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
        SERVER.JOBS = {}
        SERVER.VOICE_QUEUE = queue.Queue()
        SERVER.MODEL_QUEUE = queue.Queue()
        SERVER.ensure_pipeline_workers = lambda: None

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
        self.assertIn("动物、人物身份与年龄不得被替换", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_unknown_style_never_silently_falls_back(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "后台未加载画面风格"):
            SERVER.style_recipe("不存在的风格")

    def test_story_handdrawn_library_adds_exactly_twenty_styles(self) -> None:
        self.assertEqual(len(SERVER.HANDDRAWN_STYLE_PRESETS), 20)
        self.assertIn("彩铅日记漫画（默认）", SERVER.HANDDRAWN_STYLE_PRESETS)
        self.assertIn("粗粝木刻社论插画", SERVER.HANDDRAWN_STYLE_PRESETS)

    def test_story_handdrawn_recipe_keeps_positive_and_negative_constraints(self) -> None:
        recipe = SERVER.style_recipe("水墨写意")
        self.assertIn("浓淡干湿", recipe)
        self.assertIn("色彩要求", recipe)
        self.assertIn("排除项", recipe)

    def test_colored_pencil_diary_uses_its_full_profile(self) -> None:
        recipe = SERVER.style_recipe("彩铅日记漫画（默认）")
        self.assertIn("oversized rounded heads", recipe)
        self.assertIn("dry wax-colored-pencil fills", recipe)

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

    def test_detect_models_reads_catalog_without_sending_generation_probe(self) -> None:
        with mock.patch.object(SERVER, "provider_models", return_value={"gpt-5.4", "gpt-5.5"}) as models, mock.patch.object(
            SERVER, "provider_text_once"
        ) as generate:
            catalog = SERVER.detect_models({"api_key": "test", "base_url": "https://relay.example/v1"})
        self.assertEqual(catalog["text_models"], ["gpt-5.4"])
        self.assertEqual(catalog["selected_text_model"], "gpt-5.4")
        self.assertGreaterEqual(models.call_count, 1)
        generate.assert_not_called()

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

    def test_image_provider_uses_response_candidates_and_records_actual_model(self) -> None:
        unavailable = SERVER.ProviderHTTPError(503, "Service temporarily unavailable")
        SERVER.JOBS["image-job"] = self.job("image-job")
        with mock.patch.object(SERVER, "provider_post", side_effect=[unavailable, {"model": "gpt-image-2-live", "data": [{}]}]) as request:
            payload = SERVER.provider_image(
                {"api_key": "test", "base_url": "https://relay.example/v1", "image_model": "gpt-image-1", "_image_models": ["gpt-image-1", "gpt-image-2"]},
                "images/generations",
                {"model": "gpt-image-1", "prompt": "hello"},
                job_id="image-job",
            )
        self.assertEqual(payload["model"], "gpt-image-2-live")
        self.assertEqual([call.args[2]["model"] for call in request.call_args_list], ["gpt-image-1", "gpt-image-2"])
        self.assertEqual(SERVER.JOBS["image-job"]["image_model"], "gpt-image-2-live")

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

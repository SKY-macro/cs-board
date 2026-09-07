from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from gradio_client import Client, handle_file


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".webapp"
JOBS_DIR = STATE_DIR / "jobs"
CONFIG_PATH = STATE_DIR / "config.json"
PREFERENCES_PATH = STATE_DIR / "preferences.json"
IMAGE_NODE_STATS_PATH = STATE_DIR / "image-node-stats.json"
PYTHON = Path(sys.executable)
NODE = shutil.which("node") or "node"
REMOTION_RENDERER = ROOT / "video_renderer"
HAND = ROOT / "assets" / "drawing-hand-clean.png"
PIPELINE_VERSION = "narrated_deck_v13_style_prompt_panel"
ALIGNMENT_SEGMENTATION = "word-boundary-dtw-audio-v2"
SUBTITLE_FONT = os.environ.get(
    "CS_BOARD_SUBTITLE_FONT",
    "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei",
)

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.openlux.ai/v1",
    "text_model": "gpt-5",
    "image_model": "gpt-image-2",
    "image_base_url": "",
    "image_api_key": "",
    "text_services": [],
    "image_services": [],
    "image_global_rpm_limit": 200,
    "image_global_in_flight_limit": 80,
    "tts_url": "http://127.0.0.1:7860",
    "tts_url_2": "",
    "tts_mode": "gradio",
}

DEFAULT_STYLE = "极简粗线简笔白板风"
INFOGRAPHIC_STYLE = "国风动态信息图"
CLEAR_STORYBOOK_STYLE = "清透日系生活绘本"
DEFAULT_IDENTITY_MODE = "consistent"
IDENTITY_PROMPTS = {
    "consistent": (
        "同一角色跨分镜保持身份、基础脸型、眼睛形状、发色和标志性特征一致。"
        "年龄、身高、体型、发型、服装和当前状态默认延续上一分镜；只有原文明示或剧情必然包含时间跳跃、成长、衰老、换装、受伤等变化时才允许更新。"
        "发生变化时，只改变剧情要求改变的属性，其余身份锚点必须保留，确保仍能一眼认出是同一个人。不得因为地点、动作或镜头变化而重新设计角色。"
    ),
    "male": "同一主角固定为：中国青年男性，短黑发，朴素深色上衣，普通人形象；所有分镜中的年龄与外貌保持一致。",
    "female": "同一主角固定为：中国青年女性，自然黑色齐肩发，朴素深色上衣，普通人形象；所有分镜中的年龄与外貌保持一致。",
}
STYLE_PRESETS = {
    INFOGRAPHIC_STYLE: (
        "暖米白宣纸背景，深灰正文与朱红重点，低饱和靛青辅助色；"
        "固定总标题和章节标题，以知识卡片、关系线、时间轴、层级或对比结构组织观点，"
        "搭配克制的国风淡彩插画，大量留白，成人知识内容，禁止摄影写实和儿童卡通。"
    ),
    "极简粗线简笔白板风": (
        "暖白色纯净背景，圆润有亲和力的粗黑马克笔轮廓，人物和物体高度概括，"
        "只使用橙色与钴蓝色做少量平涂点缀；几乎没有阴影、纹理和细碎结构，留白充足，"
        "像现场快速画出的清爽白板简笔画。"
    ),
    "极简商务涂鸦风": (
        "冷白至极浅灰背景，深海军蓝的精准几何轮廓，钴蓝与青绿色作为强调色；"
        "用整齐的卡片、流程箭头、图表和图标组织信息，线条克制利落、间距规整，"
        "呈现专业的商业演示和科技产品解说感，禁止暖黄纸张与随意手绘笔触。"
    ),
    "暖米黄素描白板风": (
        "温暖米黄色纸张底色，真实石墨铅笔线条，轻柔排线、交叉线和深浅笔压，"
        "辅以低饱和赭石色与灰蓝色；保留手工速写的纸张颗粒和结构细节，"
        "像一本质感细腻的编辑手账，不能画成粗线扁平图标。"
    ),
    "粗线扁平国风卡通": (
        "温暖宣纸色背景，深棕色粗轮廓，朱红、玉绿与靛青的饱和平涂色块；"
        "人物比例生动简化，少量使用祥云、笔触和中式构图节奏，"
        "形成现代国风科普动画效果，禁止写实素描和欧美商务信息图观感。"
    ),
    "爆款高热吸睛风": (
        "明亮黄色高能背景，超粗黑色外轮廓，热烈橙红与电光钴蓝的大色块，"
        "夸张但友好的人物表情和动作，配合放射爆炸形、速度线与强烈斜向构图；"
        "主体要大、对比要强、第一眼就能看懂，具有热门短视频封面般的冲击力，"
        "但保持轮廓干净，不能堆满琐碎元素。"
    ),
    "黑金科技发布会风": (
        "深黑与炭灰背景，金属金色作为主轮廓和高光，少量电光青色点缀；"
        "使用精致的环形界面、几何数据结构和舞台式光影，主体高级、权威、科技感强，"
        "像高端科技产品发布会，禁止暖白纸张和可爱手绘效果。"
    ),
    "清新治愈手账风": (
        "奶油白纸张背景，圆润轻柔的手绘线条，鼠尾草绿、蜜桃粉、奶油黄和天蓝色的低饱和水彩；"
        "少量加入胶带、贴纸与植物点缀，整体通透、温暖、治愈、生活化，"
        "保持留白，禁止强烈黑线和高对比商务图表。"
    ),
    "复古报纸拼贴风": (
        "暖灰新闻纸底色，黑色油墨主体、复古红色强调块、半色调网点、丝网印刷颗粒与撕纸边缘；"
        "人物和物体像剪下后重新拼贴的编辑视觉，层次大胆、粗粝、有文化杂志感，"
        "禁止光滑渐变和现代扁平信息图。"
    ),
    "纸感隐喻拼贴风": (
        "暖米白手工纸背景，清晰纸纤维、撕边、轻微褶皱与手工裁切痕迹；人物和物体由剪纸拼贴叠层构成，"
        "带柔和浅浮雕投影，成人卡通比例、圆白眼与小黑瞳、细线鼻口。主色仅使用米杏、炭黑、深灰、暖灰、"
        "珊瑚红和灰粉，金黄只用于希望、价值或关键转折。每张图只选择定义、流程、对比、层级、因果、清单、"
        "时间或矩阵中的一个主结构，用单一具体隐喻表达观点；留白占 25%–45%，主视觉不超过 3 组，辅助符号不超过 5 类。"
        "禁止摄影写实、光滑塑料 3D、扁平矢量图标、儿童贴纸、霓虹科技 UI、文字、Logo、水印和图标堆砌。"
    ),
    "漫画墨线解释风": (
        "暖灰米白纸张背景，使用自信、粗细有变化的黑色漫画墨线；灰面和阴影只用经典圆点半色调，不用柔和渐变。"
        "黑白灰为主体，固定暖黄色只用于边牧或关键物件，每张图最多再使用两种低饱和语义色：蓝色表示输入或内容，"
        "橙色表示行动、警告或成本，紫色表示过程，绿色表示成功或完成。关系必须用具体物件、路径、状态变化和重复材料证明，"
        "不能靠装饰图标凑数。原文需要通用角色时才使用戴细圆框眼镜的圆头极简线人，胖胖的暖黄边牧只作合适的陪伴角色；"
        "抽象机制页优先画物件和状态，不强塞人物。禁止 3D、摄影写实、光滑渐变、通用卡片网格、仪表盘、杂乱装饰、Logo 和水印。"
    ),
    "3D黏土趣味风": (
        "可爱的三维黏土动画场景，圆润玩具化比例，可见细微手作指纹，"
        "珊瑚橙、青绿色、亮黄色和奶油色的柔和配色，温暖棚拍光与轻柔投影，"
        "像精致的定格动画小剧场，主体清楚，禁止二维线稿和写实摄影材质。"
    ),
    "赛博霓虹漫画风": (
        "深靛蓝至黑色背景，青色与洋红色霓虹边缘光，紫色渐变和粗黑漫画轮廓；"
        "加入克制的速度线、全息几何形与未来创作者工作室氛围，构图动感、戏剧性强，"
        "同时确保人物面部和关键物体清楚可读。"
    ),
    CLEAR_STORYBOOK_STYLE: (
        "纯白无纸纹数字页；纤细清晰、略有手绘起伏的黑灰墨线，外轮廓克制，内部仅少量发丝、衣褶和接地线。"
        "人物为自然纤细的现代生活绘本比例：成年人约 5～6 头身，儿童约 4～5 头身；头部仅轻度放大，肩颈、手脚和四肢完整，绝不短胖幼态。"
        "柔和短椭圆脸、大面积面部留白；小型黑色竖椭圆或圆点眼，一笔短鼻、细小嘴眉；无彩色虹膜、大眼、浓睫毛和尖下巴。"
        "头发为轮廓明确的深色块面，以少量细碎发束收边，不画蓬松尖刺发型。肤色极淡，腮红近乎不可见。"
        "颜色只用于人物服装和剧情核心道具：整洁的低饱和哑光平涂、局部极淡排线；无水彩、颗粒和体积光。"
        "构图服从剧情，优先完整全身或四分之三身平视群像。背景建筑、家具、地面、天空和植物一律不着色，仅留黑灰细线；纯白面积不少于 80%。"
        "人物场景内容只能来自当前分镜，不继承风格图内容。"
        "禁止 Q 版、chibi、短胖身体、默认背影、电影运镜、风景绘本式铺满背景、空气透视、柔焦、渐变、泛黄纸纹、蜡笔或炭笔颗粒、强光影、3D、写实摄影、文字和水印。"
    ),
}

MODEL_CATALOG_CACHE_TTL_SECONDS = 300
MODEL_CATALOG_CACHE: dict[tuple[str, str], tuple[float, set[str]]] = {}
MODEL_CATALOG_CACHE_LOCK = threading.Lock()

ASPECT_RATIO_PRESETS = {
    "16:9": {"video": (1920, 1080), "image": (1536, 864), "api_size": "1536x1024"},
    "9:16": {"video": (1080, 1920), "image": (864, 1536), "api_size": "1024x1536"},
    "3:4": {"video": (1080, 1440), "image": (1024, 1366), "api_size": "1024x1536"},
    "4:3": {"video": (1440, 1080), "image": (1536, 1152), "api_size": "1536x1024"},
    "1:1": {"video": (1080, 1080), "image": (1024, 1024), "api_size": "1024x1024"},
}


def normalize_aspect_ratio(value: Any) -> str:
    ratio = str(value or "16:9").strip()
    return ratio if ratio in ASPECT_RATIO_PRESETS else "16:9"


def normalize_presentation_mode(value: Any) -> str:
    mode = str(value or "whiteboard").strip()
    return mode if mode in {"whiteboard", "story-color"} else "whiteboard"


def normalize_identity_mode(value: Any) -> str:
    mode = str(value or DEFAULT_IDENTITY_MODE).strip().lower()
    return mode if mode in IDENTITY_PROMPTS else DEFAULT_IDENTITY_MODE


def identity_prompt(value: Any) -> str:
    return IDENTITY_PROMPTS[normalize_identity_mode(value)]


def aspect_video_dimensions(value: Any) -> tuple[int, int]:
    return ASPECT_RATIO_PRESETS[normalize_aspect_ratio(value)]["video"]


def aspect_image_dimensions(value: Any) -> tuple[int, int]:
    return ASPECT_RATIO_PRESETS[normalize_aspect_ratio(value)]["image"]


def aspect_api_size(value: Any) -> str:
    return str(ASPECT_RATIO_PRESETS[normalize_aspect_ratio(value)]["api_size"])

HANDDRAWN_STYLE_LIBRARY_PATH = ROOT / "assets" / "story-handdrawn" / "handdrawn-style-library.json"
HANDDRAWN_VISUAL_RECIPES_PATH = ROOT / "assets" / "story-handdrawn" / "visual-style-recipes.json"


def load_handdrawn_style_presets(path: Path = HANDDRAWN_STYLE_LIBRARY_PATH) -> dict[str, str]:
    """Load the bundled story-to-handdrawn-video recipes without flattening their constraints."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"手绘风格库加载失败：{path}") from exc
    styles = payload.get("styles")
    if not isinstance(styles, list) or len(styles) != 20:
        raise RuntimeError("手绘风格库必须包含 20 种画面风格")
    try:
        clean_payload = json.loads(HANDDRAWN_VISUAL_RECIPES_PATH.read_text(encoding="utf-8"))
        clean_recipes = clean_payload["recipes"]
        content_boundary = str(clean_payload["content_boundary"]).strip()
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(f"纯视觉配方库加载失败：{HANDDRAWN_VISUAL_RECIPES_PATH}") from exc
    presets: dict[str, str] = {}
    for entry in styles:
        if not isinstance(entry, dict):
            raise RuntimeError("手绘风格库包含无效条目")
        name = str(entry.get("name_zh") or "").strip()
        recipe = str(clean_recipes.get(name) or "").strip()
        if not name or not recipe:
            raise RuntimeError("手绘风格库的名称或提示词不完整")
        presets[name] = f"{recipe} 内容边界：{content_boundary}"
    if len(presets) != 20:
        raise RuntimeError("手绘风格库存在重复名称")
    return presets


HANDDRAWN_STYLE_PRESETS = load_handdrawn_style_presets()
STYLE_PRESETS.update(HANDDRAWN_STYLE_PRESETS)


def style_recipe(style: str) -> str:
    if style not in STYLE_PRESETS:
        raise RuntimeError(f"后台未加载画面风格：{style}，请重启后台后重新提交任务")
    return STYLE_PRESETS[style]


def is_infographic_job(job_id: str) -> bool:
    item = JOBS.get(job_id, {})
    return (
        item.get("reference_mode") == "infographic"
        or item.get("job_type") == "infographic"
        or item.get("style") == INFOGRAPHIC_STYLE  # Compatibility with the first preview build.
    )


PAPER_METAPHOR_STYLE = "纸感隐喻拼贴风"
PAPER_METAPHOR_REFERENCE_DIR = ROOT / "assets" / "style-references" / "paper-metaphor"
PAPER_METAPHOR_ROUTES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("流程", ("流程", "系统", "自动化", "生产", "步骤", "机器", "效率"), ("03-process-machine.png",)),
    ("对比", ("对比", "选择", "判断", "黑白", "两种", "不是", "而是"), ("05-choice-black-white.png", "09-road-between-extremes.png")),
    ("因果", ("原因", "结果", "影响", "关系", "伤害", "希望", "改变"), ("01-cause-heart-vs-wound.png",)),
    ("层级", ("层级", "成长", "方向", "阶段", "进阶", "山峰"), ("09-road-between-extremes.png",)),
    ("清单", ("清单", "资源", "经验", "多个", "几件", "要素"), ("08-dual-boxes.png",)),
    ("矩阵", ("矩阵", "四象限", "双维度"), ("02-balance-many-forces.png",)),
    ("对比", ("价值", "权衡", "平衡", "责任", "收益"), ("07-scale-values.png", "02-balance-many-forces.png")),
    ("因果", ("压力", "过载", "诱惑", "信息", "职场", "家庭"), ("04-overload-pushback.png", "06-work-stress.png")),
    ("对比", ("边界", "群体", "立场", "冲突", "夹击"), ("10-boundary-two-crowds.png",)),
]


def paper_metaphor_reference_context(scenes: list[dict[str, Any]]) -> tuple[list[Path], str]:
    text = " ".join(
        str(scene.get(key, ""))
        for scene in scenes
        for key in ("title", "concept", "text", "key_text", "metaphor")
    )
    structure = "定义"
    filenames = ("01-cause-heart-vs-wound.png",)
    for candidate, keywords, routed_files in PAPER_METAPHOR_ROUTES:
        if any(keyword in text for keyword in keywords):
            structure, filenames = candidate, routed_files
            break
    paths = [PAPER_METAPHOR_REFERENCE_DIR / filename for filename in filenames]
    paths = [path for path in paths if valid_image_file(path)][:3]
    if not paths:
        raise RuntimeError("纸感隐喻拼贴风的本地参考图缺失")
    instruction = (
        f"这些输入图仅作为纸艺视觉语言与“{structure}”构图参考，不提供人物身份或具体故事。"
        "只迁移纸纤维、撕边、叠层阴影、配色、构图密度与情绪表达；禁止照搬参考图中的人物、商品、文字、符号和场景组合。"
        f"本图统一使用“{structure}”作为唯一主结构，先用一个具体主隐喻表达观点，不做逐句图标化。"
    )
    return paths, instruction


OIL_VISUAL_STYLE = "漫画墨线解释风"
OIL_VISUAL_REFERENCE_DIR = ROOT / "assets" / "style-references" / "oil-visual"
CLEAR_STORYBOOK_REFERENCE_PATH = ROOT / "web" / "public" / "styles" / "clear-japanese-storybook.png"


def oil_visual_reference_context(scenes: list[dict[str, Any]], infographic: bool = False) -> tuple[list[Path], str]:
    scene = scenes[0] if scenes else {}
    layout_type = str(scene.get("layout_type") or scene.get("visual_structure") or "focus")
    text = " ".join(
        str(item.get(key, ""))
        for item in scenes
        for key in ("title", "concept", "text", "key_text", "visual_strategy", "illustration_elements")
    )
    if layout_type == "comparison" or any(word in text for word in ("对比", "差异", "两种", "成本", "取舍")):
        visual_mode, filename = "对比关系", "explainer-cost-comparison.png"
    elif layout_type == "cycle" or any(word in text for word in ("循环", "反馈", "闭环")):
        visual_mode, filename = "机制循环", "feedback-loop.png"
    elif layout_type in {"path", "flow", "cause", "timeline"} or any(word in text for word in ("机制", "流程", "步骤", "瓶颈", "管线")):
        visual_mode, filename = "机制流程", "pipeline-bottleneck.png"
    elif any(word in text for word in ("人物", "角色", "讲解者", "陪伴", "团队", "主人公")):
        visual_mode, filename = "角色场景", "transparent-illustration.png"
    else:
        visual_mode, filename = "概念解释", "from-complex-to-clear.png"
    path = OIL_VISUAL_REFERENCE_DIR / filename
    if not valid_image_file(path):
        raise RuntimeError("漫画墨线解释风的本地参考图缺失")
    division = (
        "Remotion 已负责中文标题、标签、线条和关系结构，本图只生成插画证据。"
        if infographic else
        "程序会另行添加中文重点文字，本图只生成视觉证据。"
    )
    instruction = (
        f"输入图仅作为漫画墨线视觉语言与“{visual_mode}”表达方式的参考，不提供本页文字或具体故事。"
        "只迁移粗细墨线、圆点半色调、暖灰纸张、克制语义色和极简角色比例；"
        "严禁复制参考图中的英文、标签、箭头、流程线、界面、Logo、原场景组合和原观点。"
        f"{division}"
    )
    return [path], instruction


def clear_storybook_reference_context() -> tuple[list[Path], str]:
    if not valid_image_file(CLEAR_STORYBOOK_REFERENCE_PATH):
        raise RuntimeError("清透日系生活绘本的本地风格参考图缺失")
    instruction = (
        "输入图只定义人物造型、头身、五官、线条、人物与核心道具配色及背景纯线稿；"
        "当前分镜决定内容，不得复制图中人物身份、数量、服装、动作、道具、场景或构图。"
    )
    return [CLEAR_STORYBOOK_REFERENCE_PATH], instruction

app = FastAPI(title="白板声画工坊", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:13000", "http://127.0.0.1:13000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()
VOICE_QUEUE: queue.Queue[tuple[Any, ...]] = queue.Queue()
MODEL_QUEUE: queue.Queue[tuple[Any, ...]] = queue.Queue()
WORKER_LOCK = threading.Lock()
VOICE_WORKER_THREADS: dict[int, threading.Thread] = {}
VOICE_NODE_JOBS: dict[int, str | None] = {}
VOICE_NODE_LOCK = threading.Lock()
MODEL_WORKER_THREADS: list[threading.Thread] = []
RENDER_THREADS: set[threading.Thread] = set()
RENDER_THREADS_LOCK = threading.Lock()
RENDER_ACTIVE = 0
RENDER_ACTIVE_LOCK = threading.Lock()
RUNNING_PROCESSES: dict[str, set[subprocess.Popen[str]]] = {}
RUNNING_PROCESSES_LOCK = threading.Lock()
MODEL_CONCURRENCY = 4
IMAGE_GENERATION_RPM = max(1, min(300, int(os.environ.get("IMAGE_GENERATION_RPM", "3"))))
IMAGE_GENERATION_MAX_RPM = max(IMAGE_GENERATION_RPM, min(300, int(os.environ.get("IMAGE_GENERATION_MAX_RPM", "300"))))
IMAGE_GENERATION_GLOBAL_RPM = max(1, min(500, int(os.environ.get("IMAGE_GENERATION_GLOBAL_RPM", "200"))))
IMAGE_GLOBAL_IN_FLIGHT_LIMIT = max(10, min(500, int(os.environ.get("IMAGE_GLOBAL_IN_FLIGHT_LIMIT", "80"))))
WHITEBOARD_RENDER_CONCURRENCY = max(1, min(4, int(os.environ.get("WHITEBOARD_RENDER_CONCURRENCY", "3"))))
RENDER_JOB_CONCURRENCY = max(1, min(3, int(os.environ.get("RENDER_JOB_CONCURRENCY", "2"))))
RENDER_JOB_SEMAPHORE = threading.BoundedSemaphore(RENDER_JOB_CONCURRENCY)
MAX_ACTIVE_AND_QUEUED = 20


class JobCancelled(RuntimeError):
    """Cooperative stop signal for a task cancelled from the UI."""


def is_job_cancelled(job_id: str) -> bool:
    with LOCK:
        return JOBS.get(job_id, {}).get("status") == "cancelled"


def ensure_job_active(job_id: str) -> None:
    if is_job_cancelled(job_id):
        raise JobCancelled("任务已取消")


def terminate_running_process(job_id: str) -> None:
    with RUNNING_PROCESSES_LOCK:
        processes = list(RUNNING_PROCESSES.get(job_id, set()))
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            else:
                process.terminate()
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass


def _persist_job_locked(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    target = job_dir / "job.json"
    temporary = job_dir / "job.json.tmp"
    temporary.write_text(json.dumps(JOBS[job_id], ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def atomic_write_json(target: Path, value: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


class ImageNodeCoolingDown(RuntimeError):
    def __init__(self, wait_seconds: float):
        self.wait_seconds = max(0.0, float(wait_seconds))
        super().__init__(f"节点限流冷却中，约 {self.wait_seconds:.1f} 秒后恢复")


class ImageDailyQuotaExhausted(RuntimeError):
    """All candidate image relays reached their configured safe daily budget."""

    def __init__(self, reset_seconds: float):
        self.reset_seconds = max(0.0, float(reset_seconds))
        super().__init__(f"所有图片节点均已达到日请求安全额度，约 {max(1, math.ceil(self.reset_seconds / 3600))} 小时后重置")


class AdaptiveImageNodePool:
    """Fair, multi-relay RPM scheduler with adaptive tiers and circuit breakers."""

    RPM_TIERS = (1, 3, 5, 8, 10)
    HIGH_TIER_FLOOR = 8
    FAILED_TIER_CAP = 5
    FIRST_TIER_LOCK_SECONDS = 1800.0
    REPEATED_TIER_LOCK_SECONDS = 21600.0
    TIER_FAILURE_WINDOW_SECONDS = 21600.0

    def __init__(
        self,
        stats_path: Path,
        default_rpm: int = 3,
        window_seconds: float = 60.0,
        *,
        max_rpm: int = 300,
        global_rpm_limit: int = 200,
        promotion_window_seconds: float = 600.0,
        promotion_successes: int = 30,
        recovery_window_seconds: float = 1800.0,
        recovery_successes: int = 100,
        minimum_in_flight_limit: int = 30,
        in_flight_minutes: float = 10.0,
        global_in_flight_limit: int = 80,
    ):
        self.stats_path = stats_path
        self.max_rpm = max(1, min(300, int(max_rpm)))
        self.default_rpm = max(1, min(self.max_rpm, int(default_rpm)))
        self.global_rpm_limit = max(1, min(500, int(global_rpm_limit)))
        self.window_seconds = max(0.0, float(window_seconds))
        self.promotion_window_seconds = max(0.0, float(promotion_window_seconds))
        self.promotion_successes = max(1, int(promotion_successes))
        self.recovery_window_seconds = max(0.0, float(recovery_window_seconds))
        self.recovery_successes = max(1, int(recovery_successes))
        self.minimum_in_flight_limit = max(1, int(minimum_in_flight_limit))
        self.in_flight_minutes = max(0.0, float(in_flight_minutes))
        self.global_in_flight_limit = max(1, int(global_in_flight_limit))
        self.condition = threading.Condition()
        self.states: dict[str, dict[str, Any]] = {}
        self.waiters: list[object] = []
        self.global_in_flight = 0
        self.next_global_request_at = 0.0
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now = time.monotonic()
        for key, raw in (payload.get("nodes") or {}).items():
            if not isinstance(raw, dict):
                continue
            rpm_limit = max(1, min(self.max_rpm, int(raw.get("rpm_limit") or self.max_rpm)))
            self.states[str(key)] = {
                "node_id": str(raw.get("node_id") or ""),
                "base_url": str(raw.get("base_url") or ""),
                "rpm_limit": rpm_limit,
                "rpd_limit": max(0, int(raw.get("rpd_limit") or 0)),
                "utilization_percent": max(10, min(100, int(raw.get("utilization_percent") or 100))),
                "safe_rpm_target": max(1, int(raw.get("safe_rpm_target") or self.default_rpm)),
                "daily_budget": max(0, int(raw.get("daily_budget") or 0)),
                "daily_date": str(raw.get("daily_date") or time.strftime("%Y-%m-%d")),
                "daily_used": max(0, int(raw.get("daily_used") or 0)),
                "capacity_signature": str(raw.get("capacity_signature") or ""),
                "rpm": max(1, min(rpm_limit, int(raw.get("rpm") or raw.get("limit") or self.default_rpm))),
                "in_flight": 0,
                "success_streak": max(0, int(raw.get("success_streak") or 0)),
                "success_count": max(0, int(raw.get("success_count") or 0)),
                "rate_limit_count": max(0, int(raw.get("rate_limit_count") or 0)),
                "rate_limit_strikes": max(0, int(raw.get("rate_limit_strikes") or 0)),
                "unavailable_count": max(0, int(raw.get("unavailable_count") or 0)),
                "consecutive_unavailable": 0,
                "average_latency": max(0.0, float(raw.get("average_latency") or 0.0)),
                "tier_successes": max(0, int(raw.get("tier_successes") or 0)),
                "tier_started_at": now,
                "failed_tier": 0,
                "failed_tier_failure_times": [],
                "tier_lock_until": 0.0,
                "tier_lock_rpm": 0,
                "runtime_rpm_cap": 0,
                "recovery_mode": False,
                "recovery_target_rpm": 0,
                "cooldown_until": 0.0,
                "next_request_at": 0.0,
                "circuit_reason": "",
                "last_status": raw.get("last_status"),
            }

    @staticmethod
    def node_key(config: dict[str, Any]) -> str:
        node_id = str(config.get("id") or "node")
        base_url = str(config.get("base_url") or "").strip().rstrip("/").lower()
        key_hash = hashlib.sha256(str(config.get("api_key") or "").encode("utf-8")).hexdigest()[:12]
        return hashlib.sha256(f"{node_id}|{base_url}|{key_hash}".encode("utf-8")).hexdigest()[:20]

    def _state(self, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        key = self.node_key(config)
        now = time.monotonic()
        rpm_limit = max(1, min(self.max_rpm, int(config.get("rpm_limit") or self.max_rpm)))
        explicit_capacity = "utilization_percent" in config
        utilization_percent = max(10, min(100, int(config.get("utilization_percent") or 80)))
        rpd_limit = max(0, min(100000, int(config.get("rpd_limit") or 0)))
        safe_rpm_target = max(1, math.floor(rpm_limit * utilization_percent / 100)) if explicit_capacity else rpm_limit
        initial_rpm = safe_rpm_target if explicit_capacity else min(self.default_rpm, rpm_limit)
        daily_budget = max(1, math.floor(rpd_limit * utilization_percent / 100)) if rpd_limit else 0
        capacity_signature = f"{rpm_limit}:{rpd_limit}:{utilization_percent}:{int(explicit_capacity)}"
        state = self.states.setdefault(key, {
            "node_id": str(config.get("id") or ""),
            "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
            "rpm_limit": rpm_limit,
            "rpd_limit": rpd_limit,
            "utilization_percent": utilization_percent,
            "safe_rpm_target": safe_rpm_target,
            "daily_budget": daily_budget,
            "daily_date": time.strftime("%Y-%m-%d"),
            "daily_used": 0,
            "capacity_signature": capacity_signature,
            "rpm": initial_rpm,
            "in_flight": 0,
            "success_streak": 0,
            "success_count": 0,
            "rate_limit_count": 0,
            "rate_limit_strikes": 0,
            "unavailable_count": 0,
            "consecutive_unavailable": 0,
            "average_latency": 0.0,
            "tier_successes": 0,
            "tier_started_at": now,
            "failed_tier": 0,
            "failed_tier_failure_times": [],
            "tier_lock_until": 0.0,
            "tier_lock_rpm": 0,
            "runtime_rpm_cap": 0,
            "recovery_mode": False,
            "recovery_target_rpm": 0,
            "cooldown_until": 0.0,
            "next_request_at": 0.0,
            "circuit_reason": "",
            "last_status": None,
        })
        state["node_id"] = str(config.get("id") or state["node_id"])
        state["base_url"] = str(config.get("base_url") or state["base_url"]).strip().rstrip("/")
        if str(state.get("capacity_signature") or "") != capacity_signature:
            state["capacity_signature"] = capacity_signature
            state["rpd_limit"] = rpd_limit
            state["utilization_percent"] = utilization_percent
            state["safe_rpm_target"] = safe_rpm_target
            state["daily_budget"] = daily_budget
            if not state["recovery_mode"] and not int(state["runtime_rpm_cap"]):
                state["rpm"] = initial_rpm
        state["rpm_limit"] = rpm_limit
        self._refresh_daily(state)
        state["rpm"] = min(int(state["rpm"]), safe_rpm_target)
        return key, state

    def _persist(self) -> None:
        with self.condition:
            nodes = {
                key: {field: value for field, value in state.items() if field not in {
                    "in_flight", "cooldown_until", "next_request_at", "tier_started_at", "circuit_reason", "consecutive_unavailable",
                    "failed_tier", "failed_tier_failure_times", "tier_lock_until", "tier_lock_rpm", "runtime_rpm_cap",
                    "recovery_mode", "recovery_target_rpm",
                }}
                for key, state in self.states.items()
            }
        try:
            atomic_write_json(self.stats_path, {"version": 2, "nodes": nodes})
        except OSError:
            pass

    def reset(self, stats_path: Path | None = None) -> None:
        with self.condition:
            if stats_path is not None:
                self.stats_path = stats_path
            self.states.clear()
            self.waiters.clear()
            self.global_in_flight = 0
            self.next_global_request_at = 0.0
            self.condition.notify_all()

    def configure(self, *, global_rpm_limit: int, global_in_flight_limit: int) -> None:
        """Apply console-wide capacity limits immediately without restarting workers."""
        with self.condition:
            self.global_rpm_limit = max(1, min(500, int(global_rpm_limit)))
            self.global_in_flight_limit = max(10, min(500, int(global_in_flight_limit)))
            self.condition.notify_all()

    @staticmethod
    def _daily_reset_seconds() -> float:
        now = time.time()
        local = time.localtime(now)
        tomorrow = time.mktime((local.tm_year, local.tm_mon, local.tm_mday + 1, 0, 0, 0, 0, 0, -1))
        return max(0.0, tomorrow - now)

    @staticmethod
    def _refresh_daily(state: dict[str, Any]) -> None:
        today = time.strftime("%Y-%m-%d")
        if str(state.get("daily_date") or "") != today:
            state["daily_date"] = today
            state["daily_used"] = 0

    def _daily_exhausted(self, state: dict[str, Any]) -> bool:
        self._refresh_daily(state)
        budget = int(state["daily_budget"])
        return budget > 0 and int(state["daily_used"]) >= budget

    def _in_flight_limit(self, state: dict[str, Any]) -> int:
        return max(self.minimum_in_flight_limit, math.ceil(int(state["rpm"]) * self.in_flight_minutes))

    def _tier_failure_times(self, state: dict[str, Any], now: float) -> list[float]:
        cutoff = now - self.TIER_FAILURE_WINDOW_SECONDS
        recent = [float(item) for item in state["failed_tier_failure_times"] if float(item) >= cutoff]
        state["failed_tier_failure_times"] = recent
        if not recent and not state["recovery_mode"] and not int(state["runtime_rpm_cap"]):
            state["failed_tier"] = 0
        return recent

    def _effective_rpm_limit(self, state: dict[str, Any], now: float) -> int:
        limit = int(state["safe_rpm_target"])
        permanent = int(state["runtime_rpm_cap"])
        if permanent:
            limit = min(limit, permanent)
        elif float(state["tier_lock_until"]) > now:
            limit = min(limit, max(1, int(state["tier_lock_rpm"])))
        return max(1, limit)

    def _remember_failed_high_tier(self, state: dict[str, Any], attempted_rpm: int, now: float) -> None:
        """Remember 8/10 RPM failures for this node only during this process lifetime."""
        if attempted_rpm < self.HIGH_TIER_FLOOR:
            return
        recent = self._tier_failure_times(state, now)
        recent.append(now)
        state["failed_tier_failure_times"] = recent
        state["failed_tier"] = max(int(state["failed_tier"]), attempted_rpm)
        failed_cap = self._downgrade_rpm(attempted_rpm)
        state["tier_lock_rpm"] = failed_cap
        state["recovery_mode"] = True
        state["recovery_target_rpm"] = max(int(state["recovery_target_rpm"]), attempted_rpm)
        if len(recent) >= 3:
            state["runtime_rpm_cap"] = failed_cap
            state["tier_lock_until"] = 0.0
        elif len(recent) == 2:
            state["tier_lock_until"] = max(float(state["tier_lock_until"]), now + self.REPEATED_TIER_LOCK_SECONDS)
        else:
            state["tier_lock_until"] = max(float(state["tier_lock_until"]), now + self.FIRST_TIER_LOCK_SECONDS)

    def reset_failure_memory(self, node_id: str) -> bool:
        """Clear runtime tier memory for one configured node without skipping an active cooldown."""
        changed = False
        now = time.monotonic()
        with self.condition:
            for state in self.states.values():
                if str(state["node_id"]) != str(node_id):
                    continue
                state["failed_tier"] = 0
                state["failed_tier_failure_times"] = []
                state["tier_lock_until"] = 0.0
                state["tier_lock_rpm"] = 0
                state["runtime_rpm_cap"] = 0
                state["recovery_mode"] = False
                state["recovery_target_rpm"] = 0
                state["tier_successes"] = 0
                state["tier_started_at"] = now
                changed = True
            if changed:
                self.condition.notify_all()
        if changed:
            self._persist()
        return changed

    def _next_tier(self, rpm: int, rpm_limit: int) -> int:
        if rpm_limit > 10 and rpm >= 10:
            return min(rpm_limit, max(rpm + 1, math.ceil(rpm * 1.25)))
        tiers = [value for value in self.RPM_TIERS if value <= rpm_limit]
        if rpm_limit not in tiers:
            tiers.append(rpm_limit)
        for value in sorted(set(tiers)):
            if value > rpm:
                return value
        return rpm

    @staticmethod
    def _downgrade_rpm(rpm: int) -> int:
        if rpm > 10:
            return max(5, math.floor(rpm * 0.7))
        if rpm >= 10:
            return 5
        if rpm >= 8:
            return 5
        if rpm >= 5:
            return 3
        return 1

    def snapshot(self, configs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self.condition:
            states = list(self.states.values())
            if configs is not None:
                states = [self._state(config)[1] for config in configs]
            for state in states:
                self._refresh_daily(state)
            return [{
                "node_id": state["node_id"],
                "base_url": state["base_url"],
                "rpm": int(state["rpm"]),
                "rpm_limit": int(state["rpm_limit"]),
                "rpd_limit": int(state["rpd_limit"]),
                "utilization_percent": int(state["utilization_percent"]),
                "safe_rpm_target": int(state["safe_rpm_target"]),
                "effective_rpm_limit": self._effective_rpm_limit(state, now),
                "in_flight": int(state["in_flight"]),
                "in_flight_limit": self._in_flight_limit(state),
                "success_streak": int(state["success_streak"]),
                "success_count": int(state["success_count"]),
                "rate_limit_count": int(state["rate_limit_count"]),
                "rate_limit_strikes": int(state["rate_limit_strikes"]),
                "unavailable_count": int(state["unavailable_count"]),
                "consecutive_unavailable": int(state["consecutive_unavailable"]),
                "average_latency": round(float(state["average_latency"]), 2),
                "cooldown_seconds": round(max(0.0, float(state["cooldown_until"]) - now), 1),
                "next_request_seconds": round(max(0.0, float(state["next_request_at"]) - now), 1),
                "tier_successes": int(state["tier_successes"]),
                "tier_elapsed_seconds": round(max(0.0, now - float(state["tier_started_at"])), 1),
                "failed_tier": int(state["failed_tier"]),
                "tier_failure_count": len(self._tier_failure_times(state, now)),
                "tier_lock_seconds": round(max(0.0, float(state["tier_lock_until"]) - now), 1),
                "runtime_rpm_capped": bool(int(state["runtime_rpm_cap"])),
                "recovery_mode": bool(state["recovery_mode"]),
                "promotion_required_seconds": int(self.recovery_window_seconds if state["recovery_mode"] else self.promotion_window_seconds),
                "promotion_required_successes": int(self.recovery_successes if state["recovery_mode"] else self.promotion_successes),
                "daily_date": state["daily_date"],
                "daily_budget": int(state["daily_budget"]),
                "daily_used": int(state["daily_used"]),
                "daily_remaining": max(0, int(state["daily_budget"]) - int(state["daily_used"])) if int(state["daily_budget"]) else None,
                "daily_exhausted": self._daily_exhausted(state),
                "daily_reset_seconds": round(self._daily_reset_seconds(), 1),
                "circuit_reason": state["circuit_reason"] if float(state["cooldown_until"]) > now else "",
                "last_status": state["last_status"],
            } for state in states]

    def overview(self) -> dict[str, int]:
        """Return queue-wide counters under the scheduler lock."""
        with self.condition:
            return {
                "global_in_flight": int(self.global_in_flight),
                "global_in_flight_limit": int(self.global_in_flight_limit),
                "global_rpm_limit": int(self.global_rpm_limit),
                "waiting": len(self.waiters),
            }

    def _reserve_any(self, configs: list[dict[str, Any]], job_id: str | None, skip_cooldown: bool = False) -> tuple[dict[str, Any], str, int]:
        ticket = object()
        with self.condition:
            self.waiters.append(ticket)
            try:
                while True:
                    if job_id:
                        ensure_job_active(job_id)
                    if self.waiters[0] is not ticket:
                        self.condition.wait(timeout=0.5)
                        continue
                    now = time.monotonic()
                    if self.global_in_flight >= self.global_in_flight_limit:
                        self.condition.wait(timeout=0.5)
                        continue
                    candidates: list[tuple[float, int, int, dict[str, Any], str, dict[str, Any]]] = []
                    quota_blocked: list[dict[str, Any]] = []
                    for index, config in enumerate(configs):
                        key, state = self._state(config)
                        if self._daily_exhausted(state):
                            quota_blocked.append(state)
                            continue
                        state["rpm"] = min(int(state["rpm"]), self._effective_rpm_limit(state, now))
                        cooldown = max(0.0, float(state["cooldown_until"]) - now)
                        if cooldown and skip_cooldown and len(configs) == 1:
                            raise ImageNodeCoolingDown(cooldown)
                        if int(state["in_flight"]) >= self._in_flight_limit(state):
                            continue
                        ready_at = max(float(state["cooldown_until"]), float(state["next_request_at"]), self.next_global_request_at)
                        candidates.append((ready_at, int(state["in_flight"]), index, config, key, state))
                    if not candidates:
                        if quota_blocked and len(quota_blocked) == len(configs):
                            raise ImageDailyQuotaExhausted(self._daily_reset_seconds())
                        self.condition.wait(timeout=0.5)
                        continue
                    ready_at, _active, _index, config, key, state = min(candidates, key=lambda item: (item[0], item[1], item[2]))
                    wait_seconds = max(0.0, ready_at - now)
                    if wait_seconds:
                        self.condition.wait(timeout=max(0.01, min(wait_seconds, 1.0)))
                        continue
                    state["next_request_at"] = now + self.window_seconds / max(1, int(state["rpm"]))
                    state["in_flight"] = int(state["in_flight"]) + 1
                    state["daily_used"] = int(state["daily_used"]) + 1
                    self.next_global_request_at = now + self.window_seconds / self.global_rpm_limit
                    self.global_in_flight += 1
                    self.waiters.pop(0)
                    self.condition.notify_all()
                    self._persist()
                    return config, key, int(state["rpm"])
            finally:
                if ticket in self.waiters:
                    self.waiters.remove(ticket)
                    self.condition.notify_all()

    def _record_failure(self, key: str, exc: Exception, job_id: str | None, *, attempted_rpm: int) -> None:
        status = exc.status_code if isinstance(exc, ProviderHTTPError) else None
        now = time.monotonic()
        with self.condition:
            state = self.states[key]
            state["in_flight"] = max(0, int(state["in_flight"]) - 1)
            self.global_in_flight = max(0, self.global_in_flight - 1)
            state["success_streak"] = 0
            state["tier_successes"] = 0
            state["tier_started_at"] = now
            state["last_status"] = status or "error"
            cooldown_seconds = 0.0
            if status == 429:
                state["rate_limit_count"] = int(state["rate_limit_count"]) + 1
                state["rate_limit_strikes"] = int(state["rate_limit_strikes"]) + 1
                retry_after = max(0.0, float(exc.retry_after or 0.0)) if isinstance(exc, ProviderHTTPError) else 0.0
                if int(state["rate_limit_strikes"]) >= 2:
                    state["rpm"] = 1
                    cooldown_seconds = max(retry_after, 900.0)
                    state["circuit_reason"] = "rate_limit"
                else:
                    state["rpm"] = self._downgrade_rpm(int(state["rpm"]))
                    cooldown_seconds = max(retry_after, 60.0, self.window_seconds / max(1, int(state["rpm"])))
                    state["circuit_reason"] = "rate_limit_cooldown"
                self._remember_failed_high_tier(state, attempted_rpm, now)
                state["rpm"] = min(int(state["rpm"]), self._effective_rpm_limit(state, now))
            elif status in {500, 502, 503, 504} or status is None:
                state["unavailable_count"] = int(state["unavailable_count"]) + 1
                state["consecutive_unavailable"] = int(state["consecutive_unavailable"]) + 1
                if int(state["consecutive_unavailable"]) >= 3:
                    cooldown_seconds = 300.0
                    state["circuit_reason"] = "unavailable"
            elif status in {401, 403}:
                cooldown_seconds = 3600.0
                state["circuit_reason"] = "authentication"
            if cooldown_seconds:
                state["cooldown_until"] = max(float(state["cooldown_until"]), now + cooldown_seconds)
            self.condition.notify_all()
        self._persist()
        if status == 429 and job_id and job_id in JOBS:
            update_job(
                job_id,
                stage=(
                    f"图片节点连续 429，已降为 1 RPM 并熔断 {math.ceil(cooldown_seconds / 60)} 分钟"
                    if int(self.states[key]["rate_limit_strikes"]) >= 2
                    else f"图片节点触发 429，已降为 {self.states[key]['rpm']} RPM 并冷却 {math.ceil(cooldown_seconds)} 秒"
                ),
            )

    def _record_success(self, key: str, latency: float) -> None:
        now = time.monotonic()
        with self.condition:
            state = self.states[key]
            state["in_flight"] = max(0, int(state["in_flight"]) - 1)
            self.global_in_flight = max(0, self.global_in_flight - 1)
            previous_count = int(state["success_count"])
            state["success_count"] = previous_count + 1
            state["average_latency"] = (float(state["average_latency"]) * previous_count + latency) / (previous_count + 1)
            state["success_streak"] = int(state["success_streak"]) + 1
            state["tier_successes"] = int(state["tier_successes"]) + 1
            state["consecutive_unavailable"] = 0
            state["last_status"] = 200
            stable = (
                int(state["tier_successes"]) >= (self.recovery_successes if state["recovery_mode"] else self.promotion_successes)
                and now - float(state["tier_started_at"]) >= (self.recovery_window_seconds if state["recovery_mode"] else self.promotion_window_seconds)
                and float(state["cooldown_until"]) <= now
            )
            if stable:
                state["rate_limit_strikes"] = 0
                promoted = self._next_tier(int(state["rpm"]), self._effective_rpm_limit(state, now))
                if promoted != int(state["rpm"]):
                    state["rpm"] = promoted
                    state["success_streak"] = 0
                if state["recovery_mode"] and int(state["rpm"]) >= int(state["recovery_target_rpm"]):
                    state["recovery_mode"] = False
                    state["recovery_target_rpm"] = 0
                state["tier_successes"] = 0
                state["tier_started_at"] = now
                state["circuit_reason"] = ""
            self.condition.notify_all()
        self._persist()

    def call_any(self, configs: list[dict[str, Any]], invoke: Any, *, job_id: str | None = None) -> dict[str, Any]:
        if not configs:
            raise RuntimeError("没有可调用的图片中转站")
        remaining = list(configs)
        errors: list[str] = []
        last_exception: Exception | None = None
        while remaining:
            service, key, attempted_rpm = self._reserve_any(remaining, job_id)
            started = time.monotonic()
            try:
                result = invoke(service)
            except Exception as exc:
                last_exception = exc
                self._record_failure(key, exc, job_id, attempted_rpm=attempted_rpm)
                position = int(service.get("_position") or configs.index(service) + 1)
                status = f"{exc.status_code} " if isinstance(exc, ProviderHTTPError) else ""
                errors.append(f"节点 {position}: {status}{exc}")
                remaining = [item for item in remaining if self.node_key(item) != key]
            else:
                self._record_success(key, max(0.0, time.monotonic() - started))
                return result
        if len(configs) == 1 and last_exception is not None:
            raise last_exception
        raise RuntimeError(f"所有可调用的图片中转站均失败（{len(configs)}）：{'；'.join(errors)}")

    def call(self, config: dict[str, Any], invoke: Any, *, retry_rate_limit: bool, skip_cooldown: bool, job_id: str | None = None) -> dict[str, Any]:
        attempts = 0
        while True:
            service, key, attempted_rpm = self._reserve_any([config], job_id, skip_cooldown=skip_cooldown)
            started = time.monotonic()
            try:
                result = invoke()
            except Exception as exc:
                self._record_failure(key, exc, job_id, attempted_rpm=attempted_rpm)
                attempts += 1
                if isinstance(exc, ProviderHTTPError) and exc.status_code == 429 and retry_rate_limit and attempts < 3:
                    continue
                raise
            else:
                self._record_success(key, max(0.0, time.monotonic() - started))
                return result


IMAGE_NODE_POOL = AdaptiveImageNodePool(
    IMAGE_NODE_STATS_PATH,
    IMAGE_GENERATION_RPM,
    max_rpm=IMAGE_GENERATION_MAX_RPM,
    global_rpm_limit=IMAGE_GENERATION_GLOBAL_RPM,
    global_in_flight_limit=IMAGE_GLOBAL_IN_FLIGHT_LIMIT,
)


def valid_image_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def valid_media_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    try:
        return probe_duration(path) > 0.1
    except Exception:
        return False


def valid_timed_video(path: Path, expected_ms: int, tolerance_seconds: float = 0.22) -> bool:
    """Reject stale scene clips whose old renderer added time past the narration."""
    if not valid_media_file(path):
        return False
    try:
        return abs(probe_duration(path) - expected_ms / 1000.0) <= tolerance_seconds
    except Exception:
        return False


def fit_scene_durations(scenes: list[dict[str, Any]], audio_duration: float) -> bool:
    """Make scene timing add up exactly to the voice track without starving the final image."""
    if not scenes:
        return False
    target_ms = max(len(scenes), round(max(0.001, audio_duration) * 1000))
    minimum_ms = min(1000, target_ms // len(scenes))
    remaining_ms = target_ms - minimum_ms * len(scenes)
    weights = [max(1, len(str(scene.get("text", "")))) for scene in scenes]
    total_weight = sum(weights)
    exact_extras = [remaining_ms * weight / total_weight for weight in weights]
    extras = [int(value) for value in exact_extras]
    leftover = remaining_ms - sum(extras)
    order = sorted(range(len(scenes)), key=lambda i: exact_extras[i] - extras[i], reverse=True)
    for index in order[:leftover]:
        extras[index] += 1
    durations = [minimum_ms + extra for extra in extras]
    changed = any(int(scene.get("duration_ms", 0)) != durations[i] for i, scene in enumerate(scenes))
    for scene, duration_ms in zip(scenes, durations):
        scene["duration_ms"] = duration_ms
    return changed


def load_config() -> dict[str, Any]:
    STATE_DIR.mkdir(exist_ok=True)
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    data = DEFAULT_CONFIG.copy()
    stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # Do not migrate the former Volcengine credential into OpenLux. A key must
    # only ever be sent to the provider it was entered for.
    for key in DEFAULT_CONFIG:
        if key in stored:
            data[key] = stored[key]
    if str(data.get("text_model", "")).startswith("doubao-"):
        data["text_model"] = DEFAULT_CONFIG["text_model"]
    if str(data.get("image_model", "")).startswith("doubao-"):
        data["image_model"] = DEFAULT_CONFIG["image_model"]
    return data


def safe_config(data: dict[str, Any]) -> dict[str, Any]:
    result = data.copy()
    result["has_api_key"] = bool(data.get("api_key"))
    result["has_image_api_key"] = bool(data.get("image_api_key"))
    return result


def configured_tts_nodes(config: dict[str, Any] | None = None) -> list[str]:
    source = config or load_config()
    nodes: list[str] = []
    for key in ("tts_url", "tts_url_2"):
        url = str(source.get(key, "")).strip().rstrip("/")
        if url and url not in nodes:
            nodes.append(url)
    return nodes


def normalized_task_name(value: Any, script: str = "", job_id: str = "") -> str:
    explicit = re.sub(r"\s+", " ", str(value or "")).strip()
    if explicit:
        return explicit[:30]
    automatic = re.sub(r"\s+", "", script.strip())[:15]
    return automatic or f"未命名任务-{job_id[-4:]}"


def request_client_ip(request: Request) -> str:
    # The API only listens on loopback and is reached through the local Vite
    # proxy. Its last forwarded address is therefore the nearest LAN client.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        candidate = forwarded.split(",")[-1].strip()
        if candidate:
            return candidate
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "未知 IP"


def update_job(job_id: str, **values: Any) -> None:
    with LOCK:
        if JOBS[job_id].get("status") == "cancelled" and values.get("status") != "cancelled":
            return
        JOBS[job_id].update(values)
        _persist_job_locked(job_id)


def begin_phase(job_id: str, key: str, label: str, stage: str, progress: int) -> None:
    now = time.time()
    with LOCK:
        job = JOBS[job_id]
        if job.get("status") == "cancelled":
            raise JobCancelled("任务已取消")
        previous = job.get("current_phase")
        previous_started = job.get("phase_started_at")
        timings = job.setdefault("timings", {})
        if previous and previous_started:
            entry = timings.setdefault(previous, {"label": previous, "seconds": 0.0})
            entry["seconds"] = float(entry.get("seconds", 0.0)) + max(0.0, now - float(previous_started))
        timings.setdefault(key, {"label": label, "seconds": 0.0})["label"] = label
        job.update(
            status="running", stage=stage, progress=progress,
            current_phase=key, phase_started_at=now,
        )
        _persist_job_locked(job_id)


def queue_for_stage(job_id: str, queue_stage: str, stage: str, progress: int) -> None:
    """Close the active timer and move a job to the next pipeline queue."""
    now = time.time()
    with LOCK:
        job = JOBS[job_id]
        if job.get("status") == "cancelled":
            raise JobCancelled("任务已取消")
        current = job.get("current_phase")
        started = job.get("phase_started_at")
        if current and started:
            entry = job.setdefault("timings", {}).setdefault(current, {"label": current, "seconds": 0.0})
            entry["seconds"] = float(entry.get("seconds", 0.0)) + max(0.0, now - float(started))
        job.update(
            status="queued", stage=stage, progress=progress,
            queue_stage=queue_stage, queue_order=time.time_ns(),
            current_phase=None, phase_started_at=None,
        )
        _persist_job_locked(job_id)


def finish_timing(job_id: str) -> None:
    now = time.time()
    with LOCK:
        job = JOBS[job_id]
        current = job.get("current_phase")
        started = job.get("phase_started_at")
        if current and started:
            entry = job.setdefault("timings", {}).setdefault(current, {"label": current, "seconds": 0.0})
            entry["seconds"] = float(entry.get("seconds", 0.0)) + max(0.0, now - float(started))
        job["current_phase"] = None
        job["phase_started_at"] = None
        job["finished_at"] = now
        job["total_elapsed"] = max(0.0, now - float(job.get("started_at", now)))
        _persist_job_locked(job_id)


def restore_jobs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK:
        for metadata in JOBS_DIR.glob("*/job.json"):
            try:
                item = json.loads(metadata.read_text(encoding="utf-8"))
                job_id = str(item.get("id") or metadata.parent.name)
                item["task_name"] = normalized_task_name(item.get("task_name"), str(item.get("copy", "")), job_id)
                if item.get("status") in {"queued", "running"}:
                    current = item.get("current_phase")
                    started = item.get("phase_started_at")
                    if current and started:
                        entry = item.setdefault("timings", {}).setdefault(current, {"label": current, "seconds": 0.0})
                        entry["seconds"] = float(entry.get("seconds", 0.0)) + max(0.0, time.time() - float(started))
                    item.update(
                        status="queued", stage="服务已恢复，正在检查任务断点", error=None,
                        current_phase=None, phase_started_at=None, finished_at=None,
                        resume_count=int(item.get("resume_count", 0)) + 1,
                    )
                JOBS[job_id] = item
                _persist_job_locked(job_id)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue


def job_snapshot(job_id: str) -> dict[str, Any]:
    now = time.time()
    with LOCK:
        source = JOBS[job_id]
        result = source.copy()
        result["task_name"] = normalized_task_name(source.get("task_name"), str(source.get("copy", "")), job_id)
        result["can_retry"] = source.get("status") == "error"
        result["can_cancel"] = source.get("status") in {"queued", "running"}
        result["image_count"] = sum(
            1
            for path in (JOBS_DIR / job_id).glob("board-*.png")
            if re.fullmatch(r"board-\d+\.png", path.name)
        )
        if (
            source.get("status") == "done"
            and result["image_count"]
            and (JOBS_DIR / job_id / "voice.wav").is_file()
            and (JOBS_DIR / job_id / "plan.json").is_file()
        ):
            result["can_rerender"] = True
        result.pop("copy", None)
        result.pop("visual_references", None)
        timings = {key: value.copy() for key, value in source.get("timings", {}).items()}
        current = source.get("current_phase")
        phase_started = source.get("phase_started_at")
        if current and phase_started and current in timings:
            timings[current]["seconds"] = float(timings[current].get("seconds", 0.0)) + max(0.0, now - float(phase_started))
            timings[current]["running"] = True
            result["current_elapsed"] = max(0.0, now - float(phase_started))
        else:
            result["current_elapsed"] = 0.0
        result["timings"] = timings
        end = source.get("finished_at") or now
        result["total_elapsed"] = max(0.0, float(end) - float(source.get("started_at", end)))
        if source.get("status") == "queued":
            order = int(source.get("queue_order", 0))
            queue_stage = str(source.get("queue_stage", "voice"))
            ahead = sum(
                1 for other_id, other in JOBS.items()
                if other_id != job_id
                and other.get("status") in {"queued", "running"}
                and str(other.get("queue_stage", "voice")) == queue_stage
                and int(other.get("queue_order", 0)) < order
            )
            result["queue_ahead"] = ahead
            queue_labels = {"voice": "语音克隆", "model": "模型调用", "render": "本地渲染"}
            label = queue_labels.get(queue_stage, "任务")
            if queue_stage == "render":
                result["stage"] = "正在进入本地渲染"
            else:
                result["stage"] = f"{label}排队中，前方 {ahead} 个任务" if ahead else f"即将开始{label}"
        return result


def run(cmd: list[str], cwd: Path = ROOT, job_id: str | None = None) -> None:
    if job_id:
        ensure_job_active(job_id)
    popen_options: dict[str, Any] = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(cmd, **popen_options)
    if job_id:
        with RUNNING_PROCESSES_LOCK:
            RUNNING_PROCESSES.setdefault(job_id, set()).add(process)
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if job_id and is_job_cancelled(job_id):
                    terminate_running_process(job_id)
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise JobCancelled("任务已取消")
        if process.returncode:
            raise RuntimeError((stderr or stdout)[-3000:])
        if job_id:
            ensure_job_active(job_id)
    finally:
        if job_id:
            with RUNNING_PROCESSES_LOCK:
                processes = RUNNING_PROCESSES.get(job_id)
                if processes is not None:
                    processes.discard(process)
                    if not processes:
                        RUNNING_PROCESSES.pop(job_id, None)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def extract_response_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return payload["output_text"]
    pieces = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                pieces.append(content.get("text", ""))
    for choice in payload.get("choices", []):
        message = choice.get("message", {})
        content = message.get("content", choice.get("text", ""))
        if isinstance(content, str):
            pieces.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                    pieces.append(str(part.get("text", "")))
    return "\n".join(pieces)


def parse_json_block(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = min([p for p in (text.find("["), text.find("{")) if p >= 0], default=0)
    end = max(text.rfind("]"), text.rfind("}"))
    return json.loads(text[start : end + 1])


class ProviderHTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def response_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone

            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def provider_retry_delay(attempt: int) -> int:
    return (3, 8, 15)[min(attempt, 2)]


def image_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    """Allow image calls to use a dedicated provider endpoint.

    Image requests may target a different gateway than text requests (for
    example an OpenAI-compatible aggregator that only serves GPT Image).
    Empty values fall back to the shared base_url / api_key so existing
    configs keep working unchanged.
    """
    resolved = dict(config)
    base_url = str(config.get("image_base_url") or "").strip()
    api_key = str(config.get("image_api_key") or "").strip()
    if re.match(r"^https?://", base_url, flags=re.I):
        resolved["base_url"] = base_url
    if api_key:
        resolved["api_key"] = api_key
    return resolved


def provider_post(config: dict[str, Any], endpoint: str, payload: dict[str, Any], timeout: float = 1800, job_id: str | None = None, attempts: int = 3) -> dict[str, Any]:
    if not config.get("api_key"):
        raise RuntimeError("请先在 API 设置中填写 API Key")
    last_error: Exception | None = None
    attempts = max(1, attempts)
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{config['base_url'].rstrip('/')}/{endpoint.lstrip('/')}",
                    headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
                    json=payload,
                )
            if response.is_error:
                error = ProviderHTTPError(
                    response.status_code,
                    f"模型服务调用失败：{response.status_code} {response.text[:800]}",
                    response_retry_after(response),
                )
                if response.status_code not in {408, 409, 425, 429, 500, 502, 503, 504}:
                    raise error
                raise error
            return response.json()
        except (httpx.TimeoutException, httpx.TransportError, ProviderHTTPError) as exc:
            last_error = exc
            retryable = not isinstance(exc, ProviderHTTPError) or exc.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
            if isinstance(exc, ProviderHTTPError) and exc.status_code == 429:
                retryable = False
            message = str(exc).lower()
            if isinstance(exc, ProviderHTTPError) and any(token in message for token in (
                "upstream rate limit", "model_not_found", "no available channel", "get_channel_failed",
            )):
                retryable = False
            if not retryable or attempt == attempts - 1:
                raise
            if job_id and job_id in JOBS:
                update_job(job_id, stage=f"模型服务暂时异常，正在自动重试 {attempt + 2}/{attempts}", model_retry_count=int(JOBS[job_id].get("model_retry_count", 0)) + 1)
            time.sleep(provider_retry_delay(attempt))
    raise RuntimeError(f"模型服务重试失败：{last_error}")


def provider_text_once(config: dict[str, Any], model: str, prompt: str, timeout: float = 1800, job_id: str | None = None, attempts: int = 3) -> dict[str, Any]:
    """Call either generation API used by OpenAI-compatible gateways.

    Newer providers expose ``/responses`` while many relay services only
    implement ``/chat/completions``. Prefer Responses and transparently fall
    back when that route is unsupported.
    """
    try:
        return provider_post(config, "responses", {"model": model, "input": prompt}, timeout=timeout, job_id=job_id, attempts=attempts)
    except ProviderHTTPError as exc:
        if exc.status_code not in {400, 404, 405, 501}:
            raise
    return provider_post(
        config,
        "chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
        job_id=job_id,
        attempts=attempts,
    )


def provider_text_single(config: dict[str, Any], model: str, prompt: str, timeout: float = 1800, job_id: str | None = None, attempts: int = 3) -> dict[str, Any]:
    """Call text generation and fail over across models advertised by a relay."""
    advertised = [str(item) for item in config.get("_text_models", []) if str(item)]
    candidates = [model, *(item for item in advertised if item != model)]
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        try:
            payload = provider_text_once(config, candidate, prompt, timeout=timeout, job_id=job_id, attempts=attempts)
            actual_model = str(payload.get("model") or candidate)
            if job_id and job_id in JOBS:
                update_job(job_id, text_model=actual_model)
            return payload
        except ProviderHTTPError as exc:
            last_error = exc
            unavailable = exc.status_code in {429, 500, 502, 503, 504}
            if not unavailable or index == len(candidates) - 1:
                raise
            if job_id and job_id in JOBS:
                update_job(job_id, stage=f"模型 {candidate} 暂不可用，自动切换到 {candidates[index + 1]}")
    raise RuntimeError(f"没有可用的文本模型：{last_error}")


def provider_text(config: dict[str, Any], model: str, prompt: str, timeout: float = 1800, job_id: str | None = None) -> dict[str, Any]:
    plan = provider_service_plan(config, "text")
    attempts = 1 if plan["ready_count"] > 1 else 3
    return provider_service_failover(
        plan,
        "文本中转站",
        lambda service: provider_text_single(service, str(service.get("model") or model), prompt, timeout=timeout, job_id=job_id, attempts=attempts),
        job_id=job_id,
    )


def provider_image_single(config: dict[str, Any], endpoint: str, payload: dict[str, Any], timeout: float = 1800, job_id: str | None = None, attempts: int = 3) -> dict[str, Any]:
    """Call exactly one selected model; relay/model failover happens outside the RPM gate."""
    selected = str(payload.get("model") or config.get("image_model") or "")
    response_payload = provider_post(
        config,
        endpoint,
        {**payload, "model": selected},
        timeout=timeout,
        job_id=job_id,
        attempts=attempts,
    )
    actual_model = str(response_payload.get("model") or selected)
    if job_id and job_id in JOBS:
        update_job(job_id, image_model=actual_model)
    return response_payload


def provider_image(config: dict[str, Any], endpoint: str, payload: dict[str, Any], timeout: float = 1800, job_id: str | None = None) -> dict[str, Any]:
    plan = provider_service_plan(config, "image")
    ready = [dict(item["service"], _position=int(item["position"])) for item in plan["ready"]]
    if not ready:
        skipped = "，".join(f"节点 {item['position']} {item['reason']}" for item in plan["skipped"])
        raise RuntimeError(f"没有可调用的图片中转站{'：' + skipped if skipped else ''}")
    # Every outbound image HTTP start must pass through the RPM scheduler.
    # Internal provider retries would bypass that gate, so each reservation
    # always represents exactly one upstream request.
    attempts = 1
    if len(ready) == 1:
        service = ready[0]
        return IMAGE_NODE_POOL.call(
            service,
            lambda: provider_image_single(
                service,
                endpoint,
                {**payload, "model": str(service.get("model") or payload.get("model") or config.get("image_model") or "")},
                timeout=timeout,
                job_id=job_id,
                attempts=attempts,
            ),
            retry_rate_limit=True,
            skip_cooldown=False,
            job_id=job_id,
        )
    return IMAGE_NODE_POOL.call_any(
        ready,
        lambda service: provider_image_single(
                service,
                endpoint,
                {**payload, "model": str(service.get("model") or payload.get("model") or config.get("image_model") or "")},
                timeout=timeout,
                job_id=job_id,
                attempts=attempts,
        ),
        job_id=job_id,
    )


def provider_image_edit_once(config: dict[str, Any], form_data: dict[str, str], raw_files: list[tuple[str, bytes, str]], timeout: float = 1800) -> dict[str, Any]:
    response: httpx.Response | None = None
    with httpx.Client(timeout=timeout) as client:
        for field_name in ("image", "image[]"):
            files = [(field_name, (name, content, mime)) for name, content, mime in raw_files]
            response = client.post(
                f"{config['base_url'].rstrip('/')}/images/edits",
                headers={"Authorization": f"Bearer {config['api_key']}"},
                data=form_data,
                files=files,
            )
            if not response.is_error or response.status_code not in {400, 422}:
                break
    if response is None or response.is_error:
        status = response.status_code if response is not None else 500
        detail = response.text[:800] if response is not None else "没有响应"
        raise ProviderHTTPError(status, f"参考图调用失败：{status} {detail}", response_retry_after(response) if response is not None else None)
    return response.json()


def provider_image_edit(config: dict[str, Any], form_data: dict[str, str], raw_files: list[tuple[str, bytes, str]], timeout: float = 1800, job_id: str | None = None) -> dict[str, Any]:
    plan = provider_service_plan(config, "image")
    ready = [dict(item["service"], _position=int(item["position"])) for item in plan["ready"]]
    if not ready:
        skipped = "，".join(f"节点 {item['position']} {item['reason']}" for item in plan["skipped"])
        raise RuntimeError(f"没有可调用的参考图中转站{'：' + skipped if skipped else ''}")
    if len(ready) == 1:
        service = ready[0]
        return IMAGE_NODE_POOL.call(
            service,
            lambda: provider_image_edit_once(
                service,
                {**form_data, "model": str(service.get("model") or form_data.get("model") or "")},
                raw_files,
                timeout=timeout,
            ),
            retry_rate_limit=True,
            skip_cooldown=False,
            job_id=job_id,
        )
    return IMAGE_NODE_POOL.call_any(
        ready,
        lambda service: provider_image_edit_once(
                service,
                {**form_data, "model": str(service.get("model") or form_data.get("model") or "")},
                raw_files,
                timeout=timeout,
        ),
        job_id=job_id,
    )


def provider_models(config: dict[str, Any], timeout: float = 30) -> set[str]:
    if not config.get("api_key"):
        raise RuntimeError("请先在 API 设置中填写 API Key")
    if not re.match(r"^https?://", str(config.get("base_url") or ""), flags=re.I):
        raise RuntimeError("接口地址必须以 http:// 或 https:// 开头")
    cache_key = (str(config["base_url"]).rstrip("/"), str(config["api_key"]))
    now = time.monotonic()
    with MODEL_CATALOG_CACHE_LOCK:
        cached = MODEL_CATALOG_CACHE.get(cache_key)
        if cached and now - cached[0] < MODEL_CATALOG_CACHE_TTL_SECONDS:
            return set(cached[1])
    with httpx.Client(timeout=timeout) as client:
        response = client.get(
            f"{config['base_url'].rstrip('/')}/models",
            headers={"Authorization": f"Bearer {config['api_key']}"},
        )
        if response.is_error:
            # The models route is optional in OpenAI-compatible relays. An
            # absent route means availability must be verified on first use.
            if response.status_code in {404, 405, 501}:
                return set()
            raise ProviderHTTPError(response.status_code, f"模型列表读取失败：{response.status_code} {response.text[:800]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("模型列表接口没有返回有效 JSON，请检查接口地址是否包含正确的 /v1 路径") from exc
    models = {str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")}
    with MODEL_CATALOG_CACHE_LOCK:
        MODEL_CATALOG_CACHE[cache_key] = (time.monotonic(), set(models))
    return models


def _is_image_model(model: str) -> bool:
    value = model.lower()
    return any(token in value for token in ("gpt-image", "dall-e", "imagen", "flux", "stable-diffusion", "ideogram", "recraft"))


def _is_text_model(model: str) -> bool:
    value = model.lower()
    excluded = (
        "embedding", "moderation", "whisper", "tts", "speech", "transcri", "rerank",
        "codex", "review", "realtime", "audio", "vision-preview",
    )
    return not _is_image_model(model) and not any(token in value for token in excluded)


def _preferred_model(models: list[str], configured: str, priorities: tuple[str, ...]) -> str:
    if configured in models:
        return configured
    return next((model for token in priorities for model in models if token in model.lower()), models[0] if models else configured)


def build_model_catalog(models: set[str], text_model: str, image_model: str) -> dict[str, Any]:
    """Classify a provider's model list and choose usable defaults."""
    text_models = sorted(model for model in models if _is_text_model(model))
    image_models = sorted(model for model in models if _is_image_model(model))
    return {
        "text_models": text_models,
        "image_models": image_models,
        "selected_text_model": _preferred_model(text_models, text_model, ("gpt-5", "gpt-4.1", "claude", "gemini", "qwen", "deepseek", "glm")),
        "selected_image_model": _preferred_model(image_models, image_model, ("gpt-image", "dall-e", "imagen", "flux", "recraft")),
    }


def merged_provider_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge submitted settings with the saved provider configuration."""
    config = load_config()
    for key, value in payload.items():
        if key not in DEFAULT_CONFIG or (key in ("api_key", "image_api_key") and isinstance(value, str) and "••••" in value):
            continue
        if key in ("tts_url_2", "image_base_url", "image_api_key") and isinstance(value, str):
            config[key] = value.strip()
        elif value:
            config[key] = value
    return config


def resolve_configured_models(config: dict[str, Any]) -> dict[str, Any]:
    """Refresh configured model names from provider catalogs when available."""
    resolved = dict(config)
    # Candidate lists are runtime data. Never reuse a previously persisted
    # multi-model queue: every refresh selects exactly one provider-advertised
    # model for text and one for images.
    resolved.pop("_text_models", None)
    resolved.pop("_image_models", None)
    text_models: set[str] = set()
    try:
        text_models = provider_models(config)
        if text_models:
            catalog = build_model_catalog(text_models, str(config["text_model"]), str(config["image_model"]))
            if catalog["text_models"]:
                resolved["text_model"] = catalog["selected_text_model"]
                resolved["_text_models"] = [catalog["selected_text_model"]]
    except Exception:
        pass
    try:
        image_config = image_provider_config(config)
        image_models = text_models if image_config.get("base_url") == config.get("base_url") and image_config.get("api_key") == config.get("api_key") else provider_models(image_config)
        if image_models:
            catalog = build_model_catalog(image_models, str(resolved["text_model"]), str(config["image_model"]))
            if catalog["image_models"]:
                resolved["image_model"] = catalog["selected_image_model"]
                resolved["_image_models"] = [catalog["selected_image_model"]]
    except Exception:
        pass
    return resolved


def provider_service_plan(config: dict[str, Any], kind: str) -> dict[str, Any]:
    """Describe every configured relay and retain original node positions."""
    if kind == "image":
        IMAGE_NODE_POOL.configure(
            global_rpm_limit=max(1, min(500, int(config.get("image_global_rpm_limit") or IMAGE_GENERATION_GLOBAL_RPM))),
            global_in_flight_limit=max(10, min(500, int(config.get("image_global_in_flight_limit") or IMAGE_GLOBAL_IN_FLIGHT_LIMIT))),
        )
    key = "text_services" if kind == "text" else "image_services"
    raw_services = config.get(key)
    if not isinstance(raw_services, list) or not raw_services:
        fallback = dict(config) if kind == "text" else image_provider_config(config)
        if kind == "image":
            fallback["rpm_limit"] = max(1, min(IMAGE_GENERATION_MAX_RPM, int(fallback.get("rpm_limit") or 10)))
            fallback["rpd_limit"] = max(0, min(100000, int(fallback.get("rpd_limit") or 0)))
            fallback["utilization_percent"] = max(10, min(100, int(fallback.get("utilization_percent") or 80)))
        return {"configured_count": 1, "ready_count": 1, "ready": [{"position": 1, "service": fallback}], "skipped": []}

    ready: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    services = [item for item in raw_services if isinstance(item, dict)]
    for position, item in enumerate(services, 1):
        if not item.get("enabled", True):
            skipped.append({"position": position, "reason": "已停用"})
            continue
        missing: list[str] = []
        if not str(item.get("base_url") or "").strip():
            missing.append("接口地址")
        if not str(item.get("api_key") or "").strip():
            missing.append("API Key")
        if not str(item.get("model") or "").strip():
            missing.append("模型")
        if missing:
            skipped.append({"position": position, "reason": f"缺少 {'、'.join(missing)}"})
            continue
        service = dict(item)
        if kind == "image":
            try:
                service["rpm_limit"] = max(1, min(IMAGE_GENERATION_MAX_RPM, int(service.get("rpm_limit") or 10)))
            except (TypeError, ValueError):
                service["rpm_limit"] = 10
            try:
                service["rpd_limit"] = max(0, min(100000, int(service.get("rpd_limit") or 0)))
            except (TypeError, ValueError):
                service["rpd_limit"] = 0
            try:
                service["utilization_percent"] = max(10, min(100, int(service.get("utilization_percent") or 80)))
            except (TypeError, ValueError):
                service["utilization_percent"] = 80
        ready.append({"position": position, "service": service})
    return {"configured_count": len(services), "ready_count": len(ready), "ready": ready, "skipped": skipped}


def provider_service_failover(plan: dict[str, Any], label: str, invoke: Any, job_id: str | None = None) -> dict[str, Any]:
    """Run text and image relays with shared counting, status, and error reporting."""
    configured = int(plan.get("configured_count") or 0)
    ready = list(plan.get("ready") or [])
    skipped = list(plan.get("skipped") or [])
    skipped_text = "，".join(f"节点 {item['position']} {item['reason']}" for item in skipped)
    if not ready:
        detail = f"：{skipped_text}" if skipped_text else ""
        raise RuntimeError(f"没有可调用的{label}{detail}")
    errors: list[str] = []
    for ready_index, item in enumerate(ready):
        position = int(item["position"])
        if ready_index and job_id and job_id in JOBS:
            suffix = f"（{len(ready)} 个可调用"
            if skipped_text:
                suffix += f"，{skipped_text}"
            suffix += "）"
            update_job(job_id, stage=f"正在切换{label} {position}/{configured}{suffix}")
        try:
            return invoke(dict(item["service"]))
        except Exception as exc:
            status = f"{exc.status_code} " if isinstance(exc, ProviderHTTPError) else ""
            errors.append(f"节点 {position}: {status}{exc}")
    raise RuntimeError(f"所有可调用的{label}均失败（{len(ready)}/{configured}）：{'；'.join(errors)}")


def text_provider_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item["service"]) for item in provider_service_plan(config, "text")["ready"]]


def image_provider_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item["service"]) for item in provider_service_plan(config, "image")["ready"]]


def script_units(copy: str) -> list[str]:
    """Use the writer's sentence and paragraph boundaries as semantic units."""
    return [x.strip() for x in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", copy) if x.strip()]


def normalized_semantic_text(value: str) -> str:
    return "".join(character.lower() for character in str(value) if character.isalnum())


def validate_infographic_cues(pages: list[dict[str, Any]], units: list[str]) -> None:
    """Require every semantic element to have an ordered, exact source anchor."""
    for page_index, page in enumerate(pages, 1):
        indexes = [int(value) for value in page.get("source_units") or []]
        page_source = normalized_semantic_text("".join(units[index - 1] for index in indexes))
        nodes = page.get("nodes")
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 5:
            raise RuntimeError(f"第 {page_index} 页 nodes 必须包含 1～5 项")
        if not all(isinstance(node, str) and node.strip() for node in nodes):
            raise RuntimeError(f"第 {page_index} 页 nodes 必须全部是短文字")
        required_ids = {"page-title", "illustration", *(f"node-{index + 1}" for index in range(len(nodes)))}
        if str(page.get("conclusion") or "").strip():
            required_ids.add("conclusion")
        cues = page.get("cues")
        if not isinstance(cues, list) or not 1 <= len(cues) <= 6:
            raise RuntimeError(f"第 {page_index} 页必须包含 1～6 个语义 Cue")
        entered: list[str] = []
        cursor = 0
        for cue_index, cue in enumerate(cues, 1):
            if not isinstance(cue, dict):
                raise RuntimeError(f"第 {page_index} 页第 {cue_index} 个 Cue 结构无效")
            anchor = normalized_semantic_text(str(cue.get("anchor_text") or ""))
            if len(anchor) < 2:
                raise RuntimeError(f"第 {page_index} 页第 {cue_index} 个 Cue 缺少至少两个字的原文锚点")
            position = page_source.find(anchor, cursor)
            if position < 0:
                raise RuntimeError(f"第 {page_index} 页 Cue 锚点不是按顺序摘录的本页原文：{cue.get('anchor_text', '')}")
            cursor = position + len(anchor)
            enter_ids = [str(value) for value in cue.get("enter_ids") or []]
            unknown = set(enter_ids) - required_ids
            if unknown:
                raise RuntimeError(f"第 {page_index} 页 Cue 引用了未知元素：{', '.join(sorted(unknown))}")
            focus_id = str(cue.get("focus_id") or "")
            if focus_id not in required_ids:
                raise RuntimeError(f"第 {page_index} 页 Cue 的 focus_id 无效：{focus_id}")
            entered.extend(enter_ids)
        missing = required_ids - set(entered)
        duplicate = sorted({value for value in entered if entered.count(value) > 1})
        if missing:
            raise RuntimeError(f"第 {page_index} 页以下元素没有绑定 Cue：{', '.join(sorted(missing))}")
        if duplicate:
            raise RuntimeError(f"第 {page_index} 页以下元素重复绑定 Cue：{', '.join(duplicate)}")


def split_script(copy: str, target_count: int) -> list[str]:
    # Prefer complete sentences and paragraphs so a scene follows the copy.
    units = script_units(copy)
    if not units:
        return [copy]
    target_count = max(1, min(target_count, len(units)))
    groups: list[str] = []
    cursor = 0
    for group_index in range(target_count):
        remaining_groups = target_count - group_index
        remaining_units = len(units) - cursor
        if remaining_groups == 1:
            groups.append("".join(units[cursor:]).strip())
            break
        remaining_chars = sum(len(x) for x in units[cursor:])
        target_chars = remaining_chars / remaining_groups
        take = 0
        length = 0
        while take < remaining_units - (remaining_groups - 1):
            unit_len = len(units[cursor + take])
            if take and length + unit_len > target_chars * 1.18:
                break
            length += unit_len
            take += 1
            if length >= target_chars * 0.82:
                break
        take = max(1, take)
        groups.append("".join(units[cursor:cursor + take]).strip())
        cursor += take
    return groups


def scene_limit_for_duration(duration: float) -> int:
    """Allow up to ten scenes per minute, capped at twenty per task."""
    return max(1, min(20, math.ceil(max(0.0, duration) * 10 / 60)))


def numbered_section_topics(copy: str) -> list[str]:
    matches = re.finditer(r"(?:^|[“”\"'\s])([1-9])\s*[.．、]\s*([^：:\n。！？!?]{2,18})\s*[：:]", copy)
    topics: list[str] = []
    expected = 1
    for match in matches:
        number = int(match.group(1))
        if number != expected:
            continue
        topic = re.sub(r"^[\s“”\"']+|[\s“”\"']+$", "", match.group(2)).strip()
        if topic:
            topics.append(topic)
            expected += 1
    return topics if 3 <= len(topics) <= 8 else []


def _allows_directional_relation(text: str, relation_type: str) -> bool:
    if relation_type == "sequence":
        return bool(re.search(r"首先|然后|接着|随后|最后|第[一二三四五六七八九]步|步骤", text))
    if relation_type == "cause":
        return bool(re.search(r"因为|所以|导致|因此|从而|结果是|原因", text))
    return False


DECK_LAYOUTS = {
    "overview", "question", "focus", "principle", "comparison", "evidence",
    "layers", "case", "path", "flow", "cause", "cycle", "timeline", "summary",
}
DECK_COMPOSITIONS = {"split-right", "split-left", "center-stage", "top-bottom", "full-width"}


def _fallback_layout(page_text: str, role: str, relation_type: str, key_count: int, page_index: int) -> str:
    if role == "overview":
        return "overview"
    if role == "summary" or re.search(r"总结|归纳|记住|最后|总之", page_text):
        return "summary"
    if "？" in page_text or "?" in page_text:
        return "question"
    if relation_type == "comparison" or re.search(r"相比|对比|而不是|一边|另一边|彼|己", page_text):
        return "comparison"
    if relation_type == "cause":
        return "cause"
    if relation_type == "sequence":
        return "path"
    if re.search(r"案例|例如|比如|数据|证据|调查|研究", page_text):
        return "case" if page_index % 2 else "evidence"
    if re.search(r"本质|原则|核心|关键|定义|意味着", page_text):
        return "principle"
    if key_count >= 4:
        return "layers"
    return ("focus", "evidence", "case")[page_index % 3]


def _default_composition(layout_type: str, page_index: int) -> str:
    if layout_type in {"question", "principle", "cycle"}:
        return "center-stage"
    if layout_type in {"path", "flow", "cause", "timeline", "layers"}:
        return "full-width" if page_index % 2 else "top-bottom"
    if layout_type in {"comparison", "case"}:
        return "top-bottom" if page_index % 2 else "full-width"
    return "split-left" if page_index % 2 == 0 else "split-right"


def normalize_deck_pages(candidate: list[dict[str, Any]], copy: str, phrase_timeline: dict[str, Any]) -> list[dict[str, Any]]:
    phrases = phrase_timeline.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        raise RuntimeError("生成 PPT 结构前必须先有完整短语时间表")
    phrase_by_id = {str(item.get("id")): item for item in phrases if isinstance(item, dict) and item.get("id")}
    all_phrase_ids = [str(item.get("id")) for item in phrases if isinstance(item, dict) and item.get("id")]
    order = {phrase_id: index for index, phrase_id in enumerate(all_phrase_ids)}
    pages: list[dict[str, Any]] = []
    used_phrase_ids: list[str] = []
    series_title = ""
    previous_layout = ""
    previous_composition = ""
    for page_index, raw in enumerate(candidate, 1):
        source_ids = [str(value) for value in raw.get("source_phrase_ids") or []]
        if not source_ids or any(value not in phrase_by_id for value in source_ids):
            raise RuntimeError(f"第 {page_index} 页缺少有效 source_phrase_ids")
        positions = [order[value] for value in source_ids]
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise RuntimeError(f"第 {page_index} 页必须引用连续的短语编号")
        used_phrase_ids.extend(source_ids)
        page_text = "".join(str(phrase_by_id[value].get("text") or "") for value in source_ids)
        role = str(raw.get("role") or "detail")
        role = role if role in {"overview", "detail", "transition", "summary"} else "detail"
        layout_type = str(raw.get("layout_type") or "")
        relation_type = str(raw.get("relationship_type") or "none")
        relation_type = relation_type if relation_type in {"none", "sequence", "cause", "comparison", "hierarchy"} else "none"
        if role == "overview" or relation_type in {"sequence", "cause"} and not _allows_directional_relation(page_text, relation_type):
            relation_type = "none"

        raw_items = raw.get("key_items") or raw.get("nodes") or []
        key_items: list[dict[str, str]] = []
        for item in raw_items[:6] if isinstance(raw_items, list) else []:
            label = str(item.get("label") or item.get("text") or "") if isinstance(item, dict) else str(item)
            trigger = str(item.get("trigger_phrase_id") or source_ids[0]) if isinstance(item, dict) else source_ids[0]
            label = label.strip()[:16]
            if label:
                key_items.append({"label": label, "trigger_phrase_id": trigger})
        if not key_items:
            raise RuntimeError(f"第 {page_index} 页没有可显示的关键词")
        fallback_layout = _fallback_layout(page_text, role, relation_type, len(key_items), page_index)
        if layout_type not in DECK_LAYOUTS:
            layout_type = fallback_layout
        if layout_type == previous_layout and role == "detail" and fallback_layout != previous_layout:
            layout_type = fallback_layout
        composition = str(raw.get("composition") or "")
        if composition not in DECK_COMPOSITIONS:
            composition = _default_composition(layout_type, page_index)
        if composition == previous_composition and layout_type not in {"question", "principle", "cycle"}:
            composition = _default_composition(layout_type, page_index + 1)
        trigger_fields = {
            "page_title_trigger_phrase_id": str(raw.get("page_title_trigger_phrase_id") or source_ids[0]),
            "illustration_trigger_phrase_id": str(raw.get("illustration_trigger_phrase_id") or source_ids[0]),
            "conclusion_trigger_phrase_id": str(raw.get("conclusion_trigger_phrase_id") or source_ids[-1]),
        }
        for item in key_items:
            if item["trigger_phrase_id"] not in source_ids:
                raise RuntimeError(f"第 {page_index} 页关键词“{item['label']}”引用了本页之外的短语")
        if any(value not in source_ids for value in trigger_fields.values()):
            raise RuntimeError(f"第 {page_index} 页存在跨页元素时间绑定")

        series_title = series_title or str(raw.get("series_title") or copy[:30]).strip()[:30]
        illustration = raw.get("illustration_elements") or []
        illustration = [str(value.get("label") or "") if isinstance(value, dict) else str(value) for value in illustration]
        illustration = [value.strip()[:24] for value in illustration if value.strip()][:3]
        page = {
            "source_phrase_ids": source_ids,
            "series_title": series_title,
            "chapter_title": str(raw.get("chapter_title") or raw.get("page_title") or "本章要点").strip()[:24],
            "page_title": str(raw.get("page_title") or raw.get("primary_sentence") or "本页重点").strip()[:24],
            "key_text": str(raw.get("key_text") or raw.get("page_title") or "本页重点").strip()[:16],
            "role": role,
            "layout_type": layout_type,
            "composition": composition,
            "relationship_type": relation_type,
            "key_items": key_items,
            "nodes": [item["label"] for item in key_items],
            "conclusion": str(raw.get("conclusion") or "").strip()[:20],
            "core_idea": str(raw.get("core_idea") or raw.get("concept") or raw.get("page_title") or "").strip()[:80],
            "concept": str(raw.get("core_idea") or raw.get("concept") or raw.get("page_title") or "").strip()[:80],
            "visual_strategy": str(raw.get("visual_strategy") or "左侧文字，右侧主题插图").strip()[:80],
            "narrative_link": str(raw.get("narrative_link") or "承接本页旁白并进入下一部分").strip()[:80],
            "illustration_elements": illustration or [item["label"] for item in key_items[:2]],
            "text": page_text,
            "_plan_mode": "narrated_deck_v4",
            **trigger_fields,
        }
        pages.append(page)
        previous_layout = layout_type
        previous_composition = composition

    if used_phrase_ids != all_phrase_ids:
        raise RuntimeError("PPT 页面没有按顺序完整覆盖全部短语")

    topics = numbered_section_topics(copy)
    if topics and pages:
        first_page = pages[0]
        trigger = next(
            (
                phrase_id for phrase_id in first_page["source_phrase_ids"]
                if re.search(rf"(?:这|以下)?{len(topics)}项", str(phrase_by_id[phrase_id].get("text") or ""))
            ),
            first_page["source_phrase_ids"][-1],
        )
        first_page["role"] = "overview"
        first_page["layout_type"] = "overview"
        first_page["composition"] = "split-right"
        first_page["relationship_type"] = "none"
        first_page["key_items"] = [{"label": topic[:16], "trigger_phrase_id": trigger} for topic in topics]
        first_page["nodes"] = topics
        first_page["illustration_elements"] = ["儿童大脑侧面轮廓", "被五种训练共同激活的脑区", "柔和发光的神经连接"]
        first_page["concept"] = f"用一页总览明确列出{len(topics)}项训练，右侧用大脑插图解释整体主题"
    return pages


def make_plan(
    config: dict[str, Any],
    copy: str,
    duration: float,
    style: str,
    character_context: str = "",
    job_id: str | None = None,
    infographic: bool = False,
    phrase_timeline: dict[str, Any] | None = None,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
) -> list[dict[str, Any]]:
    # The copy decides how many meaningful scenes exist. Duration only caps
    # their density so short narration never receives too many images.
    source_units = script_units(copy) or [copy.strip()]
    phrase_items = phrase_timeline.get("phrases") if infographic and isinstance(phrase_timeline, dict) else None
    if infographic and (not isinstance(phrase_items, list) or not phrase_items):
        raise RuntimeError("动态 PPT 必须先完成短语与真实旁白时间对齐")
    requested_count = min(len(phrase_items) if isinstance(phrase_items, list) else len(source_units), scene_limit_for_duration(duration))
    segments = split_script(copy, requested_count)
    scene_count = len(segments)
    fixed_segments = "\n".join(f"第{i + 1}幕原文：{text}" for i, text in enumerate(segments))
    character_rule = (
        f"可用人物如下：{character_context}。根据原文语义选择出场人物，并在 title、concept 和 elements 中写明人物名称；不得改变人物身份与外观。"
        if character_context else identity_prompt(identity_mode)
    )
    paper_rule = (
        "额外为每幕输出 visual_structure 和 metaphor：visual_structure 只能从定义、流程、对比、层级、因果、清单、时间、矩阵中选择一项；"
        "metaphor 只写一个可被画出的核心隐喻。不要把文案中的每个名词都转成图标。"
        if style == PAPER_METAPHOR_STYLE else ""
    )
    if infographic:
        oil_visual_rule = (
            "13. 当前风格的插图证据从四类中择一：概念解释用具体隐喻呈现从复杂到清晰；机制流程用物件、通道和状态变化；"
            "对比关系用左右两组可比对象；角色场景用动作和环境物件。每页只选最匹配的一类并写进 visual_strategy，"
            "不要把四类混在一页，也不要为了出现固定角色而改变原意。\n"
            if style == OIL_VISUAL_STYLE else ""
        )
        numbered_phrases = "\n".join(
            f"[{item['id']}｜{item['spoken_start_ms']}–{item['spoken_end_ms']}ms] {item['text']}"
            for item in phrase_items
        )
        prompt = f"""你是中文口播动态 PPT 的内容编辑。短语与真实音频时间已经在上一步确定；你只梳理页面结构，不得重新估算时间。
总口播时长约 {duration:.1f} 秒，最多 {requested_count} 页。画面风格和插图在后续步骤处理。
人物身份策略：{character_rule}

分页原则：
1. 一般用本页第一条短语作为中心句的依据，浓缩为 page_title；关键词只辅助中心句，不得抢成另一套观点。
2. 如果开头提到“以下N项/这N项”，且全文随后存在 1、2、3…编号章节，必须单独生成 role=overview 的总览页；key_items 必须使用后文各编号章节名称，不能改写为能力、效果或抽象概念。
3. source_phrase_ids 必须将下方短语按顺序连续分组，每个短语编号恰好使用一次。
4. key_items 为 1～6 个短词条，每项包含 label 和 trigger_phrase_id。label 是 PPT 上真正显示的文字；trigger_phrase_id 必须属于本页，表示该词条何时出现。
5. page_title_trigger_phrase_id、illustration_trigger_phrase_id、conclusion_trigger_phrase_id 也必须属于本页。只选择短语编号，不输出毫秒或帧号。
6. relationship_type 默认且优先使用 none。只有原文明说“首先→然后→最后”才能用 sequence，明确说“因为→所以/导致”才能用 cause；普通并列清单、训练名称、能力解释一律 none，不得画箭头。
7. role 只能是 overview、detail、transition、summary。layout_type 必须按语义选择：
   - overview：明确列出全文大纲；question：问题、悬念或反问；focus：单一强观点；principle：定义、原则或中心法则；
   - comparison：两方对照；evidence：论点加证据条；layers：多层递进；case：案例或数据；
   - path/flow/timeline：原文明示的步骤、阶段或时间过程；cause：明确因果；cycle：明确循环；summary：编号总结。
   普通 detail 页不能连续三页使用同一 layout_type。
8. series_title 全片一致；同一章节的 chapter_title 连续保持，真正换章节才改变。
9. illustration_elements 只写 1～3 个具体可画主体。插图不负责排版、文字、箭头、连接线或流程关系。

10. 每页遵循“核心观点 → 一句清晰的 page_title → visual_strategy → narrative_link”四步。core_idea 说明本页唯一信息；visual_strategy 说明 PPT 如何呈现；narrative_link 说明它在全文中承上启下的作用。
11. composition 决定页面空间：split-right（文字左、插图右）、split-left（插图左、文字右）、center-stage（中心舞台）、top-bottom（上下结构）、full-width（横向通栏）。相邻页面尽量改变 composition；不得为了变化而违背语义。
12. 同一页不是静态海报：把 key_items 分别绑定到真正说到它们的短语，让标题、插图、关键词、证据和结论逐层累积出现。
{oil_visual_rule}

每页输出：source_phrase_ids、series_title、chapter_title、core_idea、page_title、page_title_trigger_phrase_id、key_text、role、layout_type、composition、relationship_type、key_items、conclusion、conclusion_trigger_phrase_id、visual_strategy、narrative_link、illustration_elements、illustration_trigger_phrase_id。
只返回 JSON 数组，不要解释。

完整短语时间表：
{numbered_phrases}"""
    else:
        prompt = f"""你是中文白板动画分镜导演。下面已经把文案固定拆成 {scene_count} 幕。
总口播时长约 {duration:.1f} 秒。风格：{style}。
严格按幕输出 title、key_text、concept、elements，不要输出或改写原文。
key_text 是给观众看的中文重点短语，必须准确概括本幕原文，只写 4～10 个汉字，不加标点，不得编造原文没有的观点。
elements 必须是恰好 3 个具体可画的中文短语，按叙事顺序排列；每项必须包含主体和动作或物体，禁止使用抽象词。
{character_rule}
{paper_rule}
每幕只讲一个清晰事件，禁止加入原文没有的童年、旅行、花鸟、山水、宠物等内容。
只返回 JSON 数组，不要解释。
固定分幕：
{fixed_segments}"""
    scenes: list[dict[str, Any]] = []
    last_plan_error: Exception | None = None
    for attempt in range(3):
        payload = provider_text(config, str(config["text_model"]), prompt, job_id=job_id)
        try:
            candidate = parse_json_block(extract_response_text(payload))
            if not isinstance(candidate, list) or not candidate:
                raise RuntimeError("分镜模型未返回有效场景")
            if not infographic and len(candidate) != scene_count:
                raise RuntimeError(f"分镜模型返回 {len(candidate)} 幕，预期 {scene_count} 幕")
            if not all(isinstance(scene, dict) for scene in candidate):
                raise RuntimeError("分镜模型返回的数据结构无效")
            if infographic:
                if len(candidate) > requested_count:
                    raise RuntimeError(f"信息图页面超过上限 {requested_count}")
                candidate = normalize_deck_pages(candidate, copy, phrase_timeline or {})
            scenes = candidate
            break
        except (json.JSONDecodeError, RuntimeError, TypeError, ValueError) as exc:
            last_plan_error = exc
            if attempt == 2:
                break
            if job_id and job_id in JOBS:
                update_job(job_id, stage=f"分镜结果异常，正在自动重试 {attempt + 2}/3", model_retry_count=int(JOBS[job_id].get("model_retry_count", 0)) + 1)
            time.sleep(provider_retry_delay(attempt))
    if not scenes:
        raise RuntimeError(f"分镜模型连续 3 次返回无效结果：{last_plan_error}")
    from scripts.add_key_text import clean_key_text
    series_title = ""
    for i, scene in enumerate(scenes):
        if infographic:
            scene["key_text"] = clean_key_text(str(scene.get("key_text") or scene.get("page_title") or "本页重点"), 16)
        else:
            scene["text"] = segments[i]
            key_text = clean_key_text(str(scene.get("key_text") or scene.get("title") or segments[i]), 10)
            scene["key_text"] = key_text or clean_key_text(segments[i], 10) or "本幕重点"
    if not infographic:
        fit_scene_durations(scenes, duration)
    for scene in scenes:
        raw_elements = scene.get("elements") or []
        labels = [str(x.get("label", "")) if isinstance(x, dict) else str(x) for x in raw_elements]
        labels = [x.strip() for x in labels if x.strip()][:4]
        if len(labels) < 2:
            labels = [scene.get("title", "口播主角"), scene.get("concept", "核心事件")]
        scene["elements"] = labels
    return scenes


def build_image_prompt(scene: dict[str, Any], style: str, aspect_ratio: str = "16:9", identity_mode: str = DEFAULT_IDENTITY_MODE) -> str:
    labels = scene.get("elements") or [scene.get("title", "场景主体")]
    count = len(labels)
    lanes = "；".join(f"第{i + 1}区：{label}" for i, label in enumerate(labels))
    character_instruction = identity_prompt(identity_mode)
    aspect_ratio = normalize_aspect_ratio(aspect_ratio)
    layout_direction = "从上到下" if aspect_ratio in {"9:16", "3:4"} else "从左到右"
    return f"""生成一张用于中文口播的 {aspect_ratio} 白板动画分镜原画。
风格名称：{style}。
{character_instruction}
视觉配方：{style_recipe(style)}
必须严格执行这套视觉配方，不得自动改回其他白板风格；人物、物体和配色都要让所选风格一眼可辨。
本幕标题：{scene.get('title', '')}
本幕叙事：{scene.get('concept', '')}
本幕原文：{scene.get('text', '')}
必须严格表现本幕叙事，不得生成童年成长、旅行、花鸟、山水、宠物等无关意象。
构图必须{layout_direction}平均分成 {count} 个互不重叠的独立小场景，每区主体居中，区间有明显留白：{lanes}。
必须把上述每个元素都画出来，顺序不得改变；任何人物或物体不得跨越相邻区域。
主体整体垂直居中并略微靠上，主要人物和物体中心位于画面高度 42%～48%，顶部不得出现大面积无意义空白。
禁止任何文字、字母、数字、Logo、水印、边框、对话框和装饰性填充。画面底部保留约 16% 空白作为字幕安全区。"""


def build_board_prompt(scenes: list[dict[str, Any]], style: str, reference_instruction: str = "", use_character_references: bool = False, infographic: bool = False, aspect_ratio: str = "16:9", presentation_mode: str = "whiteboard", identity_mode: str = DEFAULT_IDENTITY_MODE) -> str:
    aspect_ratio = normalize_aspect_ratio(aspect_ratio)
    layout_direction = "从上到下" if aspect_ratio in {"9:16", "3:4"} else "从左到右"
    if infographic:
        scene = scenes[0]
        elements = "、".join(scene.get("illustration_elements") or scene.get("nodes") or [])
        reference_block = f"视觉参考使用规则：{reference_instruction}\n" if reference_instruction else ""
        character_instruction = identity_prompt(identity_mode)
        return f"""生成一张 {aspect_ratio} 中文知识解说视频的独立插画素材。
所选画面风格：{style}。视觉配方：{style_recipe(style)}
人物身份策略：{character_instruction}
{reference_block}必须让画面在 3 秒内认出主体、10 秒内看懂观点证据；不是装饰性配图。
画面只画以下具象内容：{elements}。对应观点：{scene.get('concept', '')}。
PPT 已确定的视觉策略：{scene.get('visual_strategy', '左侧文字，右侧主题插图')}。
插图槽位类型：{scene.get('layout_type', 'focus')} / {scene.get('composition', 'split-right')}。主体比例应适应该槽位；横向通栏可画并列主体，中心舞台突出单一隐喻，分栏槽位保持竖向紧凑。
插画必须是独立、自然融入背景的视觉证据，不画圆角卡片、照片框、界面面板。
这张图只填入 Remotion PPT 已经确定的插图区域，不负责表达页面结构。禁止箭头、连接线、流程线、项目符号和图表关系。
画面四周保留充足留白，主体不要贴边。禁止任何文字、字母、数字、Logo、水印、边框、字幕和 UI；只有原文确实需要人物时才画人物。"""
    panels: list[str] = []
    for i, scene in enumerate(scenes, 1):
        elements = "、".join(scene.get("elements") or [])
        fields = [f"第{i}区｜事件：{scene.get('concept', '')}"]
        if scene.get("visual_structure"):
            fields.append(f"主结构：{scene['visual_structure']}")
        if scene.get("metaphor"):
            fields.append(f"核心隐喻：{scene['metaphor']}")
        fields.extend((f"必须包含：{elements}", f"对应原文：{scene.get('text', '')}"))
        panels.append("｜".join(fields))
    panel_text = "\n".join(panels)
    style_instruction = (
        f"视觉配方：{style_recipe(style)}"
        if style in {OIL_VISUAL_STYLE, CLEAR_STORYBOOK_STYLE} and reference_instruction else
        "严格复现输入风格参考图的配色、线条粗细、材质、造型比例与构图语言；不要复制风格图里原有的人物或事件。"
        if reference_instruction else
        f"视觉配方：{style_recipe(style)}\n必须严格执行这套视觉配方，不得自动改回其他白板风格；人物、物体和配色都要让所选风格一眼可辨。"
    )
    character_instruction = (
        "只使用人物参考组中定义的角色；人物出现时必须保持对应参考图的脸型、发型、年龄、服装和标志性特征一致。"
        if use_character_references else identity_prompt(identity_mode)
    )
    reference_block = f"参考图说明：\n{reference_instruction}\n" if reference_instruction else ""
    region_rule = (
        "完整场景，不分栏、不画边框。"
        if len(scenes) == 1 else
        f"画面必须{layout_direction}平均分成 {len(scenes)} 个互不重叠的叙事区域，不画边框；每区内部可以组合人物、动作和关键物体，但不得跨区。"
    )
    if normalize_presentation_mode(presentation_mode) == "story-color":
        layout_rule = "每个叙事区域上方保留约 25% 的纯净留白供程序后期排版手写字幕；插画主体集中在中下部。"
    else:
        layout_rule = "所有区域的主体垂直居中并略微靠上，主要人物和物体中心位于画面高度 42%～48%，顶部不得出现大面积无意义空白。画面底部保留约 16% 空白作为字幕安全区。"
    return f"""{reference_block}生成一张用于中文口播的 {aspect_ratio} 白板动画原画，一张图承载 {len(scenes)} 个连续分镜。
风格名称：{style}。
{character_instruction}
{style_instruction}
{region_rule}
{panel_text}
严格表现上述事件，不得生成原文没有的童年成长、旅行、花鸟、山水、宠物或装饰性意象。
{layout_rule}
禁止任何文字、字母、数字、Logo、水印、边框和对话框；字幕由程序后期准确添加，图片模型不得写字。"""


def normalize_generated_image_aspect(path: Path, aspect_ratio: str) -> None:
    from PIL import Image, ImageOps

    with Image.open(path) as source:
        normalized = ImageOps.fit(source.convert("RGB"), aspect_image_dimensions(aspect_ratio), method=Image.Resampling.LANCZOS, centering=(0.5, 0.46))
        normalized.save(path, format="PNG", optimize=True)


def generate_image(config: dict[str, Any], prompt: str, target: Path, reference_images: list[Path] | None = None, job_id: str | None = None, aspect_ratio: str = "16:9") -> None:
    # OpenLux documents a 1000-character limit for this GPT Image route.
    compact_prompt = prompt if len(prompt) <= 1000 else f"{prompt[:830]}\n{prompt[-160:]}"
    request_payload = {
        "model": config["image_model"],
        "prompt": compact_prompt,
        "n": 1,
        "size": aspect_api_size(aspect_ratio),
        "quality": "medium",
        "format": "png",
    }
    if reference_images:
        form_data = {key: str(value) for key, value in request_payload.items()}
        raw_files = [(path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/png") for path in reference_images]
        payload = provider_image_edit(config, form_data, raw_files, timeout=1800, job_id=job_id)
    else:
        try:
            payload = provider_image(config, "images/generations", request_payload, timeout=1800, job_id=job_id)
        except ProviderHTTPError as exc:
            if exc.status_code not in {404, 405}:
                raise
            # OpenLux currently also documents GPT Image 2 creation on this route.
            payload = provider_image(config, "images/edits", request_payload, timeout=1800, job_id=job_id)
    candidates = payload.get("data") or payload.get("choices") or []
    if not candidates:
        raise RuntimeError("GPT Image 2 没有返回图像数据")
    item = candidates[0]
    encoded = item.get("b64_json") or item.get("b64")
    url = item.get("url")
    if encoded:
        if isinstance(encoded, str) and encoded.startswith("data:image"):
            encoded = encoded.split(",", 1)[-1]
        target.write_bytes(base64.b64decode(encoded))
    elif url:
        with httpx.Client(timeout=120) as client:
            response = client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
    else:
        raise RuntimeError("GPT Image 2 返回格式中没有 b64_json 或 url")
    normalize_generated_image_aspect(target, aspect_ratio)


def custom_reference_context(job_id: str) -> tuple[list[Path], str, str]:
    with LOCK:
        job = JOBS.get(job_id, {}).copy()
    if job.get("reference_mode") != "custom":
        return [], "", ""
    job_dir = JOBS_DIR / job_id
    references = job.get("visual_references") or {}
    style_name = str(references.get("style_image") or "")
    style_path = job_dir / style_name
    if not style_name or not valid_image_file(style_path):
        raise RuntimeError("自定义风格参考图缺失或无效")
    paths = [style_path]
    lines = ["输入图1是唯一的画面风格参考，只学习其视觉风格，不复制图中人物。"]
    character_descriptions: list[str] = []
    image_index = 2
    for character in references.get("characters") or []:
        name = str(character.get("name") or "未命名人物")[:20]
        description = str(character.get("description") or "以参考图外观为准")[:80]
        character_paths = [job_dir / str(value) for value in character.get("images") or []]
        character_paths = [path for path in character_paths if valid_image_file(path)]
        if not character_paths:
            continue
        start = image_index
        paths.extend(character_paths)
        image_index += len(character_paths)
        end = image_index - 1
        range_label = f"输入图{start}" if start == end else f"输入图{start}至输入图{end}"
        lines.append(f"{range_label}共同定义人物“{name}”：{description}。同名人物在所有分镜保持一致。")
        character_descriptions.append(f"{name}（{description}）")
    if not character_descriptions:
        raise RuntimeError("没有可用的人物参考图")
    return paths, "\n".join(lines), "；".join(character_descriptions)


def _synthesize_voice_once(config: dict[str, Any], reference: Path, copy: str, target: Path) -> None:
    if config.get("tts_mode") == "fastapi":
        with httpx.Client(timeout=900) as client, reference.open("rb") as audio:
            response = client.post(
                f"{config['tts_url'].rstrip('/')}/api/tts",
                data={"text": copy, "emo_weight": "0.65"},
                files={"voice": (reference.name, audio, "audio/wav")},
            )
            if response.is_error:
                raise RuntimeError(f"语音克隆失败：{response.status_code} {response.text[:500]}")
            target.write_bytes(response.content)
        return

    # Long-form cloning can keep the GPU busy for several minutes.  The
    # default Gradio HTTP read timeout is too short and abandons a healthy job.
    client = Client(config["tts_url"], verbose=False, httpx_kwargs={"timeout": 1800.0})
    job = client.submit(
        "Same as the voice reference", handle_file(str(reference)), copy, "ZH", None, 0.65,
        0, 0, 0, 0, 0, 0, 0, 0, "", False, 120, 1.0,
        True, 0.8, 30, 0.8, 0.0, 3, 10.0, 1500,
        api_name="/gen_single",
    )
    result = job.result(timeout=1800)
    # Gradio 4/5 may return a filepath string, while newer IndexTTS builds
    # return FileData as {"path": ..., "url": ...}.
    item: Any = result
    # Unwrap tuples/lists and Gradio update objects such as
    # {"visible": true, "value": {"path": ...}, "__type__": "update"}.
    while True:
        if isinstance(item, (list, tuple)) and item:
            item = item[0]
            continue
        if isinstance(item, dict) and "value" in item and not item.get("path"):
            item = item["value"]
            continue
        break
    if isinstance(item, dict):
        path_value = item.get("path")
        if path_value and Path(path_value).exists():
            shutil.copy2(Path(path_value), target)
            return
        if item.get("url"):
            with httpx.Client(timeout=300) as http:
                response = http.get(item["url"])
                response.raise_for_status()
                target.write_bytes(response.content)
            return
        raise RuntimeError(f"语音服务返回了无法识别的文件对象：{list(item.keys())}")
    if isinstance(item, (str, os.PathLike)):
        shutil.copy2(Path(item), target)
        return
    raise RuntimeError(f"语音服务返回格式不受支持：{type(item).__name__}")


def synthesize_voice(config: dict[str, Any], reference: Path, copy: str, target: Path) -> None:
    """Retry transient LAN failures while keeping TTS concurrency at one."""
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            _synthesize_voice_once(config, reference, copy, target)
            return
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            retryable = any(token in message for token in ("10061", "connection refused", "connecterror", "timed out"))
            if not retryable or attempt == 3:
                break
            time.sleep(5 * (attempt + 1))
    raw = str(last_error or "未知错误")
    if "10061" in raw or "connection refused" in raw.lower():
        raise RuntimeError(
            f"无法连接语音克隆服务 {config.get('tts_url', '')}。请确认 IndexTTS 已启动并可从本机访问；系统已自动重试 4 次。"
        ) from last_error
    raise RuntimeError(f"语音克隆失败：{raw}") from last_error


def uploaded_narration_command(source: Path, target: Path) -> list[str]:
    """Normalize a user-provided complete narration for the render pipeline."""
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(target),
    ]


def script_paced_duration(copy: str) -> float:
    """Estimate a comfortable silent-video duration from visible script text."""
    return max(8.0, len(normalized_semantic_text(copy)) / 4.0)


def silent_narration_command(copy: str, target: Path) -> list[str]:
    """Create an internal silent timing track so the render pipeline stays uniform."""
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", f"{script_paced_duration(copy):.3f}", "-c:a", "pcm_s16le", str(target),
    ]


def narration_phrases(copy: str) -> list[str]:
    """Use the same punctuation boundaries as the real-narration aligner."""
    return [
        value.strip()
        for value in re.findall(r"《[^》]+》|[^，,。！？!?；;：:\n]+[，,。！？!?；;：:]?", copy)
        if normalized_semantic_text(value)
    ]


def script_paced_phrase_timeline(copy: str, duration_ms: int, fps: int = 30) -> dict[str, Any]:
    """Create an intentional script-paced timeline for videos without narration."""
    phrases = narration_phrases(copy) or [copy.strip()]
    weights = [max(1, len(normalized_semantic_text(text))) for text in phrases]
    total_weight = sum(weights)
    cursor_ms = 0
    source_cursor = 0
    items: list[dict[str, Any]] = []
    normalized_source = normalized_semantic_text(copy)
    cumulative_weight = 0
    for index, (text, weight) in enumerate(zip(phrases, weights), 1):
        cumulative_weight += weight
        end_ms = duration_ms if index == len(phrases) else round(duration_ms * cumulative_weight / total_weight)
        normalized = normalized_semantic_text(text)
        source_start = normalized_source.find(normalized, source_cursor)
        source_start = source_cursor if source_start < 0 else source_start
        source_end = source_start + len(normalized)
        items.append({
            "id": f"p{index:03d}", "order": index, "text": text, "normalized_text": normalized,
            "source_start": source_start, "source_end": source_end,
            "spoken_start_ms": cursor_ms, "spoken_end_ms": end_ms,
            "start_frame": math.ceil(cursor_ms * fps / 1000),
            "end_frame": max(1, math.ceil(end_ms * fps / 1000)),
            "alignment_coverage": 1.0, "alignment_confidence": 1.0,
            "boundary_source": "script-paced-no-narration", "boundary_similarity": 1.0,
            "neighbor_anchor_similarity": 1.0, "recognized_boundary_text": normalized,
        })
        cursor_ms = end_ms
        source_cursor = source_end
    return {
        "schema_version": 2, "timing_source": "script-paced-no-narration",
        "estimated_fallback_used": False, "fps": fps,
        "audio_duration_ms": duration_ms, "source_coverage": 1.0, "phrases": items,
    }


def write_annotation(scene: dict[str, Any], image: Path, target: Path, index: int) -> None:
    from PIL import Image

    with Image.open(image) as im:
        width, height = im.size
    labels = scene.get("elements") or [scene.get("title", "场景主体")]
    count = max(1, len(labels))
    duration = int(scene["duration_ms"])
    gap = 120
    usable = duration - 500 - gap * (count - 1)
    each = max(500, usable // count)
    portrait = height > width and count > 1
    margin_x = max(10, width // 80)
    margin_y = max(10, height // 100)
    band = ((height - margin_y * 2) if portrait else (width - margin_x * 2)) / count
    elements = []
    for i, label in enumerate(labels):
        x = margin_x if portrait else round(margin_x + i * band)
        x2 = width - margin_x if portrait else round(margin_x + (i + 1) * band)
        y = round(margin_y + i * band) if portrait else round(height * 0.02)
        y2 = round(margin_y + (i + 1) * band) if portrait else round(height * 0.82)
        start = 200 + i * (each + gap)
        elements.append({
            "id": f"part-{i+1}", "label": str(label), "sequence": i + 1,
            "narrativeRole": "按文案叙事顺序出现", "subtitle": scene.get("text", ""), "type": "concept",
            "region": {"x": x, "y": y, "width": x2 - x, "height": y2 - y},
            "reveal": {"direction": "top_to_bottom" if portrait else "left_to_right", "startMs": start, "durationMs": each, "maskPaddingPx": 16, "protectedRegions": []},
            "handPath": {"start": [width // 2, y + 5], "end": [width // 2, y2 - 5], "easing": "easeInOut"} if portrait else {"start": [x + 5, height // 2], "end": [x2 - 5, height // 2], "easing": "easeInOut"},
        })
    data = {
        "sceneId": f"scene-{index:02d}", "canvas": {"width": width, "height": height},
        "storyBasis": scene.get("concept", scene.get("title", "")), "sceneDurationMs": duration,
        "elements": elements,
    }
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_board_annotation(scenes: list[dict[str, Any]], image: Path, target: Path, index: int, presentation_mode: str = "whiteboard") -> None:
    from PIL import Image

    with Image.open(image) as im:
        width, height = im.size
    count = len(scenes)
    portrait = height > width and count > 1
    margin_x = max(10, width // 100)
    margin_y = max(10, height // 100)
    band = ((height - margin_y * 2) if portrait else (width - margin_x * 2)) / count
    offset = 0
    elements = []
    for i, scene in enumerate(scenes):
        x = margin_x if portrait else round(margin_x + i * band)
        x2 = width - margin_x if portrait else round(margin_x + (i + 1) * band)
        story_color = normalize_presentation_mode(presentation_mode) == "story-color"
        y = round(margin_y + i * band + (band * 0.24 if story_color else 0)) if portrait else round(height * (0.26 if story_color else 0.02))
        y2 = round(margin_y + (i + 1) * band) if portrait else round(height * 0.82)
        duration = int(scene["duration_ms"])
        elements.append({
            "id": f"panel-{i + 1}", "label": scene.get("title", f"分镜{i + 1}"),
            "sequence": i + 1, "narrativeRole": scene.get("concept", "按原文叙事"),
            "subtitle": scene.get("text", ""), "type": "scene",
            "captionRegion": {"x": x, "y": round(margin_y + i * band) if portrait else margin_y, "width": x2 - x, "height": round(band * 0.23) if portrait else round(height * 0.23)},
            "region": {"x": x, "y": y, "width": x2 - x, "height": y2 - y},
            "reveal": {"direction": "top_to_bottom" if portrait else "left_to_right", "startMs": offset, "durationMs": duration, "maskPaddingPx": 14, "protectedRegions": []},
            "handPath": {"start": [width // 2, y + 5], "end": [width // 2, y2 - 5], "easing": "easeInOut"} if portrait else {"start": [x + 5, height // 2], "end": [x2 - 5, height // 2], "easing": "easeInOut"},
        })
        offset += duration
    data = {
        "sceneId": f"board-{index:02d}", "canvas": {"width": width, "height": height},
        "storyBasis": " / ".join(str(s.get("title", "")) for s in scenes),
        "sceneDurationMs": offset, "elements": elements,
    }
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_branded_hand(text: str, target: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    if not text.strip():
        return HAND
    hand = Image.open(HAND).convert("RGBA")
    label = text.strip()[:12]
    font_paths = [
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    ]
    font_path = next((p for p in font_paths if p.exists()), None)
    font = ImageFont.truetype(str(font_path), 58) if font_path else ImageFont.load_default()
    strip = Image.new("RGBA", (430, 104), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)
    box = draw.textbbox((0, 0), label, font=font)
    text_width = box[2] - box[0]
    if text_width > 380 and font_path:
        font = ImageFont.truetype(str(font_path), max(24, round(58 * 380 / text_width)))
        box = draw.textbbox((0, 0), label, font=font)
        text_width = box[2] - box[0]
    draw.text(((430 - text_width) / 2, 20), label, font=font, fill=(105, 48, 30, 240), stroke_width=1, stroke_fill=(255, 255, 255, 200))
    rotated = strip.rotate(-40, resample=Image.Resampling.BICUBIC, expand=True)
    hand.alpha_composite(rotated, (430, 300))
    hand.save(target)
    return target


def whiteboard_render_command(image: Path, annotation: Path, output: Path, stroke_detail: str, presentation_mode: str = "whiteboard", aspect_ratio: str = "16:9") -> list[str]:
    """Build a hand-free whiteboard reveal command."""
    if normalize_presentation_mode(presentation_mode) == "story-color":
        width, height = aspect_video_dimensions(aspect_ratio)
        return [
            str(PYTHON), str(ROOT / "scripts" / "render_story_color.py"),
            str(image), str(annotation), str(output),
            "--width", str(width), "--height", str(height),
        ]
    command = [
        str(PYTHON), str(ROOT / "scripts" / "render_stream_whiteboard.py"),
        str(image), str(annotation), str(output),
        "--bare-tip", "--ink-path", "skeleton", "--stroke-detail", stroke_detail,
        "--color-fill", "contour-wipe",
    ]
    return command


def _subtitle_chunks(text: str, max_chars: int = 22) -> list[str]:
    sentences = [x.strip() for x in re.findall(r"[^。！？!?；;，,]+[。！？!?；;，,]?", text) if x.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        while len(sentence) > max_chars:
            chunks.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if sentence:
            chunks.append(sentence)
    return chunks or [text]


def _srt_time(ms: int) -> str:
    hours, rem = divmod(max(0, ms), 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def write_subtitles(scenes: list[dict[str, Any]], target: Path) -> None:
    aligned_cues = [
        cue
        for scene in scenes
        for cue in (scene.get("subtitle_cues") or [])
        if isinstance(cue, dict)
    ]
    if aligned_cues and all(scene.get("subtitle_cues") for scene in scenes):
        lines: list[str] = []
        for index, cue in enumerate(aligned_cues, 1):
            lines.extend([
                str(index),
                f"{_srt_time(int(cue['start_ms']))} --> {_srt_time(int(cue['end_ms']))}",
                str(cue["text"]),
                "",
            ])
        target.write_text("\n".join(lines), encoding="utf-8")
        return
    cues: list[tuple[int, int, str]] = []
    offset = 0
    for scene in scenes:
        chunks = _subtitle_chunks(str(scene.get("text", "")))
        weights = [max(1, len(re.sub(r"\s+", "", x))) for x in chunks]
        duration = int(scene["duration_ms"])
        used = 0
        for i, (chunk, weight) in enumerate(zip(chunks, weights)):
            cue_ms = duration - used if i == len(chunks) - 1 else round(duration * weight / sum(weights))
            cues.append((offset + used, offset + used + cue_ms, chunk))
            used += cue_ms
        offset += duration
    lines: list[str] = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.extend([str(i), f"{_srt_time(start)} --> {_srt_time(end)}", text, ""])
    target.write_text("\n".join(lines), encoding="utf-8")


def _ffmpeg_has_filter(filter_name: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(re.search(rf"(?m)^\s*\S+\s+{re.escape(filter_name)}(?:\s|$)", result.stdout + result.stderr))


def _parse_srt_time(value: str) -> int:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(f"无法解析字幕时间：{value}")
    hours, minutes, seconds, milliseconds = (int(part) for part in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def _read_srt_cues(source: Path) -> list[tuple[int, int, str]]:
    cues: list[tuple[int, int, str]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", source.read_text(encoding="utf-8-sig"))
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            continue
        start_text, end_text = (part.strip() for part in lines[time_index].split("-->", 1))
        text = "\n".join(line for line in lines[time_index + 1:] if line).strip()
        if text:
            cues.append((_parse_srt_time(start_text), _parse_srt_time(end_text), text))
    return cues


def _subtitle_font_path() -> Path | None:
    candidates = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    return next((path for path in candidates if path.exists()), None)


def _render_subtitles_with_pillow(video: Path, subtitles: Path, target: Path, job_id: str | None = None) -> None:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    cues = _read_srt_cues(subtitles)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"无法读取字幕视频：{video.name}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(
        str(target),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("无法创建字幕视频")
    font_path = _subtitle_font_path()
    font_size = max(24, round(height * 20 / 1080))
    font = ImageFont.truetype(str(font_path), font_size) if font_path else ImageFont.load_default()
    stroke_width = max(2, round(font_size / 10))
    cue_index = 0
    frame_index = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            timestamp_ms = round(frame_index * 1000 / fps)
            while cue_index < len(cues) and timestamp_ms >= cues[cue_index][1]:
                cue_index += 1
            if cue_index < len(cues) and cues[cue_index][0] <= timestamp_ms < cues[cue_index][1]:
                text = cues[cue_index][2]
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(image)
                box = draw.multiline_textbbox((0, 0), text, font=font, stroke_width=stroke_width, spacing=4)
                text_width = box[2] - box[0]
                text_height = box[3] - box[1]
                x = (width - text_width) / 2 - box[0]
                y = height - max(28, round(height * 28 / 1080)) - text_height - box[1]
                draw.multiline_text(
                    (x, y),
                    text,
                    font=font,
                    fill=(255, 255, 255),
                    stroke_width=stroke_width,
                    stroke_fill=(32, 32, 32),
                    spacing=4,
                    align="center",
                )
                frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            writer.write(frame)
            frame_index += 1
            if job_id and frame_index % 30 == 0:
                ensure_job_active(job_id)
    finally:
        capture.release()
        writer.release()


def _subtitle_video_input(video: Path, subtitles: Path, fallback_target: Path, job_id: str | None = None) -> tuple[Path, str | None]:
    if _ffmpeg_has_filter("subtitles"):
        style = (
            f"FontName={SUBTITLE_FONT},FontSize=20,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00202020,BorderStyle=1,Outline=2,Shadow=0,MarginV=28,Alignment=2"
        )
        return video, f"subtitles=filename='{subtitles.name}':force_style='{style}'"
    fallback_target.unlink(missing_ok=True)
    _render_subtitles_with_pillow(video, subtitles, fallback_target, job_id)
    return fallback_target, None


def remotion_infographic_props(scenes: list[dict[str, Any]], style: str, duration_ms: int, subtitles_enabled: bool = False, aspect_ratio: str = "16:9") -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes, 1):
        timed_cues = scene.get("timed_cues")
        if not isinstance(timed_cues, list) or not timed_cues:
            raise RuntimeError(f"第 {index} 页没有通过真实语音对齐，禁止进入 Remotion 渲染")
        layout_type = str(scene.get("layout_type") or "focus")
        pages.append({
            "id": f"page-{index}",
            "image": f"board-{index:02d}.png",
            "startFrame": int(scene["start_frame"]),
            "endFrame": int(scene["end_frame"]),
            "seriesTitle": str(scene.get("series_title") or "动态知识解说"),
            "chapterTitle": str(scene.get("chapter_title") or "本章要点"),
            "pageTitle": str(scene.get("page_title") or scene.get("key_text") or "核心观点"),
            "layoutType": layout_type,
            "composition": str(scene.get("composition") or _default_composition(layout_type, index)),
            "slideRole": str(scene.get("role") or "detail"),
            "relationshipType": str(scene.get("relationship_type") or "none"),
            "coreIdea": str(scene.get("core_idea") or scene.get("concept") or ""),
            "visualStrategy": str(scene.get("visual_strategy") or ""),
            "narrativeLink": str(scene.get("narrative_link") or ""),
            "nodes": [str(value) for value in scene.get("nodes") or []],
            "conclusion": str(scene.get("conclusion") or ""),
            "seriesPersistent": bool(scene.get("series_persistent")),
            "chapterPersistent": bool(scene.get("chapter_persistent")),
            "cues": [{
                "id": str(cue["id"]),
                "anchorText": str(cue["anchor_text"]),
                "startFrame": int(cue["start_frame"]),
                "endFrame": int(cue["end_frame"]),
                "spokenStartMs": int(cue["spoken_start_ms"]),
                "spokenEndMs": int(cue["spoken_end_ms"]),
                "enterIds": [str(value) for value in cue["enter_ids"]],
                "focusId": str(cue["focus_id"]),
                "alignmentCoverage": float(cue["alignment_coverage"]),
                "alignmentConfidence": float(cue["alignment_confidence"]),
            } for cue in timed_cues],
        })
    width, height = aspect_video_dimensions(aspect_ratio)
    return {
        "fps": 30,
        "width": width,
        "height": height,
        "totalDurationMs": duration_ms,
        "totalDurationFrames": max(1, math.ceil(duration_ms * 30 / 1000)),
        "style": style,
        "subtitlesEnabled": subtitles_enabled,
        "pages": pages,
    }


def fail_job(job_id: str, stage: str, exc: Exception) -> None:
    if isinstance(exc, JobCancelled) or is_job_cancelled(job_id):
        return
    finish_timing(job_id)
    update_job(job_id, status="error", stage=stage, error=str(exc))


def voice_stage(job_id: str, copy: str, style: str, reference: Path | None, scenes_per_image: int, pen_text: str, include_key_text: bool, include_subtitles: bool, stroke_detail: str, voice_mode: str, tts_url: str, node_index: int) -> None:
    job_dir = JOBS_DIR / job_id
    try:
        config = load_config()
        if voice_mode == "clone":
            config["tts_url"] = tts_url
            update_job(job_id, tts_node=tts_url, tts_node_index=node_index + 1)
        direct_narration = voice_mode == "uploaded"
        no_narration = voice_mode == "none"
        begin_phase(
            job_id,
            "voice",
            "视频计时" if no_narration else "旁白处理" if direct_narration else "语音克隆",
            "正在按文案建立无旁白时间轴" if no_narration else "正在使用上传的完整旁白" if direct_narration else f"语音节点 {node_index + 1} 正在克隆声音",
            8,
        )
        voice = job_dir / "voice.wav"
        if not valid_media_file(voice):
            partial_voice = job_dir / "voice.partial.wav"
            partial_voice.unlink(missing_ok=True)
            if no_narration:
                run(silent_narration_command(copy, partial_voice), job_id=job_id)
            elif direct_narration:
                if reference is None:
                    raise RuntimeError("直接使用旁白模式缺少完整旁白音频")
                run(uploaded_narration_command(reference, partial_voice), job_id=job_id)
            else:
                if reference is None:
                    raise RuntimeError("克隆音色模式缺少参考音频")
                synthesize_voice(config, reference, copy, partial_voice)
            ensure_job_active(job_id)
            if not valid_media_file(partial_voice):
                raise RuntimeError("语音服务返回的音频文件无效")
            partial_voice.replace(voice)
        duration = probe_duration(voice)
        update_job(job_id, duration=duration, checkpoint="voice_done")
        queue_for_stage(job_id, "model", "等待调用模型", 14)
        MODEL_QUEUE.put((job_id, copy, style, reference, scenes_per_image, pen_text, include_key_text, include_subtitles, stroke_detail))
        ensure_pipeline_workers()
    except Exception as exc:
        fail_job(job_id, "音频准备失败", exc)


def model_stage(job_id: str, copy: str, style: str, reference: Path | None, scenes_per_image: int, pen_text: str, include_key_text: bool, include_subtitles: bool, stroke_detail: str) -> None:
    job_dir = JOBS_DIR / job_id
    try:
        # Models are resolved when settings are saved. Do not delay every job
        # by re-reading remote catalogs before the first generation request.
        config = load_config()
        aspect_ratio = normalize_aspect_ratio(JOBS.get(job_id, {}).get("aspect_ratio"))
        voice = job_dir / "voice.wav"
        duration = probe_duration(voice)
        reference_images, reference_instruction, character_context = custom_reference_context(job_id)
        infographic = is_infographic_job(job_id)
        presentation_mode = normalize_presentation_mode(JOBS.get(job_id, {}).get("presentation_mode"))
        identity_mode = normalize_identity_mode(JOBS.get(job_id, {}).get("identity_mode"))

        phrase_timeline: dict[str, Any] | None = None
        if infographic:
            no_narration = JOBS.get(job_id, {}).get("voice_mode") == "none"
            begin_phase(job_id, "alignment", "短语时间表", "正在按文案节奏建立短语时间表" if no_narration else "正在制作完整的短语—真实旁白时间 JSON", 16)
            if no_narration:
                phrase_timeline = script_paced_phrase_timeline(copy, round(duration * 1000), fps=30)
            else:
                alignment_path = job_dir / "alignment.tokens.json"
                desired_alignment_model = os.environ.get("INFOGRAPHIC_WHISPER_MODEL", "medium")
                alignment_current = False
                if alignment_path.exists():
                    try:
                        saved_alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
                        alignment_current = (
                            str(saved_alignment.get("model") or "") == desired_alignment_model
                            and saved_alignment.get("segmentation") == ALIGNMENT_SEGMENTATION
                            and bool(saved_alignment.get("speechSegments"))
                        )
                    except (OSError, json.JSONDecodeError):
                        alignment_current = False
                if not alignment_current:
                    run([
                        str(NODE),
                        str(REMOTION_RENDERER / "align.mjs"),
                        str(voice),
                        str(alignment_path),
                    ], cwd=REMOTION_RENDERER, job_id=job_id)
                try:
                    alignment_payload = json.loads(alignment_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise RuntimeError("真实旁白 token 时间戳文件损坏，请删除后重试") from exc
                from scripts.semantic_timeline import build_phrase_timeline
                phrase_timeline = build_phrase_timeline(copy, alignment_payload, round(duration * 1000), fps=30)
            atomic_write_json(job_dir / "phrase-timeline.json", phrase_timeline)
            update_job(job_id, checkpoint="phrase_timeline_done")

        plan_path = job_dir / "plan.json"
        scenes: list[dict[str, Any]] = []
        if plan_path.exists():
            try:
                saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
                valid_modes = {"narrated_deck_v4", "narrated_deck_v4_timed"}
                valid_mode = not infographic or all(scene.get("_plan_mode") in valid_modes for scene in saved_plan if isinstance(scene, dict))
                if isinstance(saved_plan, list) and saved_plan and all(isinstance(scene, dict) for scene in saved_plan) and valid_mode:
                    scenes = saved_plan
            except (OSError, json.JSONDecodeError):
                scenes = []
        if not scenes:
            begin_phase(job_id, "planning", "内容结构", "正在浓缩中心句、列出关键词并规划 PPT 页面", 25)
            scenes = make_plan(config, copy, duration, style, character_context, job_id, infographic, phrase_timeline, identity_mode)
            ensure_job_active(job_id)
            atomic_write_json(plan_path, scenes)
        else:
            begin_phase(job_id, "planning", "内容结构", "已恢复 PPT 内容结构", 27)
        if infographic:
            begin_phase(job_id, "deck", "Remotion PPT", "正在把页面结构和关键词绑定到短语时间", 31)
            from scripts.semantic_timeline import build_deck_timeline
            scenes, alignment_report = build_deck_timeline(
                copy,
                scenes,
                phrase_timeline or {},
                round(duration * 1000),
                fps=30,
            )
            atomic_write_json(plan_path, scenes)
            atomic_write_json(job_dir / "alignment-report.json", alignment_report)
            deck_spec = remotion_infographic_props(scenes, style, round(duration * 1000), include_subtitles, aspect_ratio)
            atomic_write_json(job_dir / "deck-spec.json", deck_spec)
            atomic_write_json(job_dir / "content-timeline.json", {
                "schema_version": 1,
                "slides": [{
                    "page": index,
                    "source_phrase_ids": scene.get("source_phrase_ids"),
                    "core_idea": scene.get("core_idea"),
                    "page_title": scene.get("page_title"),
                    "key_items": scene.get("key_items"),
                    "layout_type": scene.get("layout_type"),
                    "composition": scene.get("composition"),
                    "visual_strategy": scene.get("visual_strategy"),
                    "narrative_link": scene.get("narrative_link"),
                    "relationship_type": scene.get("relationship_type"),
                    "timed_cues": scene.get("timed_cues"),
                } for index, scene in enumerate(scenes, 1)],
            })
            scenes_per_image = 1
        elif fit_scene_durations(scenes, duration):
            atomic_write_json(plan_path, scenes)
        boards = [scenes[i:i + scenes_per_image] for i in range(0, len(scenes), scenes_per_image)]
        board_specs: list[tuple[list[Path], str, str]] = []
        for board in boards:
            board_images = reference_images
            board_instruction = reference_instruction
            use_character_references = bool(character_context)
            if style == PAPER_METAPHOR_STYLE and not board_images:
                board_images, board_instruction = paper_metaphor_reference_context(board)
                use_character_references = False
            elif style == OIL_VISUAL_STYLE and not board_images:
                board_images, board_instruction = oil_visual_reference_context(board, infographic)
                use_character_references = False
            elif style == CLEAR_STORYBOOK_STYLE and not board_images:
                board_images, board_instruction = clear_storybook_reference_context()
                use_character_references = False
            board_prompt = build_board_prompt(board, style, board_instruction, use_character_references, infographic, aspect_ratio, presentation_mode, identity_mode)
            board_specs.append((board_images, board_instruction, board_prompt))
        update_job(job_id, duration=duration, scenes=len(scenes), boards=len(boards), checkpoint="plan_done")
        atomic_write_json(job_dir / "boards.json", [
            {"scene_numbers": list(range(i * scenes_per_image + 1, i * scenes_per_image + len(board) + 1)), "image_prompt": board_specs[i][2]}
            for i, board in enumerate(boards)
        ])
        from scripts.add_key_text import add_key_text
        completed_images = 0
        completed_images_lock = threading.Lock()

        def generate_board_image(i: int, board: list[dict[str, Any]]) -> int:
            nonlocal completed_images
            board_images, _board_instruction, board_prompt = board_specs[i - 1]
            ensure_job_active(job_id)
            stem = f"board-{i:02d}"
            image = job_dir / f"{stem}.png"
            source_image = job_dir / f"{stem}.source.png"
            if not valid_image_file(source_image):
                partial_image = job_dir / f"{stem}.source.partial.png"
                last_image_error: Exception | None = None
                for attempt in range(3):
                    partial_image.unlink(missing_ok=True)
                    try:
                        generate_image(config, board_prompt, partial_image, board_images, job_id, aspect_ratio)
                        ensure_job_active(job_id)
                        if valid_image_file(partial_image):
                            break
                        raise RuntimeError("模型返回的图片文件无效")
                    except JobCancelled:
                        raise
                    except ProviderHTTPError:
                        raise
                    except (RuntimeError, ValueError, OSError) as exc:
                        last_image_error = exc
                        if attempt == 2:
                            break
                        update_job(job_id, stage=f"第 {i} 张图片结果异常，正在自动重试 {attempt + 2}/3", model_retry_count=int(JOBS[job_id].get("model_retry_count", 0)) + 1)
                        time.sleep(provider_retry_delay(attempt))
                if not valid_image_file(partial_image):
                    raise RuntimeError(f"第 {i} 张分镜图连续 3 次生成无效：{last_image_error}")
                partial_image.replace(source_image)
            if include_key_text and not infographic and presentation_mode != "story-color":
                add_key_text(source_image, [str(scene.get("key_text", "")) for scene in board], image)
            else:
                shutil.copy2(source_image, image)
            with completed_images_lock:
                completed_images += 1
                done = completed_images
            update_job(
                job_id,
                stage=f"并行生成插图：已完成 {done}/{len(boards)} 张",
                progress=36 + int(done / len(boards) * 40),
                checkpoint="images",
                completed_boards=done,
            )
            return i

        begin_phase(
            job_id,
            "images",
            "PPT 插图",
            f"正在按图片节点 {IMAGE_GENERATION_RPM} RPM 提交 {len(boards)} 张插图（响应互不阻塞）",
            36,
        )
        # Every board gets a waiting worker so a slow response cannot consume
        # the request-start budget. AdaptiveImageNodePool only paces starts.
        with ThreadPoolExecutor(max_workers=len(boards)) as executor:
            futures = [executor.submit(generate_board_image, i, board) for i, board in enumerate(boards, 1)]
            for future in as_completed(futures):
                future.result()
        queue_for_stage(job_id, "render", "准备本地渲染", 78)
        start_render_task(render_generated_job, job_id, scenes, boards, pen_text, include_subtitles, stroke_detail, duration)
    except Exception as exc:
        current_phase = str(JOBS.get(job_id, {}).get("current_phase") or "")
        stage = {
            "alignment": "短语时间表失败",
            "planning": "内容结构失败",
            "deck": "Remotion PPT 结构失败",
            "images": "PPT 插图生成失败",
        }.get(current_phase, "模型调用失败")
        fail_job(job_id, stage, exc)


def render_generated_job(job_id: str, scenes: list[dict[str, Any]], boards: list[list[dict[str, Any]]], pen_text: str, include_subtitles: bool, stroke_detail: str, duration: float) -> None:
    job_dir = JOBS_DIR / job_id
    try:
        infographic = is_infographic_job(job_id)
        presentation_mode = normalize_presentation_mode(JOBS.get(job_id, {}).get("presentation_mode"))
        duration_ms = round(duration * 1000)
        if infographic:
            begin_phase(job_id, "drawing", "Remotion 渲染", "正在按真实旁白时间编排动态信息图", 80)
            silent = job_dir / "silent-remotion-v1.mp4"
            final = job_dir / "final-remotion-v1.mp4"
            if not valid_timed_video(silent, duration_ms):
                partial_silent = job_dir / "silent-remotion-v1.partial.mp4"
                partial_silent.unlink(missing_ok=True)
                props_path = job_dir / "remotion-props.json"
                atomic_write_json(
                    props_path,
                    remotion_infographic_props(
                        scenes,
                        str(JOBS.get(job_id, {}).get("style") or DEFAULT_STYLE),
                        duration_ms,
                        include_subtitles,
                        normalize_aspect_ratio(JOBS.get(job_id, {}).get("aspect_ratio")),
                    ),
                )
                run([
                    str(NODE),
                    str(REMOTION_RENDERER / "render.mjs"),
                    str(props_path),
                    str(partial_silent),
                    str(job_dir),
                ], cwd=REMOTION_RENDERER, job_id=job_id)
                if not valid_timed_video(partial_silent, duration_ms):
                    raise RuntimeError("Remotion 信息图视频时长与真实旁白不一致")
                partial_silent.replace(silent)
            update_job(job_id, checkpoint="render", completed_videos=len(scenes), render_engine="remotion-semantic-v1")
        else:
            completed_videos = 0
            completed_videos_lock = threading.Lock()

            def render_board_video(i: int, board: list[dict[str, Any]]) -> tuple[int, Path]:
                nonlocal completed_videos
                ensure_job_active(job_id)
                stem = f"board-{i:02d}"
                image = job_dir / f"{stem}.png"
                annotation = job_dir / f"{stem}.annotation.json"
                video = job_dir / f"{stem}.mp4"
                expected_ms = sum(int(scene["duration_ms"]) for scene in board)
                if not valid_timed_video(video, expected_ms):
                    video.unlink(missing_ok=True)
                    partial_video = job_dir / f"{stem}.partial.mp4"
                    partial_video.unlink(missing_ok=True)
                    write_board_annotation(board, image, annotation, i, presentation_mode)
                    run(whiteboard_render_command(image, annotation, partial_video, stroke_detail, presentation_mode, JOBS.get(job_id, {}).get("aspect_ratio", "16:9")), job_id=job_id)
                    if not valid_media_file(partial_video):
                        raise RuntimeError(f"第 {i} 段手绘视频无效")
                    partial_video.replace(video)
                with completed_videos_lock:
                    completed_videos += 1
                    done = completed_videos
                update_job(
                    job_id,
                    stage=f"并行渲染分镜：已完成 {done}/{len(boards)} 段",
                    progress=78 + int(done / len(boards) * 12),
                    checkpoint="render",
                    completed_videos=done,
                )
                return i, video

            begin_phase(job_id, "drawing", "手绘渲染", f"正在以 {min(WHITEBOARD_RENDER_CONCURRENCY, len(boards))} 路并行渲染 {len(boards)} 段分镜", 78)
            rendered: list[tuple[int, Path]] = []
            with ThreadPoolExecutor(max_workers=min(WHITEBOARD_RENDER_CONCURRENCY, len(boards))) as executor:
                futures = [executor.submit(render_board_video, i, board) for i, board in enumerate(boards, 1)]
                for future in as_completed(futures):
                    rendered.append(future.result())
            videos = [video for _index, video in sorted(rendered)]

            silent = job_dir / "silent.mp4"
            final = job_dir / "final.mp4"
            if not valid_media_file(silent):
                partial_silent = job_dir / "silent.partial.mp4"
                partial_silent.unlink(missing_ok=True)
                run([str(PYTHON), str(ROOT / "scripts" / "merge_scenes.py"), "--inputs", *map(str, videos), "--output", str(partial_silent)], job_id=job_id)
                if not valid_media_file(partial_silent):
                    raise RuntimeError("合并后的无声视频无效")
                partial_silent.replace(silent)

        begin_phase(job_id, "compositing", "音画合成", "正在合成声音和画面", 92)
        if not valid_media_file(final):
            partial_final = job_dir / f"{final.stem}.partial.mp4"
            partial_final.unlink(missing_ok=True)
            video_input = silent
            subtitle_filter = None
            if include_subtitles and presentation_mode != "story-color":
                subtitles = job_dir / "subtitles.srt"
                write_subtitles(scenes, subtitles)
                video_input, subtitle_filter = _subtitle_video_input(
                    silent,
                    subtitles,
                    job_dir / f"{final.stem}.subtitles.mp4",
                    job_id,
                )
            ffmpeg_command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_input.name, "-i", "voice.wav", "-map", "0:v:0", "-map", "1:a:0"]
            if subtitle_filter:
                ffmpeg_command.extend(["-vf", subtitle_filter])
            ffmpeg_command.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", partial_final.name])
            run(ffmpeg_command, cwd=job_dir, job_id=job_id)
            if not valid_media_file(partial_final):
                raise RuntimeError("最终音画文件无效")
            partial_final.replace(final)
        finish_timing(job_id)
        update_job(job_id, status="done", stage="制作完成", progress=100, result_url=f"/api/jobs/{job_id}/download", result_file=final.name, duration=duration, scenes=len(scenes), boards=len(boards), can_rerender=True)
    except Exception as exc:
        fail_job(job_id, "本地渲染失败", exc)


def rerender_job(job_id: str, scenes_per_image: int, pen_text: str, include_key_text: bool, include_subtitles: bool, stroke_detail: str) -> None:
    job_dir = JOBS_DIR / job_id
    try:
        presentation_mode = normalize_presentation_mode(JOBS.get(job_id, {}).get("presentation_mode"))
        scenes = json.loads((job_dir / "plan.json").read_text(encoding="utf-8"))
        voice = job_dir / "voice.wav"
        duration = probe_duration(voice)
        if fit_scene_durations(scenes, duration):
            atomic_write_json(job_dir / "plan.json", scenes)
        boards = [scenes[i:i + scenes_per_image] for i in range(0, len(scenes), scenes_per_image)]
        from scripts.add_key_text import add_key_text
        videos: list[Path] = []
        for i, board in enumerate(boards, 1):
            progress = 15 + int(i / len(boards) * 68)
            begin_phase(job_id, "drawing", "重新手绘", f"正在重新绘制第 {i}/{len(boards)} 张分镜图", progress)
            stem = f"board-{i:02d}"
            image = job_dir / f"{stem}.png"
            source_image = job_dir / f"{stem}.source.png"
            annotation = job_dir / f"{stem}.annotation.json"
            video = job_dir / f"{stem}.mp4"
            if source_image.exists():
                if include_key_text and presentation_mode != "story-color":
                    add_key_text(source_image, [str(scene.get("key_text", "")) for scene in board], image)
                else:
                    shutil.copy2(source_image, image)
            if not image.exists():
                raise RuntimeError(f"缺少可复用的分镜图：{image.name}")
            write_board_annotation(board, image, annotation, i, presentation_mode)
            expected_ms = sum(int(scene["duration_ms"]) for scene in board)
            if not valid_timed_video(video, expected_ms):
                video.unlink(missing_ok=True)
                partial_video = job_dir / f"{stem}.partial.mp4"
                partial_video.unlink(missing_ok=True)
                run(whiteboard_render_command(image, annotation, partial_video, stroke_detail, presentation_mode, JOBS.get(job_id, {}).get("aspect_ratio", "16:9")), job_id=job_id)
                if not valid_media_file(partial_video):
                    raise RuntimeError(f"第 {i} 段重新渲染视频无效")
                partial_video.replace(video)
            videos.append(video)
            update_job(job_id, checkpoint="rerender", completed_videos=i)

        begin_phase(job_id, "compositing", "音画合成", "正在重新合成声音和画面", 90)
        silent = job_dir / "silent.mp4"
        if not valid_media_file(silent):
            partial_silent = job_dir / "silent.partial.mp4"
            partial_silent.unlink(missing_ok=True)
            run([str(PYTHON), str(ROOT / "scripts" / "merge_scenes.py"), "--inputs", *map(str, videos), "--output", str(partial_silent)], job_id=job_id)
            if not valid_media_file(partial_silent):
                raise RuntimeError("重新合并后的无声视频无效")
            partial_silent.replace(silent)
        final = job_dir / "final.mp4"
        if not valid_media_file(final):
            partial_final = job_dir / "final.partial.mp4"
            partial_final.unlink(missing_ok=True)
            video_input = job_dir / "silent.mp4"
            subtitle_filter = None
            if include_subtitles and presentation_mode != "story-color":
                subtitles = job_dir / "subtitles.srt"
                write_subtitles(scenes, subtitles)
                video_input, subtitle_filter = _subtitle_video_input(
                    video_input,
                    subtitles,
                    job_dir / "final.subtitles.mp4",
                    job_id,
                )
            ffmpeg_command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_input.name, "-i", "voice.wav", "-map", "0:v:0", "-map", "1:a:0"]
            if subtitle_filter:
                ffmpeg_command.extend(["-vf", subtitle_filter])
            ffmpeg_command.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", partial_final.name])
            run(ffmpeg_command, cwd=job_dir, job_id=job_id)
            if not valid_media_file(partial_final):
                raise RuntimeError("重新渲染的最终音画文件无效")
            partial_final.replace(final)
        finish_timing(job_id)
        update_job(job_id, status="done", stage="重新渲染完成", progress=100, result_url=f"/api/jobs/{job_id}/download", duration=duration, scenes=len(scenes), boards=len(boards), can_rerender=True)
    except Exception as exc:
        fail_job(job_id, "重新渲染失败", exc)


def voice_queue_worker(node_index: int) -> None:
    while True:
        nodes = configured_tts_nodes()
        task = VOICE_QUEUE.get()
        voice_mode = ""
        try:
            job_id = str(task[0])
            with LOCK:
                should_run = JOBS.get(job_id, {}).get("status") in {"queued", "running"}
            if not should_run:
                continue
            voice_mode = str(task[-1])
            nodes = configured_tts_nodes()
            if voice_mode == "clone" and node_index >= len(nodes):
                VOICE_QUEUE.put(task)
                time.sleep(1)
                continue
            if voice_mode == "clone":
                with VOICE_NODE_LOCK:
                    VOICE_NODE_JOBS[node_index] = str(task[0])
            voice_stage(*task, nodes[node_index] if voice_mode == "clone" else "", node_index if voice_mode == "clone" else -1)
        except Exception as exc:
            job_id = str(task[0])
            if job_id in JOBS:
                fail_job(job_id, "语音队列异常", exc)
        finally:
            if voice_mode == "clone":
                with VOICE_NODE_LOCK:
                    VOICE_NODE_JOBS[node_index] = None
            VOICE_QUEUE.task_done()


def regenerate_board_image(job_id: str, page: int, prompt: str) -> None:
    """Regenerate one existing board while keeping the previous revision recoverable."""
    job_dir = JOBS_DIR / job_id
    try:
        with LOCK:
            selected = JOBS[job_id].copy()
            source_id = job_id
            source = selected
            visited = {job_id}
            while source.get("job_type") == "rerender" and source.get("rerender_of"):
                candidate = str(source["rerender_of"])
                if candidate in visited or candidate not in JOBS:
                    break
                visited.add(candidate)
                source_id = candidate
                source = JOBS[candidate].copy()
        plan_path = job_dir / "plan.json"
        boards_path = job_dir / "boards.json"
        scenes = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(scenes, list) or not scenes:
            raise RuntimeError("任务的页面结构文件无效")
        scenes_per_image = 1 if is_infographic_job(job_id) else max(1, min(4, int(selected.get("scenes_per_image", source.get("scenes_per_image", 1)))))
        boards = [scenes[index:index + scenes_per_image] for index in range(0, len(scenes), scenes_per_image)]
        if page < 1 or page > len(boards):
            raise RuntimeError(f"第 {page} 张图片不存在")

        begin_phase(job_id, "images", "单图重生成", f"正在按修改后的提示词重新生成第 {page} 张图片", 50)
        config = load_config()
        board = boards[page - 1]
        reference_images, _reference_instruction, _character_context = custom_reference_context(source_id)
        style = str(source.get("style") or DEFAULT_STYLE)
        if style == PAPER_METAPHOR_STYLE and not reference_images:
            reference_images, _reference_instruction = paper_metaphor_reference_context(board)
        elif style == OIL_VISUAL_STYLE and not reference_images:
            reference_images, _reference_instruction = oil_visual_reference_context(board, is_infographic_job(job_id))
        elif style == CLEAR_STORYBOOK_STYLE and not reference_images:
            reference_images, _reference_instruction = clear_storybook_reference_context()

        stem = f"board-{page:02d}"
        image = job_dir / f"{stem}.png"
        source_image = job_dir / f"{stem}.source.png"
        partial_image = job_dir / f"{stem}.source.partial.png"
        last_error: Exception | None = None
        for attempt in range(3):
            partial_image.unlink(missing_ok=True)
            try:
                generate_image(config, prompt, partial_image, reference_images, job_id, normalize_aspect_ratio(source.get("aspect_ratio")))
                ensure_job_active(job_id)
                if valid_image_file(partial_image):
                    break
                raise RuntimeError("模型返回的图片文件无效")
            except JobCancelled:
                raise
            except ProviderHTTPError:
                raise
            except (RuntimeError, ValueError, OSError) as exc:
                last_error = exc
                if attempt == 2:
                    break
                update_job(job_id, stage=f"第 {page} 张图片结果异常，正在自动重试 {attempt + 2}/3")
                time.sleep(provider_retry_delay(attempt))
        if not valid_image_file(partial_image):
            raise RuntimeError(f"第 {page} 张图片连续 3 次生成无效：{last_error}")

        revision_dir = job_dir / "revisions" / time.strftime("%Y%m%d-%H%M%S")
        revision_dir.mkdir(parents=True, exist_ok=True)
        for previous in (source_image, image, boards_path):
            if previous.exists():
                shutil.copy2(previous, revision_dir / previous.name)
        partial_image.replace(source_image)
        include_key_text = bool(selected.get("include_key_text", source.get("include_key_text", True)))
        if include_key_text and not is_infographic_job(job_id):
            from scripts.add_key_text import add_key_text
            add_key_text(source_image, [str(scene.get("key_text", "")) for scene in board], image)
        else:
            shutil.copy2(source_image, image)

        try:
            manifest = json.loads(boards_path.read_text(encoding="utf-8")) if boards_path.exists() else []
        except (OSError, json.JSONDecodeError):
            manifest = []
        if not isinstance(manifest, list):
            manifest = []
        while len(manifest) < len(boards):
            index = len(manifest)
            manifest.append({
                "scene_numbers": list(range(index * scenes_per_image + 1, index * scenes_per_image + len(boards[index]) + 1)),
                "image_prompt": "",
            })
        manifest[page - 1]["image_prompt"] = prompt
        atomic_write_json(boards_path, manifest)
        finish_timing(job_id)
        update_job(
            job_id,
            status="done",
            stage=f"第 {page} 张图片已重新生成，可重新渲染成片",
            progress=100,
            completed_boards=len([path for path in job_dir.glob("board-*.png") if re.fullmatch(r"board-\d+\.png", path.name)]),
            board_regeneration=None,
            error=None,
            can_rerender=True,
            needs_rerender=True,
        )
    except Exception as exc:
        fail_job(job_id, "单图重新生成失败", exc)


def model_queue_worker() -> None:
    while True:
        task = MODEL_QUEUE.get()
        try:
            command = str(task[0])
            job_id = str(task[1]) if command == "regenerate_board" else command
            with LOCK:
                should_run = JOBS.get(job_id, {}).get("status") in {"queued", "running"}
            if not should_run:
                continue
            if command == "regenerate_board":
                regenerate_board_image(job_id, int(task[2]), str(task[3]))
            else:
                model_stage(*task)
        except Exception as exc:
            command = str(task[0])
            job_id = str(task[1]) if command == "regenerate_board" else command
            if job_id in JOBS:
                fail_job(job_id, "模型队列异常", exc)
        finally:
            MODEL_QUEUE.task_done()


def start_render_task(target: Any, *args: Any) -> None:
    job_id = str(args[0])

    def runner() -> None:
        global RENDER_ACTIVE
        acquired = False
        try:
            while not acquired:
                with LOCK:
                    should_run = JOBS.get(job_id, {}).get("status") in {"queued", "running"}
                if not should_run:
                    return
                acquired = RENDER_JOB_SEMAPHORE.acquire(timeout=0.5)
            with LOCK:
                should_run = JOBS.get(job_id, {}).get("status") in {"queued", "running"}
            if not should_run:
                return
            with RENDER_ACTIVE_LOCK:
                RENDER_ACTIVE += 1
            target(*args)
        finally:
            if acquired:
                with RENDER_ACTIVE_LOCK:
                    RENDER_ACTIVE = max(0, RENDER_ACTIVE - 1)
                RENDER_JOB_SEMAPHORE.release()
            with RENDER_THREADS_LOCK:
                RENDER_THREADS.discard(threading.current_thread())

    thread = threading.Thread(target=runner, name=f"local-render-{job_id}", daemon=True)
    with RENDER_THREADS_LOCK:
        RENDER_THREADS.add(thread)
    thread.start()


def ensure_pipeline_workers() -> None:
    with WORKER_LOCK:
        for index in range(max(1, len(configured_tts_nodes()))):
            thread = VOICE_WORKER_THREADS.get(index)
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=voice_queue_worker, args=(index,), name=f"voice-worker-{index + 1}", daemon=True)
                VOICE_WORKER_THREADS[index] = thread
                thread.start()
        MODEL_WORKER_THREADS[:] = [thread for thread in MODEL_WORKER_THREADS if thread.is_alive()]
        while len(MODEL_WORKER_THREADS) < MODEL_CONCURRENCY:
            index = len(MODEL_WORKER_THREADS) + 1
            thread = threading.Thread(target=model_queue_worker, name=f"model-worker-{index}", daemon=True)
            MODEL_WORKER_THREADS.append(thread)
            thread.start()


def enqueue_job_from_checkpoint(job_id: str, item: dict[str, Any]) -> None:
    job_dir = JOBS_DIR / job_id
    pending_regeneration = item.get("board_regeneration")
    if isinstance(pending_regeneration, dict):
        page = int(pending_regeneration.get("page", 0))
        prompt = str(pending_regeneration.get("prompt") or "").strip()
        if page < 1 or not prompt:
            raise RuntimeError("待恢复的单图重生成参数无效")
        queue_for_stage(job_id, "model", f"正在恢复第 {page} 张图片重生成", max(1, int(item.get("progress", 1))))
        MODEL_QUEUE.put(("regenerate_board", job_id, page, prompt))
        return
    result_name = str(item.get("result_file") or "final.mp4")
    if result_name not in {"final.mp4", "final-remotion-v1.mp4"}:
        result_name = "final.mp4"
    if valid_media_file(job_dir / result_name):
        finish_timing(job_id)
        update_job(
            job_id,
            status="done",
            stage="已从断点恢复完成",
            progress=100,
            result_url=f"/api/jobs/{job_id}/download",
            result_file=result_name,
            can_rerender=True,
        )
        return
    scenes_per_image = max(1, min(4, int(item.get("scenes_per_image", 1))))
    pen_text = str(item.get("pen_text", "")).strip()[:12]
    include_key_text = bool(item.get("include_key_text", True))
    include_subtitles = bool(item.get("include_subtitles", True))
    stroke_detail = str(item.get("stroke_detail", "detailed"))
    stroke_detail = stroke_detail if stroke_detail in {"light", "standard", "detailed", "full"} else "detailed"
    if item.get("job_type") == "rerender":
        queue_for_stage(job_id, "render", "正在恢复本地渲染", max(1, int(item.get("progress", 1))))
        if is_infographic_job(job_id):
            scenes = json.loads((job_dir / "plan.json").read_text(encoding="utf-8"))
            duration = probe_duration(job_dir / "voice.wav")
            boards = [[scene] for scene in scenes]
            start_render_task(render_generated_job, job_id, scenes, boards, pen_text, include_subtitles, stroke_detail, duration)
        else:
            start_render_task(rerender_job, job_id, scenes_per_image, pen_text, include_key_text, include_subtitles, stroke_detail)
        return
    copy = str(item.get("copy", "")).strip()
    if not copy:
        raise RuntimeError("旧任务缺少可恢复的文案，请从历史记录重新提交")
    reference = next(iter(sorted(job_dir.glob("reference.*"))), None)
    voice_mode = str(item.get("voice_mode") or "clone")
    voice_mode = voice_mode if voice_mode in {"none", "uploaded", "clone"} else "clone"
    task = (job_id, copy, str(item.get("style", DEFAULT_STYLE)), reference, scenes_per_image, pen_text, include_key_text, include_subtitles, stroke_detail)
    if valid_media_file(job_dir / "voice.wav"):
        queue_for_stage(job_id, "model", "已恢复配音，等待继续模型任务", max(14, int(item.get("progress", 14))))
        MODEL_QUEUE.put(task)
    else:
        if voice_mode != "none" and (reference is None or not reference.exists()):
            raise RuntimeError("任务缺少参考音频，无法从断点继续")
        queue_for_stage(job_id, "voice", "等待恢复无旁白时间轴" if voice_mode == "none" else "等待恢复上传旁白" if voice_mode == "uploaded" else "等待恢复语音克隆", max(1, int(item.get("progress", 1))))
        VOICE_QUEUE.put((*task, voice_mode))


def resume_pending_jobs() -> None:
    with LOCK:
        pending = sorted(
            [(job_id, item.copy()) for job_id, item in JOBS.items() if item.get("status") in {"queued", "running"}],
            key=lambda entry: (int(entry[1].get("queue_order", 0)), float(entry[1].get("created_at", 0))),
        )
    for job_id, item in pending:
        try:
            enqueue_job_from_checkpoint(job_id, item)
        except Exception as exc:
            fail_job(job_id, "任务恢复失败", exc)
    ensure_pipeline_workers()


restore_jobs()
resume_pending_jobs()


@app.get("/api/health")
def health() -> dict[str, Any]:
    with RENDER_THREADS_LOCK:
        render_waiting = sum(1 for thread in RENDER_THREADS if thread.is_alive())
    with RENDER_ACTIVE_LOCK:
        render_active = RENDER_ACTIVE
    nodes = configured_tts_nodes()
    with VOICE_NODE_LOCK:
        voice_nodes = [
            {"index": index + 1, "url": url, "active": bool(VOICE_NODE_JOBS.get(index)), "job_id": VOICE_NODE_JOBS.get(index)}
            for index, url in enumerate(nodes)
        ]
    runtime_config = load_config()
    image_plan = provider_service_plan(runtime_config, "image")
    image_configs = [dict(item["service"]) for item in image_plan["ready"]]
    image_overview = IMAGE_NODE_POOL.overview()
    return {
        "status": "ok", "pipeline_version": PIPELINE_VERSION, "renderer": PYTHON.exists(), "tts": nodes,
        "queues": {
            "voice": {"concurrency": len(nodes), "waiting": VOICE_QUEUE.qsize(), "nodes": voice_nodes},
            "model": {"concurrency": MODEL_CONCURRENCY, "waiting": MODEL_QUEUE.qsize()},
            "image": {
                "default_rpm": IMAGE_GENERATION_RPM,
                "max_rpm": IMAGE_GENERATION_MAX_RPM,
                "global_rpm_limit": IMAGE_GENERATION_GLOBAL_RPM,
                **image_overview,
                "nodes": IMAGE_NODE_POOL.snapshot(image_configs),
            },
            "render": {"concurrency": RENDER_JOB_CONCURRENCY, "active": render_active, "waiting": max(0, render_waiting - render_active)},
        },
    }


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return safe_config(load_config())


@app.get("/api/styles")
def get_style_catalog() -> dict[str, Any]:
    """Expose the exact visual recipes used by image prompts for the local UI."""
    return {
        "styles": [
            {"name": name, "recipe": recipe}
            for name, recipe in STYLE_PRESETS.items()
            if name != INFOGRAPHIC_STYLE
        ]
    }


@app.post("/api/image-nodes/{node_id}/reset-rpm-memory")
def reset_image_node_rpm_memory(node_id: str) -> dict[str, Any]:
    if not IMAGE_NODE_POOL.reset_failure_memory(node_id):
        raise HTTPException(status_code=404, detail="没有找到该图片节点的运行状态")
    return {"ok": True, "node_id": node_id, "message": "该节点的失败档位记忆已解除；当前429冷却仍继续生效"}


@app.post("/api/config")
def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    masked_keys = ("api_key", "image_api_key")
    clearable_keys = ("tts_url_2", "image_base_url", "image_api_key")
    for key in DEFAULT_CONFIG:
        value = payload.get(key)
        if key in masked_keys and isinstance(value, str) and "••••" in value:
            continue
        # Optional string fields must accept an empty value so the user can
        # switch back to the shared provider without editing the JSON file.
        if key in clearable_keys and isinstance(value, str):
            current[key] = value.strip()
            continue
        if value not in (None, ""):
            current[key] = value
    current = resolve_configured_models(current)
    STATE_DIR.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    IMAGE_NODE_POOL.configure(
        global_rpm_limit=max(1, min(500, int(current.get("image_global_rpm_limit") or IMAGE_GENERATION_GLOBAL_RPM))),
        global_in_flight_limit=max(10, min(500, int(current.get("image_global_in_flight_limit") or IMAGE_GLOBAL_IN_FLIGHT_LIMIT))),
    )
    ensure_pipeline_workers()
    return safe_config(current)


@app.post("/api/config/models")
def detect_models(payload: dict[str, Any]) -> dict[str, Any]:
    config = merged_provider_config(payload)
    image_config = image_provider_config(config)
    same_provider = image_config.get("base_url") == config.get("base_url") and image_config.get("api_key") == config.get("api_key")
    if same_provider:
        text_models = provider_models(config, timeout=8)
        image_models = text_models
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            text_future = executor.submit(provider_models, config, 8)
            image_future = executor.submit(provider_models, image_config, 8)
            text_models = text_future.result()
            image_models = image_future.result()
    text_catalog = build_model_catalog(text_models, str(config["text_model"]), str(config["image_model"]))
    image_catalog = build_model_catalog(image_models, str(config["text_model"]), str(config["image_model"]))
    selected_text_model = str(text_catalog["selected_text_model"] or "")
    selected_image_model = str(image_catalog["selected_image_model"] or "")
    return {
        "text_models": [selected_text_model] if selected_text_model else [],
        "image_models": [selected_image_model] if selected_image_model else [],
        "selected_text_model": selected_text_model,
        "selected_image_model": selected_image_model,
    }


@app.post("/api/config/test")
def test_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = resolve_configured_models(merged_provider_config(payload))
    results: dict[str, Any] = {}
    try:
        provider_text(config, str(config["text_model"]), "只回复：连接成功", timeout=60)
        results["openlux"] = {"ok": True, "message": f"文本模型 {config['text_model']} 连接成功"}
    except Exception as exc:
        results["openlux"] = {"ok": False, "message": str(exc)}
    try:
        models = provider_models(image_provider_config(config))
        image_model = str(config["image_model"])
        if models and image_model not in models:
            raise RuntimeError(f"当前 Key 的模型列表中没有 {image_model}")
        results["image"] = {"ok": True, "message": f"{image_model} 已可用" if models else f"{image_model} 将在生成时验证"}
    except Exception as exc:
        results["image"] = {"ok": False, "message": str(exc)}
    tts_results: list[dict[str, Any]] = []
    for index, url in enumerate(configured_tts_nodes(config), 1):
        try:
            check = f"{url}/gradio_api/info" if config.get("tts_mode") == "gradio" else f"{url}/api/health"
            response = httpx.get(check, timeout=8)
            response.raise_for_status()
            tts_results.append({"index": index, "url": url, "ok": True, "message": f"语音节点 {index} 连接成功"})
        except Exception as exc:
            tts_results.append({"index": index, "url": url, "ok": False, "message": f"语音节点 {index} 连接失败：{exc}"})
    tts_ok = bool(tts_results) and all(item["ok"] for item in tts_results)
    results["tts_nodes"] = tts_results
    results["tts"] = {"ok": tts_ok, "message": "；".join(str(item["message"]) for item in tts_results) or "未配置语音节点"}
    return results


@app.get("/api/preferences")
def get_preferences() -> dict[str, Any]:
    if not PREFERENCES_PATH.exists():
        return {"pen_text": "", "stroke_detail": "detailed"}
    try:
        data = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pen_text": "", "stroke_detail": "detailed"}
    detail = str(data.get("stroke_detail", "detailed"))
    return {"pen_text": str(data.get("pen_text", ""))[:12], "stroke_detail": detail if detail in {"light", "standard", "detailed", "full"} else "detailed"}


@app.post("/api/preferences")
def save_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    detail = str(payload.get("stroke_detail", "detailed"))
    preferences = {
        "pen_text": str(payload.get("pen_text", "")).strip()[:12],
        "stroke_detail": detail if detail in {"light", "standard", "detailed", "full"} else "detailed",
    }
    STATE_DIR.mkdir(exist_ok=True)
    PREFERENCES_PATH.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")
    return preferences


@app.post("/api/jobs")
async def create_job(
    request: Request,
    script: str = Form(..., alias="copy"),
    style: str = Form("极简粗线简笔白板风"),
    scenes_per_image: int = Form(1),
    aspect_ratio: str = Form("16:9"),
    task_name: str = Form(""),
    pen_text: str = Form(""),
    include_key_text: bool = Form(True),
    include_subtitles: bool = Form(True),
    stroke_detail: str = Form("detailed"),
    presentation_mode: str = Form("whiteboard"),
    identity_mode: str = Form(DEFAULT_IDENTITY_MODE),
    voice_mode: str = Form("clone"),
    reference: UploadFile | None = File(None),
    reference_mode: str = Form("standard"),
    character_manifest: str = Form("[]"),
    style_reference: UploadFile | None = File(None),
    character_references: list[UploadFile] | None = File(None),
) -> dict[str, Any]:
    if len(script.strip()) < 10:
        raise HTTPException(400, "文案至少需要 10 个字")
    voice_mode = voice_mode if voice_mode in {"none", "uploaded", "clone"} else "clone"
    if voice_mode != "none" and reference is None:
        raise HTTPException(400, "克隆音色需要参考音频" if voice_mode == "clone" else "直接使用旁白需要完整旁白音频")
    if voice_mode == "clone" and not configured_tts_nodes():
        raise HTTPException(400, "克隆音色需要先配置至少一个语音节点")
    with LOCK:
        pending = sum(1 for item in JOBS.values() if item.get("status") in {"queued", "running"})
    if pending >= MAX_ACTIVE_AND_QUEUED:
        raise HTTPException(429, f"当前已有 {pending} 个任务，请稍后再提交")
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    reference_path: Path | None = None
    if reference is not None:
        suffix = Path(reference.filename or "reference.wav").suffix or ".wav"
        reference_path = job_dir / f"reference{suffix}"
        with reference_path.open("wb") as target:
            shutil.copyfileobj(reference.file, target)
    reference_mode = reference_mode if reference_mode in {"custom", "infographic"} else "standard"
    visual_references: dict[str, Any] = {}
    if reference_mode == "custom":
        uploads = character_references or []
        try:
            manifest = json.loads(character_manifest)
        except json.JSONDecodeError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "人物参考信息格式无效") from exc
        if style_reference is None or not isinstance(manifest, list) or not 1 <= len(manifest) <= 5:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "自定义参考需要 1 张风格图和 1–5 个人物")
        try:
            counts = [int(item.get("file_count", 0)) for item in manifest if isinstance(item, dict)]
        except (TypeError, ValueError) as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "人物参考图片数量无效") from exc
        if len(counts) != len(manifest) or any(count < 1 or count > 3 for count in counts):
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "每个人物需要上传 1–3 张参考图")
        expected = sum(counts)
        if expected != len(uploads) or expected < 1 or expected > 15:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "人物参考图片数量不匹配")
        style_suffix = Path(style_reference.filename or "style.png").suffix.lower()
        if style_suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "风格参考图只支持 PNG、JPG 或 WebP")
        style_path = job_dir / f"style-reference{style_suffix}"
        with style_path.open("wb") as target:
            shutil.copyfileobj(style_reference.file, target)
        saved_characters: list[dict[str, Any]] = []
        cursor = 0
        for character_index, item in enumerate(manifest, 1):
            if not isinstance(item, dict):
                continue
            count = max(1, min(3, int(item.get("file_count", 1))))
            image_names: list[str] = []
            for image_index, upload in enumerate(uploads[cursor:cursor + count], 1):
                suffix = Path(upload.filename or "character.png").suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(400, "人物参考图只支持 PNG、JPG 或 WebP")
                image_name = f"character-{character_index:02d}-{image_index:02d}{suffix}"
                image_path = job_dir / image_name
                with image_path.open("wb") as target:
                    shutil.copyfileobj(upload.file, target)
                if image_path.stat().st_size > 15 * 1024 * 1024 or not valid_image_file(image_path):
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(400, "人物参考图无效或超过 15MB")
                image_names.append(image_name)
            cursor += count
            saved_characters.append({
                "name": str(item.get("name") or f"人物 {character_index}").strip()[:20],
                "description": str(item.get("description") or "").strip()[:80],
                "images": image_names,
            })
        if style_path.stat().st_size > 15 * 1024 * 1024 or not valid_image_file(style_path):
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "风格参考图无效或超过 15MB")
        visual_references = {"style_image": style_path.name, "characters": saved_characters}
    scenes_per_image = max(1, min(4, scenes_per_image))
    aspect_ratio = normalize_aspect_ratio(aspect_ratio)
    stroke_detail = stroke_detail if stroke_detail in {"light", "standard", "detailed", "full"} else "detailed"
    presentation_mode = normalize_presentation_mode(presentation_mode)
    identity_mode = normalize_identity_mode(identity_mode)
    if presentation_mode == "story-color":
        aspect_ratio = "3:4"
        scenes_per_image = 1
        include_key_text = False
        include_subtitles = True
    task_name = normalized_task_name(task_name, script, job_id)
    now = time.time()
    with LOCK:
        JOBS[job_id] = {
            "id": job_id, "status": "queued", "stage": "等待建立无旁白时间轴" if voice_mode == "none" else "等待处理上传旁白" if voice_mode == "uploaded" else "等待语音克隆", "progress": 1,
            "created_at": now, "started_at": now, "timings": {},
            "queue_stage": "voice", "queue_order": time.time_ns(),
            "client_ip": request_client_ip(request),
            "job_type": "infographic" if reference_mode == "infographic" else "generate", "style": style, "scenes_per_image": scenes_per_image,
            "pipeline_version": PIPELINE_VERSION if reference_mode == "infographic" else "standard_v1",
            "reference_mode": reference_mode, "character_count": len(visual_references.get("characters", [])),
            "aspect_ratio": aspect_ratio,
            "visual_references": visual_references,
            "task_name": task_name,
            "voice_mode": voice_mode,
            "identity_mode": identity_mode,
            "copy": script.strip(),
            "pen_text": pen_text.strip()[:12], "include_key_text": include_key_text,
            "include_subtitles": include_subtitles,
            "stroke_detail": stroke_detail, "presentation_mode": presentation_mode, "can_rerender": False,
            "current_phase": None, "phase_started_at": None, "total_elapsed": 0.0,
        }
        _persist_job_locked(job_id)
    VOICE_QUEUE.put((job_id, script.strip(), style, reference_path, scenes_per_image, pen_text.strip()[:12], include_key_text, include_subtitles, stroke_detail, voice_mode))
    ensure_pipeline_workers()
    return job_snapshot(job_id)


@app.get("/api/jobs")
def list_jobs(limit: int = 20) -> dict[str, Any]:
    with LOCK:
        ids = sorted(JOBS, key=lambda item: float(JOBS[item].get("created_at", 0)), reverse=True)[:max(1, min(100, limit))]
    return {"items": [job_snapshot(job_id) for job_id in ids]}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    now = time.time()
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "任务不存在")
        item = JOBS[job_id]
        if item.get("status") not in {"queued", "running"}:
            raise HTTPException(400, "该任务当前不需要取消")
        current = item.get("current_phase")
        started = item.get("phase_started_at")
        if current and started:
            entry = item.setdefault("timings", {}).setdefault(current, {"label": current, "seconds": 0.0})
            entry["seconds"] = float(entry.get("seconds", 0.0)) + max(0.0, now - float(started))
        item.update(
            status="cancelled",
            stage="任务已取消",
            error=None,
            cancel_requested=True,
            cancelled_at=now,
            finished_at=now,
            current_phase=None,
            phase_started_at=None,
            total_elapsed=max(0.0, now - float(item.get("started_at", now))),
        )
        _persist_job_locked(job_id)
    terminate_running_process(job_id)
    return job_snapshot(job_id)


def parameter_source(job_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "历史任务不存在")
        selected = JOBS[job_id].copy()
        source_id = job_id
        source = selected
        visited = {job_id}
        while source.get("job_type") == "rerender" and source.get("rerender_of"):
            candidate = str(source["rerender_of"])
            if candidate in visited or candidate not in JOBS:
                break
            visited.add(candidate)
            source_id = candidate
            source = JOBS[candidate].copy()
    return source_id, source, selected


def asset_descriptor(job_id: str, filename: str | None) -> dict[str, str] | None:
    if not filename:
        return None
    path = JOBS_DIR / job_id / filename
    if not path.is_file():
        return None
    return {
        "name": filename,
        "url": f"/api/jobs/{job_id}/assets/{filename}",
        "content_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
    }


@app.get("/api/jobs/{job_id}/parameters")
def get_job_parameters(job_id: str) -> dict[str, Any]:
    source_id, source, selected = parameter_source(job_id)
    source_dir = JOBS_DIR / source_id
    reference = next(iter(sorted(source_dir.glob("reference.*"))), None)
    visual_references = source.get("visual_references") if isinstance(source.get("visual_references"), dict) else {}
    style_filename = str(visual_references.get("style_image") or "")
    characters: list[dict[str, Any]] = []
    for index, raw in enumerate(visual_references.get("characters") or [], 1):
        if not isinstance(raw, dict):
            continue
        images = [
            descriptor
            for name in raw.get("images") or []
            if (descriptor := asset_descriptor(source_id, str(name))) is not None
        ]
        characters.append({
            "name": str(raw.get("name") or f"人物 {index}"),
            "description": str(raw.get("description") or ""),
            "images": images,
        })
    reference_mode = str(source.get("reference_mode") or "standard")
    if reference_mode not in {"standard", "custom", "infographic"}:
        reference_mode = "custom" if visual_references else "standard"
    return {
        "job_id": job_id,
        "source_job_id": source_id,
        "copy": str(source.get("copy") or ""),
        "voice_mode": str(source.get("voice_mode")) if source.get("voice_mode") in {"none", "uploaded", "clone"} else "clone",
        "reference_mode": reference_mode,
        "style": str(source.get("style") or DEFAULT_STYLE),
        "scenes_per_image": max(1, min(4, int(source.get("scenes_per_image", 1)))),
        "aspect_ratio": normalize_aspect_ratio(source.get("aspect_ratio")),
        "task_name": str(selected.get("task_name") or source.get("task_name") or ""),
        "pen_text": str(selected.get("pen_text", source.get("pen_text", ""))),
        "include_key_text": bool(selected.get("include_key_text", source.get("include_key_text", True))),
        "include_subtitles": bool(selected.get("include_subtitles", source.get("include_subtitles", True))),
        "stroke_detail": str(selected.get("stroke_detail", source.get("stroke_detail", "detailed"))),
        "presentation_mode": normalize_presentation_mode(selected.get("presentation_mode", source.get("presentation_mode"))),
        "identity_mode": normalize_identity_mode(source.get("identity_mode")),
        "reference": asset_descriptor(source_id, reference.name if reference else None),
        "style_reference": asset_descriptor(source_id, style_filename),
        "characters": characters,
    }


@app.get("/api/jobs/{job_id}/assets/{filename}")
def get_job_input_asset(job_id: str, filename: str) -> FileResponse:
    if Path(filename).name != filename:
        raise HTTPException(404, "素材不存在")
    with LOCK:
        item = JOBS.get(job_id)
        if item is None:
            raise HTTPException(404, "历史任务不存在")
        visual_references = item.get("visual_references") if isinstance(item.get("visual_references"), dict) else {}
    allowed = {path.name for path in (JOBS_DIR / job_id).glob("reference.*")}
    style_filename = str(visual_references.get("style_image") or "")
    if style_filename:
        allowed.add(style_filename)
    for character in visual_references.get("characters") or []:
        if isinstance(character, dict):
            allowed.update(str(name) for name in character.get("images") or [])
    if filename not in allowed:
        raise HTTPException(404, "素材不存在")
    path = JOBS_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(404, "素材不存在")
    return FileResponse(path, media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream", filename=filename)


@app.get("/api/jobs/{job_id}/gallery")
def get_job_gallery(job_id: str) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "历史任务不存在")
    job_dir = JOBS_DIR / job_id
    images = sorted(
        (path for path in job_dir.glob("board-*.png") if re.fullmatch(r"board-\d+\.png", path.name)),
        key=lambda path: int(re.search(r"\d+", path.stem).group()) if re.search(r"\d+", path.stem) else 0,
    )
    try:
        manifest = json.loads((job_dir / "boards.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = []
    if not isinstance(manifest, list):
        manifest = []
    items: list[dict[str, Any]] = []
    for path in images:
        match = re.search(r"\d+", path.stem)
        page = int(match.group()) if match else len(items) + 1
        board = manifest[page - 1] if page <= len(manifest) and isinstance(manifest[page - 1], dict) else {}
        items.append({
            "name": path.name,
            "page": page,
            "url": f"/api/jobs/{job_id}/images/{path.name}?v={path.stat().st_mtime_ns}",
            "size": path.stat().st_size,
            "prompt": str(board.get("image_prompt") or ""),
            "scene_numbers": board.get("scene_numbers") if isinstance(board.get("scene_numbers"), list) else [],
        })
    return {
        "job_id": job_id,
        "items": items,
    }


@app.get("/api/jobs/{job_id}/images/{filename}")
def get_job_generated_image(job_id: str, filename: str) -> FileResponse:
    if job_id not in JOBS or not re.fullmatch(r"board-\d+\.png", filename):
        raise HTTPException(404, "图片不存在")
    path = JOBS_DIR / job_id / filename
    if not valid_image_file(path):
        raise HTTPException(404, "图片不存在或尚未生成")
    return FileResponse(path, media_type="image/png")


@app.post("/api/jobs/{job_id}/boards/{page}/regenerate")
def regenerate_job_board(job_id: str, page: int, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < 5:
        raise HTTPException(400, "提示词至少需要 5 个字")
    if len(prompt) > 6000:
        raise HTTPException(400, "提示词不能超过 6000 个字")
    job_dir = JOBS_DIR / job_id
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "历史任务不存在")
        source = JOBS[job_id]
        if source.get("status") in {"queued", "running"}:
            raise HTTPException(409, "当前任务仍在执行，请完成或取消后再重生成图片")
        image = job_dir / f"board-{page:02d}.png"
        if page < 1 or not valid_image_file(image):
            raise HTTPException(404, "要重生成的图片不存在")
        pending = sum(1 for item in JOBS.values() if item.get("status") in {"queued", "running"})
        if pending >= MAX_ACTIVE_AND_QUEUED:
            raise HTTPException(429, f"当前已有 {pending} 个任务，请稍后再试")
        source.update(
            status="queued",
            stage=f"第 {page} 张图片等待重生成",
            progress=45,
            error=None,
            finished_at=None,
            current_phase=None,
            phase_started_at=None,
            queue_stage="model",
            queue_order=time.time_ns(),
            client_ip=request_client_ip(request),
            can_rerender=False,
            board_regeneration={"page": page, "prompt": prompt},
        )
        _persist_job_locked(job_id)
    MODEL_QUEUE.put(("regenerate_board", job_id, page, prompt))
    ensure_pipeline_workers()
    return job_snapshot(job_id)


@app.post("/api/jobs/{job_id}/retry")
def retry_failed_job(job_id: str, request: Request) -> dict[str, Any]:
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "历史任务不存在")
        source = JOBS[job_id]
        if source.get("status") != "error":
            raise HTTPException(400, "只有失败任务可以继续")
        pending = sum(1 for item in JOBS.values() if item.get("status") in {"queued", "running"})
        if pending >= MAX_ACTIVE_AND_QUEUED:
            raise HTTPException(429, f"当前已有 {pending} 个任务，请稍后再试")
        source.update(
            status="queued", stage="正在检查任务断点", error=None, finished_at=None,
            current_phase=None, phase_started_at=None, queue_order=time.time_ns(),
            client_ip=request_client_ip(request),
            manual_retry_count=int(source.get("manual_retry_count", 0)) + 1,
        )
        item = source.copy()
        _persist_job_locked(job_id)
    try:
        enqueue_job_from_checkpoint(job_id, item)
        ensure_pipeline_workers()
    except Exception as exc:
        fail_job(job_id, "继续任务失败", exc)
    return job_snapshot(job_id)


@app.post("/api/jobs/{job_id}/rerender")
def create_rerender(job_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "历史任务不存在")
    source_dir = JOBS_DIR / job_id
    required = [source_dir / "voice.wav", source_dir / "plan.json"]
    if any(not path.exists() for path in required) or not list(source_dir.glob("board-*.png")):
        raise HTTPException(400, "该任务缺少配音、分镜计划或原图，无法重新渲染")
    with LOCK:
        pending = sum(1 for item in JOBS.values() if item.get("status") in {"queued", "running"})
        source = JOBS[job_id].copy()
    if pending >= MAX_ACTIVE_AND_QUEUED:
        raise HTTPException(429, f"当前已有 {pending} 个任务，请稍后再提交")
    detail = str(payload.get("stroke_detail", source.get("stroke_detail", "detailed")))
    detail = detail if detail in {"light", "standard", "detailed", "full"} else "detailed"
    scenes_per_image = max(1, min(4, int(source.get("scenes_per_image", 1))))
    task_name = normalized_task_name(payload.get("task_name") or source.get("task_name"), str(source.get("copy", "")), job_id)
    pen_text = str(payload.get("pen_text", source.get("pen_text", ""))).strip()[:12]
    include_key_text = bool(payload.get("include_key_text", source.get("include_key_text", True)))
    include_subtitles = bool(payload.get("include_subtitles", source.get("include_subtitles", True)))
    presentation_mode = normalize_presentation_mode(payload.get("presentation_mode", source.get("presentation_mode")))
    if presentation_mode == "story-color":
        scenes_per_image = 1
        include_key_text = False
        include_subtitles = True
    new_id = uuid.uuid4().hex[:12]
    target_dir = JOBS_DIR / new_id
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("voice.wav", "plan.json", "boards.json"):
        candidate = source_dir / name
        if candidate.exists():
            shutil.copy2(candidate, target_dir / name)
    for image in source_dir.glob("board-*.png"):
        shutil.copy2(image, target_dir / image.name)
    now = time.time()
    with LOCK:
        JOBS[new_id] = {
            "id": new_id, "status": "queued", "stage": "准备重新渲染", "progress": 1,
            "created_at": now, "started_at": now, "timings": {},
            "queue_stage": "render", "queue_order": time.time_ns(),
            "client_ip": request_client_ip(request),
            "job_type": "rerender", "rerender_of": job_id, "style": source.get("style", ""),
            "reference_mode": source.get("reference_mode", "standard"),
            "aspect_ratio": normalize_aspect_ratio(source.get("aspect_ratio")),
            "voice_mode": source.get("voice_mode", "clone"),
            "pipeline_version": PIPELINE_VERSION if is_infographic_job(job_id) else source.get("pipeline_version", "standard_v1"),
            "task_name": task_name,
            "scenes_per_image": scenes_per_image, "pen_text": pen_text,
            "include_key_text": include_key_text, "include_subtitles": include_subtitles,
            "stroke_detail": detail, "presentation_mode": presentation_mode, "can_rerender": False,
            "current_phase": None, "phase_started_at": None, "total_elapsed": 0.0,
        }
        _persist_job_locked(new_id)
    if is_infographic_job(new_id):
        scenes = json.loads((target_dir / "plan.json").read_text(encoding="utf-8"))
        duration = probe_duration(target_dir / "voice.wav")
        boards = [[scene] for scene in scenes]
        start_render_task(render_generated_job, new_id, scenes, boards, pen_text, include_subtitles, detail, duration)
    else:
        start_render_task(rerender_job, new_id, scenes_per_image, pen_text, include_key_text, include_subtitles, detail)
    return job_snapshot(new_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "任务不存在或服务已经重启")
    return job_snapshot(job_id)


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    item = JOBS.get(job_id)
    if not item:
        raise HTTPException(404, "任务不存在")
    result_name = str(item.get("result_file") or "final.mp4")
    if result_name not in {"final.mp4", "final-remotion-v1.mp4"}:
        raise HTTPException(404, "视频文件记录无效")
    path = JOBS_DIR / job_id / result_name
    if not path.exists():
        raise HTTPException(404, "视频尚未生成")
    return FileResponse(path, media_type="video/mp4", filename=f"whiteboard-{job_id}.mp4")

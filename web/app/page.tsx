"use client";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
const API = process.env.NEXT_PUBLIC_API_BASE || "";
const LOCAL_PREFERENCES_KEY = "whiteboard-maker:local-preferences:v1";
type ServiceNode = {
  id: string;
  base_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
  rpm_limit?: number;
  rpd_limit?: number;
  utilization_percent?: number;
  max_input_images?: number;
};
type Config = {
  api_key: string;
  base_url: string;
  text_model: string;
  image_model: string;
  image_base_url: string;
  image_api_key: string;
  text_services: ServiceNode[];
  image_services: ServiceNode[];
  image_global_rpm_limit: number;
  image_global_in_flight_limit: number;
  tts_url: string;
  tts_url_2: string;
  tts_mode: string;
  has_api_key?: boolean;
  has_image_api_key?: boolean;
};
type TimingEntry = { label: string; seconds: number; running?: boolean };
type Job = {
  id: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  stage: string;
  progress: number;
  client_ip?: string;
  queue_ahead?: number;
  created_at?: number;
  task_name?: string;
  pen_text?: string;
  style?: string;
  stroke_detail?: string;
  job_type?: string;
  rerender_of?: string;
  rerender_version?: number;
  next_rerender_version?: number;
  can_rerender?: boolean;
  needs_rerender?: boolean;
  can_retry?: boolean;
  can_cancel?: boolean;
  model_retry_count?: number;
  manual_retry_count?: number;
  result_url?: string;
  error?: string;
  duration?: number;
  scenes?: number;
  boards?: number;
  image_count?: number;
  total_elapsed?: number;
  current_elapsed?: number;
  resume_count?: number;
  checkpoint?: string;
  timings?: Record<string, TimingEntry>;
};
type CharacterReference = {
  id: string;
  name: string;
  description: string;
  files: File[];
};
type CharacterAsset = {
  id: string;
  style: string;
  label: string;
  description: string;
  status: "queued" | "review" | "approved" | "rejected" | "error";
  image_url?: string | null;
  error?: string | null;
};
type CharacterBinding = {
  role_id: string;
  story_name: string;
  gender: string;
  age_group: string;
  description: string;
  core_personality?: string;
  facial_persona?: string;
  temporary_behavior?: string;
  asset_id: string | null;
  asset_label?: string | null;
  asset_image_url?: string | null;
  persona_compatible?: boolean;
  match_confidence?: number;
  match_reason?: string;
};
type InputAsset = { name: string; url: string; content_type: string };
type VoiceMode = "none" | "clone" | "uploaded";
type IdentityMode = "consistent" | "male" | "female";
type JobParameters = {
  copy: string;
  voice_mode: VoiceMode;
  identity_mode: IdentityMode;
  reference_mode: "standard" | "custom" | "infographic";
  style: string;
  scenes_per_image: number;
  aspect_ratio: string;
  presentation_mode: "whiteboard" | "story-color";
  task_name: string;
  pen_text: string;
  include_key_text: boolean;
  include_subtitles: boolean;
  stroke_detail: string;
  reference: InputAsset | null;
  style_reference: InputAsset | null;
  characters: { name: string; description: string; images: InputAsset[] }[];
  character_bindings?: CharacterBinding[];
};
type GalleryItem = {
  name: string;
  page: number;
  url: string;
  size: number;
  prompt?: string;
  scene_numbers?: number[];
};
type AssetPreview = { src: string; label: string };
type ServiceHealth = {
  queues: {
    voice: {
      concurrency: number;
      waiting: number;
      nodes: {
        index: number;
        url: string;
        active: boolean;
        job_id?: string | null;
      }[];
    };
    model: { concurrency: number; waiting: number };
    image: {
      default_rpm?: number;
      default_concurrency?: number;
      max_rpm?: number;
      global_rpm_limit?: number;
      global_in_flight?: number;
      global_in_flight_limit?: number;
      waiting?: number;
      nodes: {
        node_id: string;
        base_url: string;
        rpm?: number;
        rpm_limit?: number;
        rpd_limit?: number;
        utilization_percent?: number;
        safe_rpm_target?: number;
        effective_rpm_limit?: number;
        concurrency?: number;
        in_flight: number;
        in_flight_limit?: number;
        rate_limit_count: number;
        rate_limit_strikes?: number;
        unavailable_count?: number;
        average_latency: number;
        cooldown_seconds: number;
        next_request_seconds?: number;
        tier_successes?: number;
        tier_lock_seconds?: number;
        tier_failure_count?: number;
        failed_tier?: number;
        runtime_rpm_capped?: boolean;
        recovery_mode?: boolean;
        promotion_required_seconds?: number;
        promotion_required_successes?: number;
        daily_budget?: number;
        daily_used?: number;
        daily_remaining?: number | null;
        daily_exhausted?: boolean;
        daily_reset_seconds?: number;
        circuit_reason?: string;
      }[];
    };
    render: { concurrency: number; active: number; waiting: number };
  };
};
type ModelCatalog = {
  text_models: string[];
  image_models: string[];
  selected_text_model: string;
  selected_image_model: string;
};
type StylePromptPreview = {
  full_prompt: string;
  sent_prompt: string;
  full_length: number;
  sent_length: number;
  truncated: boolean;
  request: { prompt_limit: number; n: number; size: string; quality: string; format: string };
};
type SaveState = "idle" | "pending" | "saving" | "saved" | "error";
const defaults: Config = {
  api_key: "",
  base_url: "https://api.openlux.ai/v1",
  text_model: "gpt-5",
  image_model: "gpt-image-2",
  image_base_url: "",
  image_api_key: "",
  text_services: [],
  image_services: [],
  image_global_rpm_limit: 200,
  image_global_in_flight_limit: 80,
  tts_url: "http://127.0.0.1:7860",
  tts_url_2: "",
  tts_mode: "gradio",
};
const imageCapacityPresets = [
  { label: "手动设置", rpm: 0, rpd: 0 },
  { label: "自营GPT绘画 · 50 RPM / 800 RPD", rpm: 50, rpd: 800 },
  { label: "自营GPT特惠 · 60 RPM / 1100 RPD", rpm: 60, rpd: 1100 },
  { label: "GPT稳定绘画 · 90 RPM / 1600 RPD", rpm: 90, rpd: 1600 },
  { label: "GPT原生分辨率 · 40 RPM / 600 RPD", rpm: 40, rpd: 600 },
  { label: "VIP · 70 RPM / 1200 RPD", rpm: 70, rpd: 1200 },
  { label: "视觉聚合 · 90 RPM / 1500 RPD", rpm: 90, rpd: 1500 },
  { label: "视觉外接供应商 · 100 RPM / 1700 RPD", rpm: 100, rpd: 1700 },
  { label: "视觉默认组 · 110 RPM / 1800 RPD", rpm: 110, rpd: 1800 },
];
const clampNumber = (value: unknown, min: number, max: number, fallback: number) => (Number.isFinite(Number(value)) ? Math.max(min, Math.min(max, Math.round(Number(value)))) : fallback);
const normalizeRpmLimit = (value: unknown) => clampNumber(value, 1, 300, 10);
const imageCircuitLabel = (reason?: string) =>
  (
    ({
      rate_limit: "连续429熔断",
      rate_limit_cooldown: "429冷却",
      unavailable: "服务异常熔断",
      authentication: "认证熔断",
    }) as Record<string, string>
  )[reason || ""] || "健康";
const normalizeConfig = (data: Config): Config => ({
  ...data,
  image_global_rpm_limit: clampNumber(data.image_global_rpm_limit, 1, 500, 200),
  image_global_in_flight_limit: clampNumber(data.image_global_in_flight_limit, 10, 500, 80),
  text_services: data.text_services?.length
    ? data.text_services
    : [
        {
          id: "text-primary",
          base_url: data.base_url,
          api_key: data.api_key,
          model: data.text_model,
          enabled: true,
        },
      ],
  image_services: (data.image_services?.length
    ? data.image_services
    : [
        {
          id: "image-primary",
          base_url: data.image_base_url || data.base_url,
          api_key: data.image_api_key || data.api_key,
          model: data.image_model,
          enabled: true,
        },
      ]
  ).map((node) => ({
    ...node,
    rpm_limit: normalizeRpmLimit(node.rpm_limit),
    rpd_limit: clampNumber(node.rpd_limit, 0, 100000, 0),
    utilization_percent: clampNumber(node.utilization_percent, 10, 100, 80),
    max_input_images: clampNumber(node.max_input_images, 1, 32, 4),
  })),
});
const providerPayloadFor = (source: Config) => {
  const text = source.text_services.find((item) => item.enabled) || source.text_services[0];
  const image = source.image_services.find((item) => item.enabled) || source.image_services[0];
  return {
    ...source,
    base_url: text?.base_url || source.base_url,
    api_key: text?.api_key || source.api_key,
    text_model: text?.model || source.text_model,
    image_base_url: image?.base_url || source.image_base_url,
    image_api_key: image?.api_key || source.image_api_key,
    image_model: image?.model || source.image_model,
  };
};
const serviceSignature = (kind: "text" | "image", node: ServiceNode) => `${kind}:${node.id}:${node.base_url.trim()}:${node.api_key.trim()}`;
const serviceAvailability = (nodes: ServiceNode[]) => ({
  total: nodes.length,
  ready: nodes.filter((node) => node.enabled && node.base_url.trim() && node.api_key.trim() && node.model.trim()).length,
});
const hasPendingRerender = (job: Job) => Boolean(job.needs_rerender || /图片已重新生成，可重新渲染成片/.test(job.stage));
const countScriptUnits = (text: string) => Math.max(1, (text.match(/[^。！？!?；;\n]+[。！？!?；;]?/g) || []).filter((item) => item.trim()).length);
const estimateMinutes = (text: string) => Math.max(1 / 8, text.trim().length / 250);
const estimateSceneCount = (text: string) => Math.max(1, Math.min(20, countScriptUnits(text), Math.max(1, Math.ceil(estimateMinutes(text) * 10))));
const normalizeIdentityMode = (value: unknown): IdentityMode => (value === "male" || value === "female" ? value : "consistent");
const identityModeDescriptions: Record<IdentityMode, string> = {
  consistent: "角色默认延续，剧情明确成长或换装时只更新相关属性",
  male: "固定为短黑发、深色上衣的普通中国青年男性",
  female: "固定为自然黑色齐肩发、深色上衣的普通中国青年女性",
};
const styleOptions = [
  {
    name: "极简粗线简笔白板风",
    image: "/styles/minimal-whiteboard.webp",
    desc: "粗黑线 · 少量配色 · 清爽留白",
  },
  {
    name: "极简商务涂鸦风",
    image: "/styles/business-doodle.webp",
    desc: "几何图表 · 蓝绿配色 · 专业克制",
  },
  {
    name: "暖米黄素描白板风",
    image: "/styles/warm-pencil.webp",
    desc: "铅笔排线 · 纸张质感 · 温暖细腻",
  },
  {
    name: "粗线扁平国风卡通",
    image: "/styles/guofeng-flat.webp",
    desc: "朱红玉绿 · 国风纹样 · 生动平涂",
  },
  {
    name: "爆款高热吸睛风",
    image: "/styles/viral-pop.webp",
    desc: "高饱和 · 强对比 · 短视频冲击力",
    badge: "热门",
  },
  {
    name: "黑金科技发布会风",
    image: "/styles/black-gold-tech.webp",
    desc: "黑金光效 · 科技舞台 · 高级权威",
  },
  {
    name: "清新治愈手账风",
    image: "/styles/healing-journal.webp",
    desc: "柔和水彩 · 治愈配色 · 生活手账",
  },
  {
    name: "复古报纸拼贴风",
    image: "/styles/retro-collage.webp",
    desc: "撕纸拼贴 · 半色调 · 编辑视觉",
  },
  {
    name: "纸感隐喻拼贴风",
    image: "/styles/paper-metaphor.png",
    desc: "手工剪纸 · 观点隐喻 · 高级克制",
  },
  {
    name: "漫画墨线解释风",
    image: "/styles/oil-visual.png",
    desc: "漫画墨线 · 半调网点 · 概念机制",
  },
  {
    name: "3D黏土趣味风",
    image: "/styles/clay-3d.webp",
    desc: "黏土材质 · 玩具比例 · 温暖可爱",
  },
  {
    name: "赛博霓虹漫画风",
    image: "/styles/cyber-neon.webp",
    desc: "霓虹青紫 · 漫画速度线 · 未来感",
  },
  {
    name: "清透日系生活绘本",
    image: "/styles/clear-japanese-storybook.png",
    desc: "细墨线 · 柔和淡彩 · 日常留白",
  },
  {
    name: "彩铅日记漫画（默认）",
    image: "/styles/story-handdrawn/01-colored-pencil-diary.png",
    desc: "笨拙墨线 · 低饱和彩铅 · 生活纪实",
    badge: "Skill",
  },
  {
    name: "极简黑白线条讲解",
    image: "/styles/story-handdrawn/02-minimal-line-explainer.png",
    desc: "细黑轮廓 · 火柴人 · 快速讲解",
    badge: "Skill",
  },
  {
    name: "五岁儿童蜡笔坏画",
    image: "/styles/story-handdrawn/03-kid-crayon.png",
    desc: "歪扭比例 · 越界涂色 · 天真粗糙",
    badge: "Skill",
  },
  {
    name: "潦草家庭投稿蜡笔",
    image: "/styles/story-handdrawn/04-rawkid-crayon.png",
    desc: "家庭投稿 · 断续乱涂 · 温暖日常",
    badge: "Skill",
  },
  {
    name: "小豆人涂鸦信息图",
    image: "/styles/story-handdrawn/05-bean-doodle-infographic.png",
    desc: "黑色豆人 · 单橙重点 · 清单步骤",
    badge: "Skill",
  },
  {
    name: "鼠标烂涂鸦",
    image: "/styles/story-handdrawn/06-ms-paint-bad-doodle.png",
    desc: "像素锯齿 · 荒谬比例 · 反转吐槽",
    badge: "Skill",
  },
  {
    name: "圆珠笔缠绕线速写",
    image: "/styles/story-handdrawn/07-ballpoint-scribble.png",
    desc: "自由缠线 · 黑白体积 · 情绪独白",
    badge: "Skill",
  },
  {
    name: "真实蜡笔纸实拍",
    image: "/styles/story-handdrawn/08-real-crayon-paper.png",
    desc: "真实纸纹 · 蜡质结块 · 成长记录",
    badge: "Skill",
  },
  {
    name: "水墨写意",
    image: "/styles/story-handdrawn/09-ink-wash.png",
    desc: "浓淡干湿 · 宣纸飞白 · 寓言感悟",
    badge: "Skill",
  },
  {
    name: "情绪叙事淡彩速写",
    image: "/styles/story-handdrawn/10-emotional-watercolor-sketch.png",
    desc: "靛蓝松线 · 淡彩留白 · 克制纪实",
    badge: "Skill",
  },
  {
    name: "中古动画水粉概念稿",
    image: "/styles/story-handdrawn/11-retro-gouache-concept.png",
    desc: "复古水粉 · 橙蓝互补 · 怀旧剧情",
    badge: "Skill",
  },
  {
    name: "暖光童画绘本",
    image: "/styles/story-handdrawn/12-sunlit-storybook.png",
    desc: "柔软水粉 · 暖边光 · 治愈童话",
    badge: "Skill",
  },
  {
    name: "北欧低饱和水粉绘本",
    image: "/styles/story-handdrawn/13-nordic-gouache-storybook.png",
    desc: "干刷水粉 · 北欧留白 · 安静日常",
    badge: "Skill",
  },
  {
    name: "墨线淡彩绘本",
    image: "/styles/story-handdrawn/14-inked-storybook.png",
    desc: "松散墨线 · 透亮淡彩 · 青春对白",
    badge: "Skill",
  },
  {
    name: "暖色几何扁平绘本",
    image: "/styles/story-handdrawn/15-warm-flat-storybook.png",
    desc: "圆润色块 · 蓝橙限定 · 品牌叙事",
    badge: "Skill",
  },
  {
    name: "稚拙马克笔笔记",
    image: "/styles/story-handdrawn/16-naive-marker-notes.png",
    desc: "粗马克笔 · 荧光重点 · 社媒观点",
    badge: "Skill",
  },
  {
    name: "Zine 孔版拼贴",
    image: "/styles/story-handdrawn/17-zine-riso-collage.png",
    desc: "撕纸拼贴 · 套印偏移 · 文化混剪",
    badge: "Skill",
  },
  {
    name: "有机轮廓品牌涂鸦",
    image: "/styles/story-handdrawn/18-organic-contour-doodle.png",
    desc: "自由单线 · 有机色形 · 生活品牌",
    badge: "Skill",
  },
  {
    name: "白板讲解动画",
    image: "/styles/story-handdrawn/19-whiteboard-explainer.png",
    desc: "白板笔迹 · 箭头框选 · 教程时间线",
    badge: "Skill",
  },
  {
    name: "粗粝木刻社论插画",
    image: "/styles/story-handdrawn/20-linocut-editorial.png",
    desc: "粗黑刻线 · 有限套色 · 社论力量",
    badge: "Skill",
  },
];
export default function Home() {
  const [pageMode, setPageMode] = useState<"standard" | "custom" | "infographic">("standard");
  const [styleReference, setStyleReference] = useState<File | null>(null);
  const [characters, setCharacters] = useState<CharacterReference[]>([{ id: "character-1", name: "人物 1", description: "", files: [] }]);
  const [characterLibraryOpen, setCharacterLibraryOpen] = useState(false);
  const [characterAssets, setCharacterAssets] = useState<CharacterAsset[]>([]);
  const [characterBindings, setCharacterBindings] = useState<CharacterBinding[]>([]);
  const [replacementRoleId, setReplacementRoleId] = useState<string | null>(null);
  const [replacementAssets, setReplacementAssets] = useState<CharacterAsset[]>([]);
  const [replacementLoading, setReplacementLoading] = useState(false);
  const [replacementError, setReplacementError] = useState("");
  const [characterMatchReady, setCharacterMatchReady] = useState(false);
  const [characterBusy, setCharacterBusy] = useState(false);
  const [drawingRoleId, setDrawingRoleId] = useState<string | null>(null);
  const [pendingDrawRoles, setPendingDrawRoles] = useState<Record<string, string>>({});
  const drawOriginRoles = useRef<Record<string, string>>({});
  const [drawLabel, setDrawLabel] = useState("角色候选");
  const [drawDescription, setDrawDescription] = useState("");
  const [drawCount, setDrawCount] = useState(1);
  const [selectedSourceAssetId, setSelectedSourceAssetId] = useState<string | null>(null);
  const [characterMessage, setCharacterMessage] = useState("");
  const [sharedJob, setSharedJob] = useState<Job | null>(null);
  const [modelCatalog, setModelCatalog] = useState<Record<string, string[]>>({});
  const [modelLoading, setModelLoading] = useState<Record<string, boolean>>({});
  const [modelDetectionMessage, setModelDetectionMessage] = useState("");
  const [includeKeyText, setIncludeKeyText] = useState(true);
  const [restoringJobId, setRestoringJobId] = useState<string | null>(null);
  const [detailJobId, setDetailJobId] = useState<string | null>(null);
  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [detailParameters, setDetailParameters] = useState<JobParameters | null>(null);
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const [previewImage, setPreviewImage] = useState<GalleryItem | null>(null);
  const [assetPreview, setAssetPreview] = useState<AssetPreview | null>(null);
  const [inputPreviewFile, setInputPreviewFile] = useState<File | null>(null);
  const [selectedGalleryPage, setSelectedGalleryPage] = useState<number | null>(null);
  const [promptDraft, setPromptDraft] = useState("");
  const [regeneratingPage, setRegeneratingPage] = useState<number | null>(null);
  const [detailActionMessage, setDetailActionMessage] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [renameJob, setRenameJob] = useState<Job | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [rerenderSource, setRerenderSource] = useState<Job | null>(null);
  const [rerenderName, setRerenderName] = useState("");
  const [rerendering, setRerendering] = useState(false);
  const [copy, setCopy] = useState("");
  const [reference, setReference] = useState<File | null>(null);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("clone");
  const [identityMode, setIdentityMode] = useState<IdentityMode>("consistent");
  const [style, setStyle] = useState("极简粗线简笔白板风");
  const [styleRecipes, setStyleRecipes] = useState<Record<string, string>>({});
  const [stylePromptPreview, setStylePromptPreview] = useState<StylePromptPreview | null>(null);
  const [scenesPerImage, setScenesPerImage] = useState(1);
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [presentationMode, setPresentationMode] = useState<"whiteboard" | "story-color">("whiteboard");
  const [taskName, setTaskName] = useState("");
  const [penText, setPenText] = useState("");
  const [strokeDetail, setStrokeDetail] = useState("detailed");
  const [includeSubtitles, setIncludeSubtitles] = useState(true);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [config, setConfig] = useState<Config>(defaults);
  const [health, setHealth] = useState<ServiceHealth | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [history, setHistory] = useState<Job[]>([]);
  const [message, setMessage] = useState("");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [connectionOk, setConnectionOk] = useState<boolean | null>(null);
  const [testing, setTesting] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const focusedJobId = useRef<string | null>(null);
  const restoredCharacterState = useRef<{ copy: string; style: string; bindings: CharacterBinding[]; ready: boolean } | null>(null);
  const configHydrated = useRef(false);
  const lastSavedConfig = useRef("");
  const saveRequest = useRef(0);
  const detectedServiceSignatures = useRef<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    fetch(`${API}/api/styles`)
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((payload) => {
        if (!active || !Array.isArray(payload.styles)) return;
        setStyleRecipes(Object.fromEntries(payload.styles.map((item: { name: string; recipe: string }) => [item.name, item.recipe])));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setStylePromptPreview(null);
    const timer = setTimeout(() => {
      fetch(`${API}/api/style-prompt-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_mode: pageMode,
          style,
          scenes_per_image: presentationMode === "story-color" ? 1 : scenesPerImage,
          aspect_ratio: presentationMode === "story-color" ? "3:4" : aspectRatio,
          presentation_mode: presentationMode,
          identity_mode: identityMode,
        }),
      })
        .then((response) => (response.ok ? response.json() : Promise.reject()))
        .then((payload: StylePromptPreview) => {
          if (active) setStylePromptPreview(payload);
        })
        .catch(() => undefined);
    }, 120);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [pageMode, style, scenesPerImage, aspectRatio, presentationMode, identityMode]);
  useEffect(() => {
    let active = true;
    let reconnectTimer: ReturnType<typeof setInterval> | null = null;
    const reconnect = async () => {
      try {
        const r = await fetch(`${API}/api/config`);
        if (!r.ok) throw new Error();
        const data = await r.json();
        if (active) {
          const normalized = normalizeConfig(data);
          setConfig(normalized);
          lastSavedConfig.current = JSON.stringify(providerPayloadFor(normalized));
          detectedServiceSignatures.current = Object.fromEntries([...normalized.text_services.map((node) => [`text:${node.id}`, serviceSignature("text", node)]), ...normalized.image_services.map((node) => [`image:${node.id}`, serviceSignature("image", node)])]);
          configHydrated.current = true;
          setMessage((current) => (current === "后端尚未启动" ? "" : current));
          if (reconnectTimer) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
          }
        }
      } catch {
        if (active) setMessage("后端尚未启动");
      }
    };
    reconnect();
    reconnectTimer = setInterval(reconnect, 3000);
    return () => {
      active = false;
      if (reconnectTimer) clearInterval(reconnectTimer);
      if (timer.current) clearInterval(timer.current);
    };
  }, []);
  useEffect(() => {
    try {
      const saved = localStorage.getItem(LOCAL_PREFERENCES_KEY);
      if (saved) {
        const data = JSON.parse(saved);
        setVoiceMode(normalizeVoiceMode(data.voice_mode));
        setIdentityMode(normalizeIdentityMode(data.identity_mode));
        setPenText(String(data.pen_text || ""));
        setStrokeDetail(["light", "standard", "detailed", "full"].includes(data.stroke_detail) ? data.stroke_detail : "detailed");
        setScenesPerImage(Math.max(1, Math.min(4, Number(data.scenes_per_image) || 1)));
        setAspectRatio(["16:9", "9:16", "3:4", "4:3", "1:1"].includes(data.aspect_ratio) ? data.aspect_ratio : "16:9");
        setPresentationMode(data.presentation_mode === "story-color" ? "story-color" : "whiteboard");
        setIncludeKeyText(data.include_key_text !== false);
        setIncludeSubtitles(data.include_subtitles !== false);
        if (styleOptions.some((item) => item.name === data.style)) setStyle(data.style);
        if (["custom", "standard", "infographic"].includes(data.page_mode)) setPageMode(data.page_mode);
      }
    } catch {
    } finally {
      setPreferencesLoaded(true);
    }
  }, []);
  useEffect(() => {
    if (!preferencesLoaded) return;
    const timeout = setTimeout(() => {
      localStorage.setItem(
        LOCAL_PREFERENCES_KEY,
        JSON.stringify({
          voice_mode: voiceMode,
          identity_mode: identityMode,
          pen_text: penText,
          stroke_detail: strokeDetail,
          scenes_per_image: scenesPerImage,
          aspect_ratio: aspectRatio,
          presentation_mode: presentationMode,
          include_key_text: includeKeyText,
          include_subtitles: includeSubtitles,
          style,
          page_mode: pageMode,
        }),
      );
    }, 300);
    return () => clearTimeout(timeout);
  }, [voiceMode, identityMode, penText, strokeDetail, scenesPerImage, aspectRatio, presentationMode, includeKeyText, includeSubtitles, style, pageMode, preferencesLoaded]);
  const loadHistory = async () => {
    try {
      const [jobsResponse, healthResponse] = await Promise.all([fetch(`${API}/api/jobs?limit=20`), fetch(`${API}/api/health`)]);
      if (jobsResponse.ok) {
        const items: Job[] = (await jobsResponse.json()).items || [];
        setHistory(items);
        setSharedJob(items.find((item) => item.status === "running") || items.find((item) => item.status === "queued") || null);
      }
      if (healthResponse.ok) setHealth(await healthResponse.json());
    } catch {}
  };
  const applyApprovedAssetsToBindings = (assets: CharacterAsset[]) => {
    setCharacterBindings((items) => {
      const used = new Set(items.map((item) => item.asset_id).filter(Boolean));
      let changed = false;
      const next = items.map((binding) => {
        if (binding.asset_id) return binding;
        const normalized = binding.description.replace(/\s+/g, "").trim();
        const match = assets.find((asset) => asset.status === "approved" && !used.has(asset.id) && asset.description.replace(/\s+/g, "").trim() === normalized);
        if (!match) return binding;
        used.add(match.id);
        changed = true;
        return { ...binding, asset_id: match.id, asset_label: match.label, asset_image_url: match.image_url || null };
      });
      return changed ? next : items;
    });
  };
  const loadCharacterAssets = async () => {
    try {
      const response = await fetch(`${API}/api/character-assets?style=${encodeURIComponent(style)}`);
      if (response.ok) {
        const assets: CharacterAsset[] = (await response.json()).items || [];
        setCharacterAssets(assets);
        applyApprovedAssetsToBindings(assets);
        setPendingDrawRoles((items) => {
          let changed = false;
          const next = { ...items };
          for (const [roleId, assetId] of Object.entries(items)) {
            const asset = assets.find((candidate) => candidate.id === assetId);
            if (asset && (asset.status === "error" || asset.status === "rejected")) {
              delete next[roleId];
              delete drawOriginRoles.current[assetId];
              changed = true;
            }
          }
          return changed ? next : items;
        });
      }
    } catch {}
  };
  useEffect(() => {
    setReplacementRoleId(null);
    const restored = restoredCharacterState.current;
    if (restored) {
      if (restored.copy === copy && restored.style === style) {
        setCharacterBindings(restored.bindings);
        setCharacterMatchReady(restored.ready);
        restoredCharacterState.current = null;
      }
      return;
    }
    setCharacterMatchReady(false);
    setCharacterBindings([]);
  }, [copy, style]);
  useEffect(() => setSelectedSourceAssetId(null), [style]);
  useEffect(() => {
    if (!characterLibraryOpen) return;
    loadCharacterAssets();
    const id = setInterval(loadCharacterAssets, 2200);
    return () => clearInterval(id);
  }, [characterLibraryOpen, style]);
  const hasMissingCharacters = characterBindings.some((item) => !item.asset_id);
  useEffect(() => {
    if (pageMode === "standard" && characterMatchReady && hasMissingCharacters) void loadCharacterAssets();
  }, [pageMode, characterMatchReady, hasMissingCharacters, style]);
  const matchCharacters = async () => {
    if (copy.trim().length < 10) return setMessage("请先填写至少 10 个字的文案，再分析角色");
    setCharacterBusy(true);
    setCharacterMessage("AI 正在分析文案并匹配当前画风的角色资产…");
    try {
      const response = await fetch(`${API}/api/character-matches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ copy, style }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "角色匹配失败");
      const bindings: CharacterBinding[] = payload.bindings || [];
      setCharacterBindings(bindings);
      setCharacterMatchReady(true);
      const missing = bindings.filter((item) => !item.asset_id);
      if (missing.length) {
        setCharacterMessage(`有 ${missing.length} 个角色没有合适资产；点击每张红色卡片右侧的“开始抽卡”即可直接生成。`);
      } else {
        setCharacterMessage(bindings.length ? `已匹配 ${bindings.length} 个角色；生成时会按分镜只上传实际出镜角色。` : "文案中没有需要固定形象的出镜角色，可直接生成。");
      }
    } catch (error) {
      setCharacterMessage(error instanceof Error ? error.message : "角色匹配失败");
    } finally {
      setCharacterBusy(false);
    }
  };
  const submitCharacterDraw = async (label: string, description: string, count: number, originRoleId?: string, sourceAssetId?: string) => {
    setCharacterBusy(true);
    setCharacterMessage("已提交角色抽卡，生成完成后会出现在审核区…");
    try {
      const response = await fetch(`${API}/api/character-assets/draw`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style, label, description, count, source_asset_id: sourceAssetId || undefined }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "抽卡失败");
      if (originRoleId) {
        for (const asset of payload.items || []) drawOriginRoles.current[asset.id] = originRoleId;
        const firstAsset = (payload.items || [])[0];
        if (firstAsset) setPendingDrawRoles((items) => ({ ...items, [originRoleId]: firstAsset.id }));
      }
      if (sourceAssetId) setSelectedSourceAssetId(null);
      await loadCharacterAssets();
    } catch (error) {
      setCharacterMessage(error instanceof Error ? error.message : "抽卡失败");
    } finally {
      setCharacterBusy(false);
      setDrawingRoleId(null);
    }
  };
  const drawCharacterAssets = async () => submitCharacterDraw(drawLabel, drawDescription, drawCount, undefined, selectedSourceAssetId || undefined);
  const selectCharacterDrawSource = (asset: CharacterAsset) => {
    if (!asset.image_url) return;
    if (selectedSourceAssetId === asset.id) {
      setSelectedSourceAssetId(null);
      setCharacterMessage("已取消角色图片参考；下一次抽卡只使用当前画风和文字说明。");
      return;
    }
    setSelectedSourceAssetId(asset.id);
    setDrawLabel(`${asset.label}变体`);
    setDrawDescription(asset.description);
    setCharacterMessage(`已选择“${asset.label}”作为人物参考；修改左侧说明后，可在该人物基础上生成新的角色设定图。`);
  };
  const reusableAssetLabel = (binding: CharacterBinding) => {
    const age = binding.age_group && binding.age_group !== "未知" ? binding.age_group.replace(/阶段|人群/g, "") : "";
    const gender = binding.gender === "女性" ? "女" : binding.gender === "男性" ? "男" : binding.gender !== "未知" ? binding.gender : "";
    return `${age}${gender}`.trim() || "角色候选";
  };
  const drawMissingCharacter = async (binding: CharacterBinding) => {
    const label = reusableAssetLabel(binding);
    const description = [
      binding.description,
      binding.core_personality ? `核心性格：${binding.core_personality}` : "",
      binding.facial_persona ? `固定脸相：${binding.facial_persona}` : "",
    ].filter(Boolean).join("；");
    setDrawLabel(label);
    setDrawDescription(description);
    setDrawCount(1);
    setDrawingRoleId(binding.role_id);
    setCharacterLibraryOpen(true);
    await submitCharacterDraw(label, description, 1, binding.role_id);
  };
  const handleMissingCharacterAction = (binding: CharacterBinding) => {
    if (pendingDrawRoles[binding.role_id]) {
      setCharacterLibraryOpen(true);
      void loadCharacterAssets();
      return;
    }
    void drawMissingCharacter(binding);
  };
  const openCharacterReplacement = async (binding: CharacterBinding) => {
    setReplacementRoleId(binding.role_id);
    setReplacementAssets([]);
    setReplacementError("");
    setReplacementLoading(true);
    try {
      const response = await fetch(`${API}/api/character-assets?style=${encodeURIComponent(style)}&approved_only=true`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "读取角色资产失败");
      const approvedAssets = (payload.items || []).filter((asset: CharacterAsset) => asset.status === "approved" && asset.image_url);
      if (binding.asset_id && binding.asset_image_url && !approvedAssets.some((asset: CharacterAsset) => asset.id === binding.asset_id)) {
        approvedAssets.unshift({
          id: binding.asset_id,
          style,
          label: binding.asset_label || binding.story_name,
          description: binding.description,
          status: "approved",
          image_url: binding.asset_image_url,
        });
      }
      setReplacementAssets(approvedAssets);
    } catch (error) {
      setReplacementError(error instanceof Error ? error.message : "读取角色资产失败");
    } finally {
      setReplacementLoading(false);
    }
  };
  const replaceCharacterAsset = (asset: CharacterAsset) => {
    if (!replacementRoleId) return;
    const binding = characterBindings.find((item) => item.role_id === replacementRoleId);
    setCharacterBindings((items) => items.map((item) => item.role_id === replacementRoleId ? {
      ...item,
      asset_id: asset.id,
      asset_label: asset.label,
      asset_image_url: asset.image_url || null,
      description: asset.description,
      persona_compatible: true,
      match_confidence: undefined,
      match_reason: `由你手动选择“${asset.label}”`,
    } : item));
    setCharacterMessage(`已将“${binding?.story_name || "该角色"}”更换为资产“${asset.label}”；其他人物不会改变。`);
    setReplacementRoleId(null);
  };
  const reviewCharacterAsset = async (asset: CharacterAsset, status: "approved" | "rejected") => {
    const response = await fetch(`${API}/api/character-assets/${asset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json();
    if (!response.ok) return setCharacterMessage(payload.detail || "审核失败");
    if (status === "approved") {
      const originRoleId = drawOriginRoles.current[asset.id];
      if (originRoleId) {
        setCharacterBindings((items) => items.map((binding) => binding.role_id === originRoleId ? {
          ...binding,
          asset_id: asset.id,
          asset_label: payload.label,
          asset_image_url: payload.image_url || null,
        } : binding));
        delete drawOriginRoles.current[asset.id];
        setPendingDrawRoles((items) => {
          const next = { ...items };
          delete next[originRoleId];
          return next;
        });
      } else {
        applyApprovedAssetsToBindings([{ ...asset, ...payload }]);
      }
      setCharacterMessage("已审核并自动绑定到当前任务；对应角色已从红色变为绿色。");
    } else {
      const originRoleId = drawOriginRoles.current[asset.id];
      if (originRoleId) {
        delete drawOriginRoles.current[asset.id];
        setPendingDrawRoles((items) => {
          const next = { ...items };
          delete next[originRoleId];
          return next;
        });
      }
      setCharacterMessage("已标记为不采用。");
    }
    loadCharacterAssets();
  };
  const deleteCharacterAsset = async (asset: CharacterAsset) => {
    if (!window.confirm(`确定删除角色资产“${asset.label}”吗？已提交任务中的冻结副本不会受影响。`)) return;
    const response = await fetch(`${API}/api/character-assets/${asset.id}`, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok) return setCharacterMessage(payload.detail || "删除失败");
    const originRoleId = drawOriginRoles.current[asset.id];
    if (originRoleId) {
      delete drawOriginRoles.current[asset.id];
      setPendingDrawRoles((items) => {
        const next = { ...items };
        delete next[originRoleId];
        return next;
      });
    }
    setCharacterMessage("角色资产已删除；历史任务里的冻结副本仍然保留。");
    loadCharacterAssets();
  };
  const onFile = (e: ChangeEvent<HTMLInputElement>) => setReference(e.target.files?.[0] || null);
  const updateCharacter = (id: string, patch: Partial<CharacterReference>) => setCharacters((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  const addCharacter = () =>
    setCharacters((items) =>
      items.length >= 5
        ? items
        : [
            ...items,
            {
              id: `character-${Date.now()}`,
              name: `人物 ${items.length + 1}`,
              description: "",
              files: [],
            },
          ],
    );
  const removeCharacter = (id: string) => setCharacters((items) => (items.length === 1 ? items : items.filter((item) => item.id !== id)));
  const updateService = (kind: "text" | "image", id: string, patch: Partial<ServiceNode>) =>
    setConfig((current) => {
      const key = kind === "text" ? "text_services" : "image_services";
      return {
        ...current,
        [key]: current[key].map((item) => (item.id === id ? { ...item, ...patch } : item)),
      };
    });
  const addService = (kind: "text" | "image") =>
    setConfig((current) => {
      const key = kind === "text" ? "text_services" : "image_services";
      return {
        ...current,
        [key]: [
          ...current[key],
          {
            id: `${kind}-${Date.now()}`,
            base_url: "",
            api_key: "",
            model: kind === "text" ? "gpt-5" : "gpt-image-2",
            enabled: true,
            ...(kind === "image" ? { rpm_limit: 40, rpd_limit: 600, utilization_percent: 80, max_input_images: 4 } : {}),
          },
        ],
      };
    });
  const applyCapacityPreset = (id: string, value: string) => {
    const [rpm, rpd] = value.split(":").map(Number);
    if (rpm > 0) updateService("image", id, { rpm_limit: rpm, rpd_limit: rpd });
  };
  const removeService = (kind: "text" | "image", id: string) =>
    setConfig((current) => {
      const key = kind === "text" ? "text_services" : "image_services";
      return {
        ...current,
        [key]: current[key].length === 1 ? current[key] : current[key].filter((item) => item.id !== id),
      };
    });
  const detectNodeModel = async (kind: "text" | "image", node: ServiceNode, snapshot: Config = config) => {
    const key = `${kind}-${node.id}`;
    setModelLoading((old) => ({ ...old, [key]: true }));
    try {
      const probe = {
        ...snapshot,
        base_url: node.base_url,
        api_key: node.api_key,
        text_model: kind === "text" ? node.model : "gpt-5",
        image_base_url: node.base_url,
        image_api_key: node.api_key,
        image_model: kind === "image" ? node.model : "gpt-image-2",
        text_services: [],
        image_services: [],
      };
      const response = await fetch(`${API}/api/config/models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(probe),
      });
      const data: ModelCatalog & { detail?: string } = await response.json();
      if (!response.ok) throw new Error(data.detail || "模型读取失败");
      const models = kind === "text" ? data.text_models : data.image_models;
      const selected = kind === "text" ? data.selected_text_model : data.selected_image_model;
      if (!selected) throw new Error("该节点没有返回对应类型的模型");
      setModelCatalog((old) => ({ ...old, [key]: models }));
      updateService(kind, node.id, { model: selected });
      return selected;
    } finally {
      setModelLoading((old) => ({ ...old, [key]: false }));
    }
  };
  const detectService = async (kind: "text" | "image", node: ServiceNode) => {
    const signatureKey = `${kind}:${node.id}`;
    detectedServiceSignatures.current[signatureKey] = serviceSignature(kind, node);
    setModelDetectionMessage(`正在读取${kind === "text" ? "文本" : "图片"}节点模型…`);
    try {
      const selected = await detectNodeModel(kind, node);
      setModelDetectionMessage(`节点模型已识别并更正：${selected}`);
    } catch (error) {
      setModelDetectionMessage(error instanceof Error ? error.message : "模型读取失败");
    }
  };
  const detectChangedServiceModels = async (snapshot: Config) => {
    const candidates = [
      ...snapshot.text_services.map((node, index) => ({
        kind: "text" as const,
        node,
        index,
      })),
      ...snapshot.image_services.map((node, index) => ({
        kind: "image" as const,
        node,
        index,
      })),
    ];
    for (const candidate of candidates) {
      const { kind, node, index } = candidate;
      if (!node.base_url.trim() || !node.api_key.trim()) continue;
      const signatureKey = `${kind}:${node.id}`;
      const signature = serviceSignature(kind, node);
      if (detectedServiceSignatures.current[signatureKey] === signature) continue;
      detectedServiceSignatures.current[signatureKey] = signature;
      const label = `${kind === "text" ? "文本" : "图片"}节点 ${index + 1}`;
      setModelDetectionMessage(`已自动保存，正在识别${label}模型…`);
      try {
        const selected = await detectNodeModel(kind, node, snapshot);
        setModelDetectionMessage(`${label}已自动识别并更正为 ${selected}`);
      } catch (error) {
        setModelDetectionMessage(`${label}自动识别失败：${error instanceof Error ? error.message : "模型读取失败"}`);
      }
    }
  };
  useEffect(() => {
    loadHistory();
    const id = setInterval(loadHistory, 2000);
    return () => clearInterval(id);
  }, []);
  const poll = (id: string) => {
    focusedJobId.current = id;
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      const r = await fetch(`${API}/api/jobs/${id}`);
      if (!r.ok) return;
      const next = await r.json();
      if (focusedJobId.current === id) setJob(next);
      if (["done", "error", "cancelled"].includes(next.status)) {
        if (focusedJobId.current === id && timer.current) clearInterval(timer.current);
        loadHistory();
      }
    }, 1600);
  };
  const create = async (e: FormEvent) => {
    e.preventDefault();
    setMessage("");
    if (voiceMode !== "none" && !reference) return setMessage(voiceMode === "uploaded" ? "请先上传完整旁白音频" : "请先上传一段清晰的克隆音色样本");
    if (copy.trim().length < 10) return setMessage("文案至少需要 10 个字");
    const readyCharacters = characters.filter((item) => item.name.trim() && item.files.length);
    if (pageMode === "custom" && !styleReference) return setMessage("请上传一张画面风格参考图");
    if (pageMode === "custom" && !readyCharacters.length) return setMessage("请至少添加一个带参考图片的人物");
    if (pageMode === "standard" && !characterMatchReady) return setMessage("请先点击“AI 分析并挑选角色”，确认当前文案的人物资产");
    if (pageMode === "standard" && characterBindings.some((item) => !item.asset_id)) return setMessage("仍有角色没有资产，请先到抽卡区生成、审核并重新匹配");
    const body = new FormData();
    body.append("copy", copy);
    body.append("voice_mode", voiceMode);
    body.append("identity_mode", identityMode);
    body.append("style", pageMode === "custom" ? "自定义参考" : style);
    body.append("reference_mode", pageMode);
    body.append("scenes_per_image", String(pageMode === "infographic" || presentationMode === "story-color" ? 1 : scenesPerImage));
    body.append("aspect_ratio", presentationMode === "story-color" ? "3:4" : aspectRatio);
    body.append("presentation_mode", pageMode === "infographic" ? "whiteboard" : presentationMode);
    body.append("task_name", taskName);
    body.append("pen_text", penText);
    body.append("include_key_text", String(presentationMode === "story-color" ? false : includeKeyText));
    body.append("stroke_detail", strokeDetail);
    body.append("include_subtitles", String(presentationMode === "story-color" ? true : includeSubtitles));
    if (pageMode === "standard") body.append("character_bindings", JSON.stringify(characterBindings));
    if (reference) body.append("reference", reference);
    if (pageMode === "custom" && styleReference) {
      body.append("style_reference", styleReference);
      body.append(
        "character_manifest",
        JSON.stringify(
          readyCharacters.map((item) => ({
            name: item.name.trim(),
            description: item.description.trim(),
            file_count: item.files.length,
          })),
        ),
      );
      readyCharacters.forEach((item) => item.files.forEach((file) => body.append("character_references", file)));
    }
    focusedJobId.current = "submitting";
    setJob({ id: "", status: "queued", stage: "正在提交任务", progress: 1 });
    try {
      const r = await fetch(`${API}/api/jobs`, { method: "POST", body });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "提交失败");
      setJob(data);
      loadHistory();
      poll(data.id);
    } catch (err) {
      focusedJobId.current = null;
      setJob(null);
      setMessage(err instanceof Error ? err.message : "无法连接后端");
    }
  };
  const createAnotherTask = () => {
    focusedJobId.current = null;
    if (timer.current) clearInterval(timer.current);
    setJob(null);
    setCopy("");
    setTaskName("");
    setReference(null);
    setStyleReference(null);
    setCharacters([
      {
        id: `character-${Date.now()}`,
        name: "人物 1",
        description: "",
        files: [],
      },
    ]);
    setMessage("上一任务继续在后台制作；已保留画风与成片设置，可以提交新任务");
    document.querySelector(".workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const persistConfig = async (snapshot: Config = config, origin: "auto" | "manual" = "manual", requestId = ++saveRequest.current) => {
    const payload = providerPayloadFor(snapshot);
    const fingerprint = JSON.stringify(payload);
    if (fingerprint === lastSavedConfig.current) {
      setSaveState("saved");
      setConnectionOk(true);
      setConnectionMessage(origin === "auto" ? "已自动保存" : "设置已保存");
      return;
    }
    setSaveState("saving");
    setConnectionMessage(origin === "auto" ? "正在自动保存…" : "正在保存…");
    try {
      const r = await fetch(`${API}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: fingerprint,
      });
      if (!r.ok) throw new Error();
      await r.json();
      if (requestId !== saveRequest.current) return;
      lastSavedConfig.current = fingerprint;
      setConnectionOk(true);
      setSaveState("saved");
      setConnectionMessage(origin === "auto" ? "已自动保存" : "设置已保存");
      void detectChangedServiceModels(snapshot);
    } catch {
      if (requestId !== saveRequest.current) return;
      setConnectionOk(false);
      setSaveState("error");
      setConnectionMessage("保存失败，请检查后端连接");
    }
  };
  const closeSettings = () => {
    const fingerprint = JSON.stringify(providerPayloadFor(config));
    if (configHydrated.current && fingerprint !== lastSavedConfig.current) {
      const requestId = ++saveRequest.current;
      void persistConfig(config, "auto", requestId);
    }
    setSettingsOpen(false);
  };
  useEffect(() => {
    if (!settingsOpen || !configHydrated.current) return;
    const fingerprint = JSON.stringify(providerPayloadFor(config));
    if (fingerprint === lastSavedConfig.current) return;
    const requestId = ++saveRequest.current;
    setSaveState("pending");
    setConnectionMessage("修改已记录，停止输入后自动保存");
    const timeout = setTimeout(() => {
      void persistConfig(config, "auto", requestId);
    }, 900);
    return () => clearTimeout(timeout);
  }, [config, settingsOpen]);
  useEffect(() => {
    if (!settingsOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeSettings();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [settingsOpen, config]);
  const test = async () => {
    setTesting(true);
    setConnectionMessage(voiceMode === "clone" ? "正在依次测试文本、图片和语音服务…" : "正在测试文本和图片服务…");
    setConnectionOk(null);
    try {
      const r = await fetch(`${API}/api/config/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(providerPayloadFor(config)),
      });
      if (!r.ok) throw new Error();
      const d = await r.json();
      const ok = Boolean(d.openlux?.ok && d.image?.ok && (voiceMode !== "clone" || d.tts?.ok));
      setConnectionOk(ok);
      setConnectionMessage(`${d.openlux.message}；${d.image.message}${voiceMode === "clone" ? `；${d.tts.message}` : "；当前声音模式不需要语音服务"}`);
    } catch {
      setConnectionOk(false);
      setConnectionMessage("测试失败，请确认后端已经启动");
    } finally {
      setTesting(false);
    }
  };
  const resetImageTierMemory = async (nodeId: string) => {
    if (!window.confirm("解除这个图片节点的失败档位记忆吗？当前429冷却不会被跳过。")) return;
    try {
      const response = await fetch(`${API}/api/image-nodes/${encodeURIComponent(nodeId)}/reset-rpm-memory`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "解除失败");
      setConnectionOk(true);
      setConnectionMessage(data.message);
      await loadHistory();
    } catch (error) {
      setConnectionOk(false);
      setConnectionMessage(error instanceof Error ? error.message : "解除失败");
    }
  };
  const clearImageCircuitBreaker = async (nodeId: string) => {
    if (!window.confirm("手动清除这个图片节点的熔断吗？节点会立即恢复调度；如果余额、密钥或服务故障尚未解决，下一次请求可能再次熔断。")) return;
    try {
      const response = await fetch(`${API}/api/image-nodes/${encodeURIComponent(nodeId)}/clear-circuit-breaker`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "清除失败");
      setConnectionOk(true);
      setConnectionMessage(data.message);
      await loadHistory();
    } catch (error) {
      setConnectionOk(false);
      setConnectionMessage(error instanceof Error ? error.message : "清除失败");
    }
  };
  const openRenameDialog = (source: Job) => {
    setRenameJob(source);
    setRenameDraft(source.task_name || source.id);
    setDetailActionMessage("");
  };
  const saveTaskName = async () => {
    if (!renameJob || !renameDraft.trim()) return;
    setRenaming(true);
    try {
      const response = await fetch(`${API}/api/jobs/${renameJob.id}/name`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_name: renameDraft.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "修改任务名失败");
      if (detailJob?.id === data.id) setDetailJob(data);
      if (job?.id === data.id) setJob(data);
      setRenameJob(null);
      setDetailActionMessage("任务名已保存");
      await loadHistory();
    } catch (err) {
      setDetailActionMessage(err instanceof Error ? err.message : "修改任务名失败");
    } finally {
      setRenaming(false);
    }
  };
  const openRerenderDialog = (source: Job) => {
    const version = source.next_rerender_version || (source.rerender_version || 0) + 1;
    const suffix = `+重新渲染第${version}版`;
    const base = (source.task_name || source.id).replace(/\+重新渲染第\d+版$/, "");
    setRerenderSource(source);
    setRerenderName(`${base.slice(0, Math.max(1, 30 - suffix.length))}${suffix}`);
    setMessage("");
    setDetailActionMessage("");
  };
  const submitRerender = async () => {
    if (!rerenderSource || !rerenderName.trim()) return;
    const source = rerenderSource;
    setRerendering(true);
    setMessage("");
    setDetailActionMessage("");
    try {
      const r = await fetch(`${API}/api/jobs/${source.id}/rerender`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_name: rerenderName.trim() }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "重新渲染提交失败");
      setJob(data);
      setRerenderSource(null);
      setDetailJobId(null);
      setPreviewImage(null);
      loadHistory();
      poll(data.id);
    } catch (err) {
      const text = err instanceof Error ? err.message : "重新渲染失败";
      setMessage(text);
      setDetailActionMessage(text);
    } finally {
      setRerendering(false);
    }
  };
  const retryFailed = async (source: Job) => {
    setMessage("");
    try {
      const r = await fetch(`${API}/api/jobs/${source.id}/retry`, {
        method: "POST",
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "继续任务失败");
      setJob(data);
      loadHistory();
      poll(data.id);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "继续任务失败");
    }
  };
  const cancelTask = async (source: Job) => {
    if (!window.confirm(`确定取消“${source.task_name || source.id}”吗？已完成的断点会保留。`)) return;
    setMessage("");
    try {
      const r = await fetch(`${API}/api/jobs/${source.id}/cancel`, {
        method: "POST",
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "取消失败");
      if (timer.current) clearInterval(timer.current);
      setJob(data);
      setMessage("任务已取消，已完成的断点仍保留在历史记录中");
      loadHistory();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "取消任务失败");
    }
  };
  const assetFile = async (asset: InputAsset) => {
    const response = await fetch(`${API}${asset.url}`);
    if (!response.ok) throw new Error(`无法读取历史素材：${asset.name}`);
    return new File([await response.blob()], asset.name, {
      type: asset.content_type || "application/octet-stream",
    });
  };
  const restoreParameters = async (source: Job) => {
    setRestoringJobId(source.id);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/jobs/${source.id}/parameters`);
      const data: JobParameters = await response.json();
      if (!response.ok) throw new Error((data as unknown as { detail?: string }).detail || "读取历史参数失败");
      const restoredReference = data.reference ? await assetFile(data.reference) : null;
      const restoredVoiceMode = normalizeVoiceMode(data.voice_mode);
      if (restoredVoiceMode !== "none" && !restoredReference) throw new Error("该历史任务缺少音频，不能完整复用");
      const restoredStyle = data.style_reference ? await assetFile(data.style_reference) : null;
      const restoredCharacters = await Promise.all(
        (data.characters || []).map(async (item, index) => ({
          id: `restored-${source.id}-${index}`,
          name: item.name,
          description: item.description,
          files: await Promise.all(item.images.map(assetFile)),
        })),
      );
      const restoredBindings = data.character_bindings || [];
      if (copy === data.copy && style === data.style) {
        restoredCharacterState.current = null;
        setCharacterBindings(restoredBindings);
        setCharacterMatchReady(data.reference_mode === "standard");
      } else {
        restoredCharacterState.current = {
          copy: data.copy,
          style: data.style,
          bindings: restoredBindings,
          ready: data.reference_mode === "standard",
        };
      }
      setCopy(data.copy);
      setReference(restoredReference);
      setVoiceMode(restoredVoiceMode);
      setIdentityMode(normalizeIdentityMode(data.identity_mode));
      setPageMode(data.reference_mode);
      setStyle(data.style);
      setScenesPerImage(Math.max(1, Math.min(4, data.scenes_per_image || 1)));
      setAspectRatio(["16:9", "9:16", "3:4", "4:3", "1:1"].includes(data.aspect_ratio) ? data.aspect_ratio : "16:9");
      setPresentationMode(data.presentation_mode === "story-color" ? "story-color" : "whiteboard");
      setTaskName(data.task_name);
      setPenText(data.pen_text);
      setIncludeKeyText(data.include_key_text);
      setIncludeSubtitles(data.include_subtitles);
      setStrokeDetail(data.stroke_detail);
      setStyleReference(restoredStyle);
      setCharacters(
        restoredCharacters.length
          ? restoredCharacters
          : [
              {
                id: `character-${Date.now()}`,
                name: "人物 1",
                description: "",
                files: [],
              },
            ],
      );
      focusedJobId.current = null;
      if (timer.current) clearInterval(timer.current);
      setJob(null);
      setRerenderSource(null);
      setDetailJobId(null);
      setPreviewImage(null);
      setMessage(`已将“${source.task_name || source.id}”的设置和素材填入制作页`);
      document.querySelector(".workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "复用历史任务失败");
    } finally {
      setRestoringJobId(null);
    }
  };
  const openTaskDetail = (source: Job) => {
    setDetailJob(source);
    setDetailJobId(source.id);
    setDetailParameters(null);
    setGallery([]);
    setPreviewImage(null);
    setAssetPreview(null);
    setSelectedGalleryPage(null);
    setPromptDraft("");
    setDetailActionMessage("");
    setDetailLoading(true);
  };
  const selectGalleryPrompt = (image: GalleryItem) => {
    setSelectedGalleryPage(image.page);
    setPromptDraft(image.prompt || "");
    setDetailActionMessage("");
  };
  const regenerateImage = async () => {
    if (!detailJob || selectedGalleryPage === null) return;
    setRegeneratingPage(selectedGalleryPage);
    setDetailActionMessage("");
    try {
      const response = await fetch(`${API}/api/jobs/${detailJob.id}/boards/${selectedGalleryPage}/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptDraft }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "图片重生成提交失败");
      setDetailJob(data);
      setJob(data);
      setDetailActionMessage(`第 ${selectedGalleryPage} 张图片已进入重生成队列`);
      loadHistory();
      poll(data.id);
    } catch (err) {
      setDetailActionMessage(err instanceof Error ? err.message : "图片重生成失败");
    } finally {
      setRegeneratingPage(null);
    }
  };
  useEffect(() => {
    if (!detailJobId) return;
    let active = true;
    const load = async () => {
      try {
        const [jobResponse, galleryResponse, parametersResponse] = await Promise.all([fetch(`${API}/api/jobs/${detailJobId}`), fetch(`${API}/api/jobs/${detailJobId}/gallery`), fetch(`${API}/api/jobs/${detailJobId}/parameters`)]);
        if (!jobResponse.ok || !galleryResponse.ok || !parametersResponse.ok) throw new Error();
        const [nextJob, nextGallery, nextParameters] = await Promise.all([jobResponse.json(), galleryResponse.json(), parametersResponse.json()]);
        if (active) {
          const items: GalleryItem[] = nextGallery.items || [];
          setDetailJob(nextJob);
          setGallery(items);
          setSelectedGalleryPage((current) => {
            if (current !== null && items.some((image) => image.page === current)) return current;
            const first = items[0];
            setPromptDraft(first?.prompt || "");
            return first?.page ?? null;
          });
          setDetailParameters(nextParameters);
          setDetailLoading(false);
        }
      } catch {
        if (active) setDetailLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 2200);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewImage((current) => (current ? null : current));
        setAssetPreview(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      active = false;
      clearInterval(interval);
      window.removeEventListener("keydown", onKey);
    };
  }, [detailJobId]);
  useEffect(() => {
    if (previewImage) selectGalleryPrompt(previewImage);
  }, [previewImage]);
  const shownJob = job || sharedJob;
  const selectedStyleOption = styleOptions.find((item) => item.name === style) || styleOptions[0];
  const selectedStyleRecipe = pageMode === "custom" ? "读取你上传的风格参考图，只学习配色、线条、材质、造型比例与构图语言，不复制参考图中的人物和事件。" : styleRecipes[style] || selectedStyleOption.desc;
  const selectedStyleRecipeParts = selectedStyleRecipe
    .split(/[；。]\s*/)
    .map((item) => item.trim())
    .filter(Boolean);
  const promptStructureLayers = [
    { code: "01", title: "分镜内容", text: pageMode === "infographic" ? "当前中心句、观点证据和插图元素" : `当前文案拆出的 ${presentationMode === "story-color" ? 1 : scenesPerImage} 个分镜` },
    { code: "02", title: "构图版式", text: `${presentationMode === "story-color" ? "一幕一页" : `${scenesPerImage} 幕组合`} · ${presentationMode === "story-color" ? "3:4" : aspectRatio}` },
    { code: "03", title: "人物约束", text: pageMode === "custom" ? "以人物参考图和人物描述为准" : identityModeDescriptions[identityMode] },
    { code: "04", title: "画风配方", text: pageMode === "custom" ? "从上传参考图动态提取" : `${selectedStyleRecipeParts.length} 条视觉规则` },
    { code: "05", title: "文字与禁用项", text: `${includeKeyText && pageMode !== "infographic" ? "允许一条重点短语" : "图片内不生成文字"} · 禁止复制参考图内容` },
  ];
  const showingShared = !job && !!sharedJob;
  const selectedGalleryImage = selectedGalleryPage === null ? null : gallery.find((image) => image.page === selectedGalleryPage) || null;
  const textAvailability = serviceAvailability(config.text_services);
  const imageAvailability = serviceAvailability(config.image_services);
  const replacementBinding = characterBindings.find((item) => item.role_id === replacementRoleId) || null;
  const otherBoundAssetIds = new Set(
    characterBindings.filter((item) => item.role_id !== replacementRoleId).map((item) => item.asset_id).filter(Boolean),
  );
  const selectableReplacementAssets = replacementAssets.filter((asset) => !otherBoundAssetIds.has(asset.id));
  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brandMark">
            <img src="/brand-mark.png" alt="" />
          </span>
          <span>有温度出品</span>
        </div>
        <nav className="pageSwitch" aria-label="制作页面">
          <button type="button" className={pageMode === "standard" ? "active" : ""} onClick={() => setPageMode("standard")}>
            标准制作
          </button>
          <button type="button" className={pageMode === "custom" ? "active" : ""} onClick={() => setPageMode("custom")}>
            自定义参考
          </button>
          <button type="button" className={pageMode === "infographic" ? "active infographicActive" : ""} onClick={() => setPageMode("infographic")}>
            动态信息图
          </button>
          <button type="button" onClick={() => setCharacterLibraryOpen(true)}>
            角色抽卡库
          </button>
        </nav>
        <button type="button" className="ghost" aria-haspopup="dialog" aria-expanded={settingsOpen} onClick={() => setSettingsOpen(true)}>
          ⚙ API 设置
        </button>
      </header>
      <section className={`hero ${pageMode === "infographic" ? "infographicHero" : ""}`}>
        <p className="eyebrow">{pageMode === "custom" ? "声音可选 × 文案 × 自定义视觉" : pageMode === "infographic" ? "AI 文案分析 × 动态知识卡片" : "声音可选 × 一段文案"}</p>
        <h1>{pageMode === "custom" ? "让你的画风和人物，贯穿每一幕。" : pageMode === "infographic" ? "把观点，变成会讲故事的信息图。" : "把你的表达，画成一支有节奏的白板视频。"}</h1>
        <p className="subtitle">{pageMode === "custom" ? "上传风格参考图与多个人物参考，可自由选择无旁白、克隆音色或完整旁白。" : pageMode === "infographic" ? "自动提炼章节与递进论据；有旁白时跟随真实声音，无旁白时按文案节奏呈现。" : "可选择无旁白、克隆音色或直接上传完整旁白，再自动完成分镜、插画和视频合成。"}</p>
      </section>
      {settingsOpen && (
        <div
          className="settingsOverlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeSettings();
          }}
        >
          <section className="settingsDialog panel" role="dialog" aria-modal="true" aria-label="API 设置">
            <header className="settingsModalHeader">
              <Title n="01" title="连接服务" note="密钥仅保存在本机后端" />
              <button type="button" className="settingsClose" onClick={closeSettings}>
                关闭
              </button>
            </header>
            <div className="settingsDialogBody">
              <div className="settingsGrid">
                <section className="serviceConfigGroup">
                  <header>
                    <strong>文本中转站</strong>
                    <span>
                      可调用 {textAvailability.ready}/{textAvailability.total} · 按节点顺序快速切换
                    </span>
                  </header>
                  <div className="serviceNodeList">
                    {config.text_services.map((node, index) => {
                      const key = `text-${node.id}`;
                      const choices = modelCatalog[key]?.length ? modelCatalog[key] : [node.model];
                      return (
                        <article className="serviceNode" key={node.id}>
                          <header>
                            <b>节点 {index + 1}</b>
                            <label>
                              <input
                                type="checkbox"
                                checked={node.enabled}
                                onChange={(e) =>
                                  updateService("text", node.id, {
                                    enabled: e.target.checked,
                                  })
                                }
                              />
                              启用
                            </label>
                            <button type="button" disabled={config.text_services.length === 1} onClick={() => removeService("text", node.id)}>
                              删除
                            </button>
                          </header>
                          <label>
                            接口地址
                            <input
                              value={node.base_url}
                              onChange={(e) =>
                                updateService("text", node.id, {
                                  base_url: e.target.value,
                                })
                              }
                              placeholder="https://example.com/v1"
                            />
                          </label>
                          <label>
                            API Key（明文）
                            <input
                              type="text"
                              autoComplete="off"
                              value={node.api_key}
                              onChange={(e) =>
                                updateService("text", node.id, {
                                  api_key: e.target.value,
                                })
                              }
                            />
                          </label>
                          <label>
                            模型
                            <select
                              value={node.model}
                              onChange={(e) =>
                                updateService("text", node.id, {
                                  model: e.target.value,
                                })
                              }
                            >
                              {choices.map((model) => (
                                <option key={model} value={model}>
                                  {model}
                                </option>
                              ))}
                            </select>
                          </label>
                          <button type="button" className="detectModel" disabled={modelLoading[key] || !node.base_url || !node.api_key} onClick={() => detectService("text", node)}>
                            {modelLoading[key] ? "读取中…" : "识别节点模型"}
                          </button>
                        </article>
                      );
                    })}
                    <button type="button" className="addService" onClick={() => addService("text")}>
                      ＋ 添加备用文本中转站
                    </button>
                  </div>
                </section>
                <section className="serviceConfigGroup imageService">
                  <header>
                    <strong>图片容量控制台</strong>
                    <span>
                      可调用 {imageAvailability.ready}/{imageAvailability.total} · RPM、RPD和安全余量按节点独立计算
                    </span>
                  </header>
                  <div className="globalCapacityControls">
                    <label>
                      全局最高 RPM
                      <input
                        type="number"
                        min={1}
                        max={500}
                        value={config.image_global_rpm_limit}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            image_global_rpm_limit: clampNumber(e.target.value, 1, 500, 200),
                          })
                        }
                      />
                      <small>所有图片节点每分钟提交总上限</small>
                    </label>
                    <label>
                      全局最大在途
                      <input
                        type="number"
                        min={10}
                        max={500}
                        value={config.image_global_in_flight_limit}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            image_global_in_flight_limit: clampNumber(e.target.value, 10, 500, 80),
                          })
                        }
                      />
                      <small>防止慢响应无限堆积，建议80</small>
                    </label>
                    <div className="capacityAdvice">
                      <strong>推荐：全局 200 RPM / 在途 80</strong>
                      <span>高RPM负责快速发出一批任务；长期吞吐仍受图片平均响应时间和在途上限约束。</span>
                    </div>
                  </div>
                  <div className="serviceNodeList">
                    {config.image_services.map((node, index) => {
                      const key = `image-${node.id}`;
                      const choices = modelCatalog[key]?.length ? modelCatalog[key] : [node.model];
                      const rpm = normalizeRpmLimit(node.rpm_limit);
                      const rpd = clampNumber(node.rpd_limit, 0, 100000, 0);
                      const safety = clampNumber(node.utilization_percent, 10, 100, 80);
                      const preset = imageCapacityPresets.find((item) => item.rpm === rpm && item.rpd === rpd);
                      return (
                        <article className="serviceNode imageCapacityNode" key={node.id}>
                          <header>
                            <b>节点 {index + 1}</b>
                            <em>
                              实际目标 {Math.max(1, Math.floor((rpm * safety) / 100))} RPM · 日安全额度 {rpd ? Math.floor((rpd * safety) / 100) : "不限"}
                            </em>
                            <label>
                              <input
                                type="checkbox"
                                checked={node.enabled}
                                onChange={(e) =>
                                  updateService("image", node.id, {
                                    enabled: e.target.checked,
                                  })
                                }
                              />
                              启用
                            </label>
                            <button type="button" disabled={config.image_services.length === 1} onClick={() => removeService("image", node.id)}>
                              删除
                            </button>
                          </header>
                          <label>
                            接口地址
                            <input
                              value={node.base_url}
                              onChange={(e) =>
                                updateService("image", node.id, {
                                  base_url: e.target.value,
                                })
                              }
                              placeholder="https://example.com/v1"
                            />
                          </label>
                          <label>
                            API Key（明文）
                            <input
                              type="text"
                              autoComplete="off"
                              value={node.api_key}
                              onChange={(e) =>
                                updateService("image", node.id, {
                                  api_key: e.target.value,
                                })
                              }
                            />
                          </label>
                          <label>
                            模型
                            <select
                              value={node.model}
                              onChange={(e) =>
                                updateService("image", node.id, {
                                  model: e.target.value,
                                })
                              }
                            >
                              {choices.map((model) => (
                                <option key={model} value={model}>
                                  {model}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            套餐预设
                            <select value={preset ? `${preset.rpm}:${preset.rpd}` : "0:0"} onChange={(e) => applyCapacityPreset(node.id, e.target.value)}>
                              {imageCapacityPresets.map((item) => (
                                <option key={item.label} value={`${item.rpm}:${item.rpd}`}>
                                  {item.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            标称 RPM
                            <input
                              type="number"
                              min={1}
                              max={300}
                              value={rpm}
                              onChange={(e) =>
                                updateService("image", node.id, {
                                  rpm_limit: clampNumber(e.target.value, 1, 300, 40),
                                })
                              }
                            />
                          </label>
                          <label>
                            标称 RPD
                            <input
                              type="number"
                              min={0}
                              max={100000}
                              value={rpd}
                              onChange={(e) =>
                                updateService("image", node.id, {
                                  rpd_limit: clampNumber(e.target.value, 0, 100000, 0),
                                })
                              }
                            />
                            <small>填0表示不启用本地日额度保护</small>
                          </label>
                          <label>
                            安全使用率
                            <select
                              value={safety}
                              onChange={(e) =>
                                updateService("image", node.id, {
                                  utilization_percent: Number(e.target.value),
                                })
                              }
                            >
                              <option value={60}>60%（最稳）</option>
                              <option value={70}>70%</option>
                              <option value={80}>80%（推荐）</option>
                              <option value={90}>90%</option>
                              <option value={100}>100%（贴线）</option>
                            </select>
                          </label>
                          <label>
                            单次参考图上限
                            <input
                              type="number"
                              min={1}
                              max={32}
                              value={clampNumber(node.max_input_images, 1, 32, 4)}
                              onChange={(e) => updateService("image", node.id, { max_input_images: clampNumber(e.target.value, 1, 32, 4) })}
                            />
                            <small>接口实测容量；未检测节点保守按 4 张</small>
                          </label>
                          <button type="button" className="detectModel" disabled={modelLoading[key] || !node.base_url || !node.api_key} onClick={() => detectService("image", node)}>
                            {modelLoading[key] ? "读取中…" : "识别节点模型"}
                          </button>
                        </article>
                      );
                    })}
                    <button type="button" className="addService" onClick={() => addService("image")}>
                      ＋ 添加备用图片中转站
                    </button>
                  </div>
                </section>
                <section className="serviceConfigGroup voiceService">
                  <header>
                    <strong>语音服务</strong>
                    <span>仅“克隆音色”模式需要配置</span>
                  </header>
                  <div>
                    <label>
                      接口类型
                      <select value={config.tts_mode} onChange={(e) => setConfig({ ...config, tts_mode: e.target.value })}>
                        <option value="gradio">IndexTTS Gradio（7860）</option>
                        <option value="fastapi">IndexTTS API（8000）</option>
                      </select>
                    </label>
                    <label>
                      语音节点 1
                      <input value={config.tts_url} onChange={(e) => setConfig({ ...config, tts_url: e.target.value })} />
                    </label>
                    <label>
                      语音节点 2（可选）
                      <input value={config.tts_url_2} onChange={(e) => setConfig({ ...config, tts_url_2: e.target.value })} placeholder="留空则仅使用节点 1" />
                    </label>
                  </div>
                </section>
              </div>
              {modelDetectionMessage && <p className="modelDetection success">{modelDetectionMessage}</p>}
              {health && (
                <div className="serviceSummary">
                  <strong>本地多任务流水线</strong>
                  <span>
                    语音 {health.queues.voice.concurrency} 路 · 文案 {health.queues.model.concurrency} 路 · 图片 {health.queues.image.max_rpm !== undefined ? `初始 ${health.queues.image.default_rpm} RPM/节点 · 单节点最高 ${health.queues.image.max_rpm} · 全局最高 ${health.queues.image.global_rpm_limit} RPM · 在途 ${health.queues.image.global_in_flight}/${health.queues.image.global_in_flight_limit} · 等待 ${health.queues.image.waiting}` : health.queues.image.default_rpm !== undefined ? `固定 ${health.queues.image.default_rpm} RPM（任务结束后升级自适应调度）` : `${health.queues.image.default_concurrency} 路并发（后端重启后切换自适应 RPM）`} · 本地渲染 {health.queues.render.concurrency} 个任务
                  </span>
                  <div>
                    {health.queues.voice.nodes.map((node) => (
                      <i key={`voice-${node.index}`} className={node.active ? "busy" : "idle"}>
                        语音节点 {node.index} · {node.active ? "工作中" : "空闲"}
                      </i>
                    ))}
                    {health.queues.image.nodes.map((node, index) => (
                      <i key={`${node.node_id}-${node.base_url}`} className={node.cooldown_seconds > 0 || node.runtime_rpm_capped || Number(node.tier_lock_seconds) > 0 ? "busy" : "idle"}>
                        图片节点 {index + 1} · {node.rpm_limit !== undefined ? `${node.rpm}/${node.effective_rpm_limit ?? node.rpm_limit}/${node.rpm_limit} RPM（当前/运行/配置） · 在途 ${node.in_flight}/${node.in_flight_limit} · ${imageCircuitLabel(node.circuit_reason)}${node.cooldown_seconds > 0 ? ` ${Math.ceil(node.cooldown_seconds)}秒` : ""}${node.runtime_rpm_capped ? ` · 已封顶${node.effective_rpm_limit ?? node.rpm} RPM至重启` : Number(node.tier_lock_seconds) > 0 ? ` · 高档锁定 ${Math.ceil(Number(node.tier_lock_seconds) / 60)}分钟` : node.recovery_mode ? ` · 恢复观察 ${node.promotion_required_successes}张/${Math.ceil(Number(node.promotion_required_seconds) / 60)}分钟` : ""} · 下次 ${Math.ceil(node.next_request_seconds || 0)}秒` : node.rpm !== undefined ? `${node.rpm} RPM · 在途 ${node.in_flight}` : `${node.concurrency} 路并发`} · 429 {node.rate_limit_count} 次 · 均耗 {node.average_latency.toFixed(1)} 秒 · 今日请求 {node.daily_used ?? 0}/{node.daily_budget ? node.daily_budget : "不限"}
                        {node.daily_exhausted ? "（额度已用尽）" : ""}
                        {node.cooldown_seconds > 0 && (
                          <button type="button" className="resetTierMemory clearCircuitBreaker" onClick={() => clearImageCircuitBreaker(node.node_id)}>
                            清除熔断
                          </button>
                        )}
                        {(node.runtime_rpm_capped || Number(node.tier_lock_seconds) > 0 || node.recovery_mode) && (
                          <button type="button" className="resetTierMemory" onClick={() => resetImageTierMemory(node.node_id)}>
                            解除档位记忆
                          </button>
                        )}
                      </i>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <footer className="settingsDialogFooter">
              <div className={`autoSaveStatus ${saveState}`}>
                <i />
                <span>{saveState === "pending" ? "等待输入结束" : saveState === "saving" ? "正在保存…" : saveState === "saved" ? "已自动保存" : saveState === "error" ? "保存失败" : "修改后自动保存"}</span>
              </div>
              <div className="actions">
                <button type="button" className="secondary" onClick={test} disabled={testing || Object.values(modelLoading).some(Boolean)}>
                  {testing ? "测试中…" : "测试连接"}
                </button>
                <button type="button" className="primary small" onClick={() => void persistConfig(config, "manual")}>
                  立即保存
                </button>
              </div>
            </footer>
            {connectionMessage && (
              <div className={`configSaveToast ${connectionOk === true ? "success" : connectionOk === false ? "error" : ""}`} role="status">
                {connectionMessage}
              </div>
            )}
          </section>
        </div>
      )}
      {characterLibraryOpen && (
        <div className="settingsOverlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setCharacterLibraryOpen(false)}>
          <section className="characterLibraryDialog panel" role="dialog" aria-modal="true" aria-label="角色抽卡资产库">
            <header className="settingsModalHeader">
              <Title n="角色" title="公共角色抽卡库" note="独立于任务 · 按画面风格长期复用" />
              <button type="button" className="settingsClose" onClick={() => setCharacterLibraryOpen(false)}>返回制作</button>
            </header>
            <div className="characterLibraryBody">
              <section className="characterDrawPanel">
                <label>角色所属画风<select value={style} onChange={(e) => setStyle(e.target.value)}>{styleOptions.map((item) => <option key={item.name}>{item.name}</option>)}</select></label>
                <label>资产名称<input value={drawLabel} maxLength={30} onChange={(e) => setDrawLabel(e.target.value)} placeholder="例如：青年母亲候选" /></label>
                <label>详细外观说明<textarea value={drawDescription} maxLength={300} onChange={(e) => setDrawDescription(e.target.value)} placeholder="年龄、脸型、眼睛、发型发色、体型、服装和标志特征" /></label>
                <label>候选数量<select value={drawCount} onChange={(e) => setDrawCount(Number(e.target.value))}><option value={1}>1 张</option><option value={2}>2 张</option><option value={3}>3 张</option><option value={4}>4 张</option></select></label>
                {selectedSourceAssetId && <div className="selectedDrawSource">基于此角色继续抽卡：<strong>{characterAssets.find((asset) => asset.id === selectedSourceAssetId)?.label || "已选角色"}</strong><button type="button" onClick={() => setSelectedSourceAssetId(null)}>取消</button></div>}
                <button type="button" className="primary" disabled={characterBusy || drawDescription.trim().length < 4} onClick={drawCharacterAssets}>{characterBusy ? "处理中…" : selectedSourceAssetId ? "基于此角色继续抽卡" : "开始针对性抽卡"}</button>
                <p>每张候选图包含同一角色的正面、四分之三侧面、纯侧面和全身视图；审核通过后才进入公共资产库。</p>
              </section>
              <section className="characterAssetGrid">
                {characterAssets.length ? characterAssets.map((asset) => (
                  <article key={asset.id} className={`characterAssetCard ${asset.status} ${asset.image_url ? "selectable" : ""} ${selectedSourceAssetId === asset.id ? "selected" : ""}`} onClick={() => selectCharacterDrawSource(asset)} onKeyDown={(event) => { if (asset.image_url && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); selectCharacterDrawSource(asset); } }} role={asset.image_url ? "button" : undefined} tabIndex={asset.image_url ? 0 : undefined} aria-pressed={asset.image_url ? selectedSourceAssetId === asset.id : undefined}>
                    {asset.image_url ? <img src={`${API}${asset.image_url}`} alt={`${asset.label}角色设定图`} /> : <div className="characterAssetWaiting">{asset.status === "error" ? "生成失败" : "正在生成角色设定图…"}</div>}
                    <strong>{asset.label}</strong>
                    <span>{asset.description}</span>
                    <small>{asset.status === "approved" ? "已审核，可被任务匹配" : asset.status === "review" ? "待你审核" : asset.status === "error" ? asset.error : "生成队列中"}</small>
                    {selectedSourceAssetId === asset.id && <small className="selectedSourceHint">已选为新设定图的人物参考</small>}
                    <div onClick={(event) => event.stopPropagation()}>
                      {asset.status === "review" && <><button type="button" className="approveAsset" onClick={() => reviewCharacterAsset(asset, "approved")}>审核并保存</button><button type="button" onClick={() => reviewCharacterAsset(asset, "rejected")}>不采用</button></>}
                      {asset.status === "approved" && <button type="button" onClick={() => reviewCharacterAsset(asset, "rejected")}>停用</button>}
                      {asset.status === "rejected" && <button type="button" className="approveAsset" onClick={() => reviewCharacterAsset(asset, "approved")}>重新启用</button>}
                      {asset.status !== "queued" && <button type="button" onClick={() => deleteCharacterAsset(asset)}>删除</button>}
                    </div>
                  </article>
                )) : <div className="characterAssetEmpty">当前画风还没有角色资产。填写左侧外观说明开始抽卡。</div>}
              </section>
            </div>
            {characterMessage && <div className="characterMessage">{characterMessage}</div>}
          </section>
        </div>
      )}
      {replacementBinding && (
        <div className="settingsOverlay roleAssetPickerOverlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setReplacementRoleId(null)}>
          <section className="roleAssetPickerDialog panel" role="dialog" aria-modal="true" aria-label={`更换角色：${replacementBinding.story_name}`}>
            <header className="settingsModalHeader">
              <div>
                <span>人物资产</span>
                <h2>为“{replacementBinding.story_name}”选择替换角色</h2>
                <p>仅更换角色设定图；故事身份、性格、分镜和其他人物保持不变。</p>
              </div>
              <button type="button" className="settingsClose" onClick={() => setReplacementRoleId(null)}>取消更换</button>
            </header>
            <div className="roleAssetPickerGrid">
              {replacementLoading && <div className="roleAssetPickerEmpty">正在读取“{style}”的已审核角色…</div>}
              {!replacementLoading && replacementError && <div className="roleAssetPickerEmpty error">{replacementError}</div>}
              {!replacementLoading && !replacementError && selectableReplacementAssets.map((asset) => {
                const current = asset.id === replacementBinding.asset_id;
                return (
                  <article key={asset.id} className={`roleAssetChoice ${current ? "current" : ""}`}>
                    <img src={`${API}${asset.image_url}`} alt={`${asset.label}角色设定图`} />
                    <div>
                      <strong>{asset.label}</strong>
                      <p>{asset.description}</p>
                    </div>
                    <button type="button" disabled={current} onClick={() => replaceCharacterAsset(asset)}>
                      {current ? "当前使用" : "选择此角色"}
                    </button>
                  </article>
                );
              })}
              {!replacementLoading && !replacementError && selectableReplacementAssets.length === 0 && (
                <div className="roleAssetPickerEmpty">当前画风没有其他可用角色，请先到角色抽卡库生成并审核。</div>
              )}
            </div>
          </section>
        </div>
      )}
      <form className="workspace" onSubmit={create}>
        <section className="panel inputPanel">
          <Title n="01" title="提供素材" note={voiceMode === "none" ? "只填文案即可" : "选择声音并填写文案"} />
          <div className="voiceModePicker">
            <button
              type="button"
              className={voiceMode === "none" ? "active" : ""}
              onClick={() => {
                setVoiceMode("none");
                setReference(null);
              }}
            >
              <strong>无旁白</strong>
              <small>无需上传音频，按文案长度自动安排画面节奏</small>
            </button>
            <button
              type="button"
              className={voiceMode === "clone" ? "active" : ""}
              onClick={() => {
                setVoiceMode("clone");
                setReference(null);
              }}
            >
              <strong>克隆音色</strong>
              <small>上传 10–30 秒声音样本，由系统朗读文案</small>
            </button>
            <button
              type="button"
              className={voiceMode === "uploaded" ? "active" : ""}
              onClick={() => {
                setVoiceMode("uploaded");
                setReference(null);
              }}
            >
              <strong>直接使用旁白</strong>
              <small>上传与文案一致的完整录音，不调用语音克隆</small>
            </button>
          </div>
          {voiceMode === "none" ? (
            <section className="noNarrationNotice">
              <strong>不需要旁白音频</strong>
              <span>分镜仍按完整文案的语义和叙事顺序智能规划，与“直接使用旁白”相同；系统只用内部静音轨补足成片时长。</span>
            </section>
          ) : (
            <>
              <label className={`dropzone ${reference ? "ready" : ""}`}>
                <input type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg" onChange={onFile} />
                <span className="uploadIcon">⌁</span>
                <strong>{reference ? reference.name : voiceMode === "uploaded" ? "上传完整旁白音频" : "上传克隆音色样本"}</strong>
                <small>{reference ? `${(reference.size / 1024 / 1024).toFixed(1)} MB · 点击这里可重新选择` : voiceMode === "uploaded" ? "录音内容应与下方文案一致，画面将跟随这段声音的时长" : "建议 10–30 秒，单人、无噪声、WAV 最佳"}</small>
              </label>
              {reference && <AudioFilePreview file={reference} />}
            </>
          )}
          <label className="copyLabel">
            <span>视频文案</span>
            <em>{copy.length} 字</em>
          </label>
          <textarea value={copy} onChange={(e) => setCopy(e.target.value)} placeholder="粘贴你想讲的内容。系统会按口播节奏自动拆分场景……" />
          {pageMode === "infographic" ? (
            <>
              <section className="infographicIntro">
                <div className="infographicPreview">
                  <span>文章结构</span>
                  <strong>大纲 → 章节 → 论证</strong>
                  <i>01</i>
                  <p>先理解全文，再决定是否需要总览页</p>
                  <i>02</i>
                  <p>章节标题持续保留，内部可有多页</p>
                  <i>03</i>
                  <p>语义进入下一部分时才切换章节</p>
                </div>
                <div>
                  <b>通用内容架构</b>
                  <h3>动态信息图解说</h3>
                  <p>根据文案选择总览、流程、对比、层级、因果、循环、时间线、中心聚焦或总结版式，不再固定三张卡片。</p>
                  <ul>
                    <li>画面文字保持短小，不放大段解释</li>
                    <li>插画自然融入构图，并带独立入场动画</li>
                    <li>完全不显示画手，字幕可以在成片设置中开关</li>
                  </ul>
                </div>
              </section>
              <div className="styleHeading">
                <strong>画面风格</strong>
                <span>与标准制作共用同一套风格，可自由选择</span>
              </div>
              <div className="stylePicker">
                {styleOptions.map((item) => (
                  <button type="button" key={item.name} className={`styleCard ${item.badge ? "featured" : ""} ${style === item.name ? "selected" : ""}`} onClick={() => setStyle(item.name)} aria-pressed={style === item.name}>
                    <span className="stylePreview">
                      <img src={item.image} alt={`${item.name}预览`} />
                      {item.badge && item.badge !== "Skill" && <em>{item.badge}</em>}
                      <i>{style === item.name ? "✓ 已选择" : "选择"}</i>
                    </span>
                    <strong>{item.name}</strong>
                    <small>{item.desc}</small>
                  </button>
                ))}
              </div>
            </>
          ) : pageMode === "standard" ? (
            <>
              <div className="styleHeading">
                <strong>画面风格</strong>
                <span>点击预览图选择，生成结果会严格遵循对应视觉配方</span>
              </div>
              <div className="stylePicker">
                {styleOptions.map((item) => (
                  <button type="button" key={item.name} className={`styleCard ${item.badge ? "featured" : ""} ${style === item.name ? "selected" : ""}`} onClick={() => setStyle(item.name)} aria-pressed={style === item.name}>
                    <span className="stylePreview">
                      <img src={item.image} alt={`${item.name}预览`} />
                      {item.badge && item.badge !== "Skill" && <em>{item.badge}</em>}
                      <i>{style === item.name ? "✓ 已选择" : "选择"}</i>
                    </span>
                    <strong>{item.name}</strong>
                    <small>{item.desc}</small>
                  </button>
                ))}
              </div>
            </>
          ) : (
            <section className="referenceBuilder">
              <div className="styleHeading">
                <strong>自定义参考</strong>
                <span>风格图控制画风，人物组控制角色一致性</span>
              </div>
              <label className={`visualDrop ${styleReference ? "ready" : ""}`}>
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setStyleReference(e.target.files?.[0] || null)} />
                <span>风格参考图</span>
                <strong>{styleReference ? styleReference.name : "点击上传一张风格图"}</strong>
                <small>只参考配色、线条、材质与构图，不复制其中人物</small>
              </label>
              <div className="characterHeading">
                <div>
                  <strong>人物参考</strong>
                  <span>每个人物可上传 1–3 张不同角度图片</span>
                </div>
                <button type="button" onClick={addCharacter} disabled={characters.length >= 5}>
                  ＋ 添加人物
                </button>
              </div>
              <div className="characterList">
                {characters.map((item, index) => (
                  <article className="characterCard" key={item.id}>
                    <div className="characterTop">
                      <b>人物 {index + 1}</b>
                      <button type="button" onClick={() => removeCharacter(item.id)} disabled={characters.length === 1}>
                        删除
                      </button>
                    </div>
                    <div className="characterFields">
                      <label>
                        人物名称
                        <input maxLength={20} value={item.name} onChange={(e) => updateCharacter(item.id, { name: e.target.value })} placeholder="例如：小昌" />
                      </label>
                      <label>
                        身份或外观说明
                        <input
                          maxLength={80}
                          value={item.description}
                          onChange={(e) =>
                            updateCharacter(item.id, {
                              description: e.target.value,
                            })
                          }
                          placeholder="例如：短发青年，黑色外套"
                        />
                      </label>
                    </div>
                    <label className={`characterUpload ${item.files.length ? "ready" : ""}`}>
                      <input
                        type="file"
                        multiple
                        accept="image/png,image/jpeg,image/webp"
                        onChange={(e) =>
                          updateCharacter(item.id, {
                            files: Array.from(e.target.files || []).slice(0, 3),
                          })
                        }
                      />
                      <strong>{item.files.length ? `已选择 ${item.files.length} 张参考图` : "上传人物参考图"}</strong>
                      <small>{item.files.length ? item.files.map((file) => file.name).join("、") : "推荐正面、侧面、全身照，最多 3 张"}</small>
                    </label>
                  </article>
                ))}
              </div>
              <p className="referenceTip">最多添加 5 个人物。系统会按人物名称与文案关系，决定每个分镜出现谁。</p>
            </section>
          )}
          {pageMode === "custom" && (styleReference || characters.some((item) => item.files.length)) && (
            <section className="referenceMediaPreview">
              <div className="referencePreviewHeading">
                <strong>已选择的参考素材</strong>
                <span>点击图片放大查看，复用历史任务后也可正常打开</span>
              </div>
              {styleReference && (
                <article>
                  <div>
                    <b>风格参考图</b>
                    <small>{styleReference.name}</small>
                  </div>
                  <FileThumbnail file={styleReference} label="放大风格参考图" onOpen={() => setInputPreviewFile(styleReference)} />
                  <label className="replaceUpload">
                    重新选择
                    <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setStyleReference(e.target.files?.[0] || null)} />
                  </label>
                </article>
              )}
              {characters
                .filter((item) => item.files.length)
                .map((item) => (
                  <article key={`preview-${item.id}`}>
                    <div>
                      <b>{item.name || "未命名人物"}</b>
                      <small>{item.files.length} 张人物参考图</small>
                    </div>
                    <div className="referenceThumbs">
                      {item.files.map((file, index) => (
                        <FileThumbnail key={`${file.name}-${index}`} file={file} label={`放大${item.name}参考图 ${index + 1}`} onOpen={() => setInputPreviewFile(file)} />
                      ))}
                    </div>
                    <label className="replaceUpload">
                      重新选择 1–3 张
                      <input
                        type="file"
                        multiple
                        accept="image/png,image/jpeg,image/webp"
                        onChange={(e) =>
                          updateCharacter(item.id, {
                            files: Array.from(e.target.files || []).slice(0, 3),
                          })
                        }
                      />
                    </label>
                  </article>
                ))}
            </section>
          )}
        </section>
        <div className="rightStack">
          {pageMode === "standard" && (
            <section className="panel taskCharacterMatcher">
              <div><strong>本任务角色资产</strong><span>AI 只匹配“{style}”的已审核角色；每个分镜只上传本幕实际出镜人物。</span></div>
              <div className="taskCharacterActions">
                <button type="button" className="secondary" disabled={characterBusy || copy.trim().length < 10} onClick={matchCharacters}>{characterBusy ? "分析中…" : characterMatchReady ? "重新分析并匹配" : "AI 分析并挑选角色"}</button>
                <button type="button" className="secondary" onClick={() => setCharacterLibraryOpen(true)}>打开角色抽卡库</button>
              </div>
              {characterBindings.length > 0 && (
                <div className="taskCharacterBindings">
                  {characterBindings.map((binding) => (
                    <article key={binding.role_id} className={binding.asset_id ? "matched" : "missing"}>
                      {binding.asset_image_url ? <img src={`${API}${binding.asset_image_url}`} alt="" /> : <span>缺</span>}
                      <div>
                        <b>{binding.story_name}</b>
                        {binding.asset_label && <small className="assetMatchName">已使用资产：{binding.asset_label}</small>}
                        <small>{binding.age_group} · {binding.gender}</small>
                        {binding.core_personality && <small>核心性格：{binding.core_personality}</small>}
                        {binding.facial_persona && <small>固定脸相：{binding.facial_persona}</small>}
                        <p>{binding.description}</p>
                        {binding.match_reason && <small>{binding.asset_id ? "匹配理由" : "未匹配原因"}：{binding.match_reason}</small>}
                      </div>
                      {binding.asset_id ? (
                        <div className="bindingStatusActions">
                          <em>匹配</em>
                          <button type="button" className="replaceBoundRole" onClick={() => void openCharacterReplacement(binding)}>更换该角色</button>
                        </div>
                      ) : (
                        <button type="button" className="drawMissingRole" disabled={drawingRoleId === binding.role_id} onClick={() => handleMissingCharacterAction(binding)}>
                          {drawingRoleId === binding.role_id ? "提交中…" : pendingDrawRoles[binding.role_id] ? "开始审核" : "开始抽卡"}
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              )}
              {characterMessage && <p className="characterMessage">{characterMessage}</p>}
            </section>
          )}
          <section className="panel controlPanel">
            <div className="controlCaption">
              <strong>成片设置</strong>
              <span>仅保存在当前电脑浏览器</span>
            </div>
            <label className="taskNameField">
              任务名
              <input maxLength={30} value={taskName} onChange={(e) => setTaskName(e.target.value)} placeholder="留空则自动使用文案前 15 个字" />
              <small>
                历史记录显示：
                {taskName.trim() || copy.replace(/\s+/g, "").slice(0, 15) || "等待输入文案"}
              </small>
            </label>
            <label className="taskNameField">
              画面比例
              <select value={presentationMode === "story-color" ? "3:4" : aspectRatio} disabled={presentationMode === "story-color"} onChange={(e) => setAspectRatio(e.target.value)}>
                <option value="16:9">16:9 · 横屏 / B站 / YouTube</option>
                <option value="9:16">9:16 · 抖音 / 视频号 / Shorts</option>
                <option value="3:4">3:4 · 演示视频原始比例</option>
                <option value="4:3">4:3 · 传统横图 / 公众号</option>
                <option value="1:1">1:1 · 方形动态 / 通用贴文</option>
              </select>
              <small>{presentationMode === "story-color" ? "该模式固定复刻 1080×1440 竖屏" : "图片、动画和最终视频都会使用 " + aspectRatio}</small>
            </label>
            {pageMode !== "custom" && (
              <div className="renderSetting compact identitySetting">
                <div>
                  <strong>人物身份</strong>
                  <span>{identityModeDescriptions[identityMode]}</span>
                </div>
                <select value={identityMode} onChange={(e) => setIdentityMode(normalizeIdentityMode(e.target.value))}>
                  <option value="consistent">身份一致（默认）</option>
                  <option value="male">默认男主角</option>
                  <option value="female">默认女主角</option>
                </select>
              </div>
            )}
            {pageMode === "infographic" ? (
              <div className="infographicSettings">
                <div>
                  <strong>语义时间轴</strong>
                  <span>每个元素绑定真实旁白，讲到才出现</span>
                </div>
                <div>
                  <strong>智能结构</strong>
                  <span>自动选择对比、时间轴、层级、因果、案例或总结</span>
                </div>
                <div>
                  <strong>文字安全</strong>
                  <span>标题与论点由程序排版，不让图片模型生成中文</span>
                </div>
              </div>
            ) : (
              <div className="styleRow">
                {presentationMode === "story-color" ? (
                  <label>
                    分镜版式
                    <select value={1} disabled>
                      <option value={1}>一幕一页（演示视频版式）</option>
                    </select>
                  </label>
                ) : (
                  <label>
                    每张图包含几个分镜
                    <select value={scenesPerImage} onChange={(e) => setScenesPerImage(Number(e.target.value))}>
                      <option value={1}>1 个分镜（画面最大）</option>
                      <option value={2}>2 个分镜（推荐）</option>
                      <option value={3}>3 个分镜</option>
                      <option value={4}>4 个分镜（最省图片）</option>
                    </select>
                  </label>
                )}
                <div className="estimate">
                  <span>文案结构 · 图片上限</span>
                  <strong>
                    约 {Math.max(1, Math.round(estimateMinutes(copy)))} 分钟 · 最多 {Math.ceil(estimateSceneCount(copy) / (presentationMode === "story-color" ? 1 : scenesPerImage))} 张
                  </strong>
                </div>
              </div>
            )}
            {pageMode !== "infographic" && presentationMode !== "story-color" && (
              <label className="subtitleToggle">
                <input type="checkbox" checked={includeKeyText} onChange={(e) => setIncludeKeyText(e.target.checked)} />
                <span>
                  <strong>画面重点文字</strong>
                  <small>{includeKeyText ? "每个分镜显示一条重点短语" : "只保留插画，不添加重点词"}</small>
                </span>
              </label>
            )}
            <label className="subtitleToggle">
              <input type="checkbox" checked={includeSubtitles} onChange={(e) => setIncludeSubtitles(e.target.checked)} />
              <span>
                <strong>生成字幕</strong>
                <small>{includeSubtitles ? "成片会烧录中文字幕" : "只保留画面和配音"}</small>
              </span>
            </label>
            {pageMode !== "infographic" && (
              <div className="renderSetting compact">
                <div>
                  <strong>动画呈现方式</strong>
                  <span>{presentationMode === "story-color" ? "无画手：文字 → 整体黑白图层 → 彩色图层" : "沿画面轮廓逐步显现并上色"}</span>
                </div>
                <select
                  value={presentationMode}
                  onChange={(e) => {
                    const mode = e.target.value as "whiteboard" | "story-color";
                    setPresentationMode(mode);
                    if (mode === "story-color") setAspectRatio("3:4");
                  }}
                >
                  <option value="whiteboard">白板手绘揭示</option>
                  <option value="story-color">故事绘本 · 分层揭示（无画手）</option>
                </select>
              </div>
            )}
            {pageMode !== "infographic" && presentationMode === "whiteboard" && (
              <div className="renderSetting compact">
                <div>
                  <strong>线条绘制量</strong>
                  <span>控制白板模式逐步显现的轮廓数量</span>
                </div>
                <select value={strokeDetail} onChange={(e) => setStrokeDetail(e.target.value)}>
                  <option value="light">精简 · 24 条</option>
                  <option value="standard">标准 · 48 条</option>
                  <option value="detailed">丰富 · 96 条（推荐）</option>
                  <option value="full">完整 · 全部线条</option>
                </select>
              </div>
            )}
            <button className="primary create" disabled={!!job && !["done", "error", "cancelled"].includes(job.status)}>
              {job && !["done", "error", "cancelled"].includes(job.status) ? "正在制作…" : "开始生成视频 →"}
            </button>
            {message && <p className={`message ${message.startsWith("已复现") || message.startsWith("任务已取消") ? "successMessage" : ""}`}>{message}</p>}
          </section>
          <aside className="panel resultPanel">
            <Title n="02" title="制作进度" note="自动完成全部步骤" />
            {!shownJob ? (
              <div className="emptyState">
                <div className="paper">
                  <i />
                  <i />
                  <i />
                </div>
                <h3>视频将在这里出现</h3>
                <p>{voiceMode === "none" ? "填写文案后即可开始生成。" : "上传声音与文案，然后点击开始生成。"}</p>
              </div>
            ) : (
              <div className="jobState">
                {showingShared && (
                  <p className="sharedTask">
                    <span>后台任务</span>
                    <strong>{shownJob.client_ip || "本机"}</strong>
                  </p>
                )}
                <div className={`statusOrb ${shownJob.status}`}>
                  <span>{shownJob.status === "done" ? "✓" : shownJob.status === "error" ? "!" : shownJob.status === "cancelled" ? "×" : "✦"}</span>
                </div>
                <h3>{shownJob.stage}</h3>
                <div className="progress">
                  <i style={{ width: `${shownJob.progress}%` }} />
                </div>
                <p>
                  {shownJob.progress}%{shownJob.scenes ? ` · ${shownJob.scenes} 幕${shownJob.boards ? ` / ${shownJob.boards} 张图` : ""} · ${shownJob.duration?.toFixed(1)} 秒` : ""}
                </p>
                <div className="timingPanel">
                  <div className="timingTotal">
                    <span>总耗时</span>
                    <strong>{formatDuration(shownJob.total_elapsed || 0)}</strong>
                    {shownJob.status === "running" && <em>当前环节 {formatDuration(shownJob.current_elapsed || 0)}</em>}
                  </div>
                  {shownJob.timings &&
                    Object.entries(shownJob.timings).map(([key, item]) => (
                      <div className={`timingRow ${item.running ? "running" : ""}`} key={key}>
                        <span>
                          {item.running ? "● " : "✓ "}
                          {item.label}
                        </span>
                        <strong>{formatDuration(item.seconds)}</strong>
                      </div>
                    ))}
                </div>
                {shownJob.error && <pre>{shownJob.error}</pre>}
                {Boolean(shownJob.image_count) && (
                  <button type="button" className="galleryButton" onClick={() => openTaskDetail(shownJob)}>
                    查看已生成的 {shownJob.image_count} 张图片
                  </button>
                )}
                {shownJob.status === "done" && hasPendingRerender(shownJob) && (
                  <button type="button" className="rerenderProgressButton" onClick={() => openRerenderDialog(shownJob)}>
                    重新渲染成片
                  </button>
                )}
                {shownJob.can_cancel && (
                  <button type="button" className="cancelButton" onClick={() => cancelTask(shownJob)}>
                    取消任务
                  </button>
                )}
                {shownJob.can_cancel && job && (
                  <button type="button" className="newTaskButton" onClick={createAnotherTask}>
                    创建新的任务
                  </button>
                )}
                {shownJob.status === "error" && shownJob.can_retry && (
                  <button type="button" className="retryButton" onClick={() => retryFailed(shownJob)}>
                    重试并继续任务
                  </button>
                )}
                {shownJob.status === "done" && shownJob.result_url && !hasPendingRerender(shownJob) && (
                  <>
                    <video controls src={`${API}${shownJob.result_url}`} />
                    <a className="download" href={`${API}${shownJob.result_url}`}>
                      下载 MP4
                    </a>
                  </>
                )}
              </div>
            )}
            {pageMode === "infographic" ? (
              <ol className="steps infographicSteps">
                <li>{voiceMode === "none" ? "建立视频节奏" : voiceMode === "uploaded" ? "处理完整旁白" : "克隆参考音色"}</li>
                <li>生成短语时间表</li>
                <li>梳理中心句与关键词</li>
                <li>制作 Remotion PPT</li>
                <li>按 PPT 生成插图</li>
                <li>合成音画成片</li>
              </ol>
            ) : (
              <ol className="steps">
                <li>{voiceMode === "none" ? "建立视频节奏" : voiceMode === "uploaded" ? "处理完整旁白" : "克隆参考音色"}</li>
                <li>拆分文案分镜</li>
                <li>生成统一插画</li>
                <li>绘制白板动画</li>
                <li>合成音画成片</li>
              </ol>
            )}
          </aside>
          <aside className="panel stylePromptPanel" aria-live="polite">
            <header className="stylePromptHeader">
              <div>
                <span>画风提示词结构</span>
                <h3>{pageMode === "custom" ? "自定义参考" : selectedStyleOption.name}</h3>
              </div>
              {pageMode !== "custom" && <img src={selectedStyleOption.image} alt="" />}
            </header>
            <p className="stylePromptLead">
              单击左侧任意画风即可切换。这里展示图片请求真正采用的结构，分镜内容会在生成时自动填入。
            </p>
            <div className="promptLayerList">
              {promptStructureLayers.map((layer) => (
                <div className="promptLayer" key={layer.code}>
                  <b>{layer.code}</b>
                  <span>
                    <strong>{layer.title}</strong>
                    <small>{layer.text}</small>
                  </span>
                </div>
              ))}
            </div>
            <div className="styleRecipeBox fullPromptBox">
              <div>
                <strong>完整拼接提示词（后台原文）</strong>
                <span>{stylePromptPreview ? `${stylePromptPreview.full_length} 字符` : "等待新版后台"}</span>
              </div>
              <pre>{stylePromptPreview?.full_prompt || `风格名称：${pageMode === "custom" ? "自定义参考" : style}\n视觉配方：${selectedStyleRecipe}\n\n完整动态模板将在当前运行任务结束、后台安全升级后显示。`}</pre>
            </div>
            {stylePromptPreview?.truncated && (
              <div className="styleRecipeBox sentPromptBox">
                <div>
                  <strong>实际提交给图片模型的提示词</strong>
                  <span>{stylePromptPreview.sent_length} / {stylePromptPreview.request.prompt_limit} 字符</span>
                </div>
                <pre>{stylePromptPreview.sent_prompt}</pre>
              </div>
            )}
            {stylePromptPreview && (
              <div className="promptRequestMeta">
                <span>请求参数</span>
                <code>size={stylePromptPreview.request.size}</code>
                <code>quality={stylePromptPreview.request.quality}</code>
                <code>format={stylePromptPreview.request.format}</code>
                <code>n={stylePromptPreview.request.n}</code>
                <strong>{stylePromptPreview.truncated ? "超过上限：下方同时展示实际截取版本" : "未截断：完整原文即实际提交内容"}</strong>
              </div>
            )}
            <footer className="stylePromptFooter">
              <span>最终提示词</span>
              <strong>分镜内容 ＋ 构图 ＋ 人物身份 ＋ 画风配方 ＋ 约束</strong>
            </footer>
          </aside>
        </div>
      </form>
      <section className="panel historyPanel">
        <Title n="03" title="生成历史" note="点击任务查看图片、参数与成片" />
        {history.length ? (
          <div className="historyList">
            {history.map((item) => (
              <article
                key={item.id}
                tabIndex={0}
                onClick={() => openTaskDetail(item)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openTaskDetail(item);
                  }
                }}
              >
                <div>
                  <strong>
                    <em>{item.job_type === "rerender" ? "重新渲染" : item.job_type === "infographic" ? "动态信息图" : "视频生成"}</em>
                    {item.task_name || `未命名任务-${item.id.slice(-4)}`}
                  </strong>
                  <span>
                    {formatDate(item.created_at)} · {item.style || "默认风格"} · {hasPendingRerender(item) ? "图片已更新" : item.stage}
                  </span>
                  <span className="historyMeta">
                    笔身文字：{item.pen_text || "未设置"} · IP：
                    {item.client_ip || "未知"}
                  </span>
                </div>
                <div>
                  <span className="imageCount">{item.image_count ? `${item.image_count} 张图片` : "暂无图片"}</span>
                  {item.can_cancel && (
                    <button
                      type="button"
                      className="cancelHistory"
                      onClick={(event) => {
                        event.stopPropagation();
                        cancelTask(item);
                      }}
                    >
                      取消
                    </button>
                  )}
                  {item.status === "done" && item.result_url && !hasPendingRerender(item) && (
                    <a className="downloadHistory" href={`${API}${item.result_url}`} download onClick={(event) => event.stopPropagation()}>
                      下载成片
                    </a>
                  )}
                  {item.status === "done" && hasPendingRerender(item) && (
                    <button
                      type="button"
                      className="rerenderHistory"
                      onClick={(event) => {
                        event.stopPropagation();
                        openRerenderDialog(item);
                      }}
                    >
                      已重新生成，重新渲染成片
                    </button>
                  )}
                  <button
                    type="button"
                    className="viewHistory"
                    onClick={(event) => {
                      event.stopPropagation();
                      openTaskDetail(item);
                    }}
                  >
                    查看详情
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="historyEmpty">完成一次视频制作后，记录会显示在这里。</p>
        )}
      </section>
      {detailJobId && detailJob && (
        <div
          className="taskDetailOverlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setDetailJobId(null);
              setPreviewImage(null);
            }
          }}
        >
          <section className="taskDetailDialog" role="dialog" aria-modal="true" aria-label="任务详情">
            <header>
              <div>
                <span className={`taskStatus ${detailJob.status}`}>{statusLabel(detailJob.status)}</span>
                <div className="detailTitleLine">
                  <h2>{detailJob.task_name || detailJob.id}</h2>
                  <button type="button" className="renameTaskButton" onClick={() => openRenameDialog(detailJob)}>
                    修改名称
                  </button>
                </div>
                <p>
                  {detailJob.stage} · {detailJob.progress}% · {formatDate(detailJob.created_at)}
                </p>
              </div>
              <button
                type="button"
                className="detailClose"
                onClick={() => {
                  setDetailJobId(null);
                  setPreviewImage(null);
                }}
                aria-label="关闭"
              >
                ×
              </button>
            </header>
            <div className="taskDetailBody">
              <section className="detailGallery">
                <div className="detailSectionTitle">
                  <div>
                    <strong>生成图片</strong>
                    <span>{gallery.length ? `共 ${gallery.length} 张，单击切换提示词，双击或点击右上角放大` : detailLoading ? "正在读取图片…" : "该任务尚未生成图片"}</span>
                  </div>
                  <div className="galleryHeaderActions">
                    {gallery.length > 0 && (
                      <a className="downloadAllImages" href={`${API}/api/jobs/${detailJob.id}/images.zip`} download>
                        保存全部图片
                      </a>
                    )}
                    {["queued", "running"].includes(detailJob.status) && <i>生成中，图片会自动出现</i>}
                  </div>
                </div>
                {gallery.length ? (
                  <div className="galleryGrid">
                    {gallery.map((image) => (
                      <article key={image.name} className={selectedGalleryPage === image.page ? "selected" : ""}>
                        <button type="button" className="gallerySelect" onClick={() => selectGalleryPrompt(image)} onDoubleClick={() => setPreviewImage(image)} aria-label={`选择第 ${image.page} 张图片提示词，双击放大`}>
                          <img src={`${API}${image.url}`} alt={`第 ${image.page} 张生成图片`} />
                          <span>第 {image.page} 张</span>
                        </button>
                        <button
                          type="button"
                          className="galleryExpand"
                          onClick={(event) => {
                            event.stopPropagation();
                            setPreviewImage(image);
                          }}
                          aria-label={`放大第 ${image.page} 张图片`}
                          title="放大图片"
                        >
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" />
                          </svg>
                        </button>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="galleryEmpty">
                    <b>{detailLoading ? "正在加载…" : "暂无可查看图片"}</b>
                    <span>{detailJob.status === "error" ? "可以从断点继续任务" : "图片生成后会显示在这里"}</span>
                  </div>
                )}
              </section>
              <aside className="detailSidebar">
                <section>
                  <h3>本次参数</h3>
                  {detailParameters ? (
                    <dl>
                      <div>
                        <dt>制作方式</dt>
                        <dd>{modeLabel(detailParameters.reference_mode)}</dd>
                      </div>
                      <div>
                        <dt>画面风格</dt>
                        <dd>{detailParameters.style}</dd>
                      </div>
                      <div>
                        <dt>画面比例</dt>
                        <dd>{detailParameters.aspect_ratio || "16:9"}</dd>
                      </div>
                      <div>
                        <dt>字幕</dt>
                        <dd>{detailParameters.include_subtitles ? "已添加" : "未添加"}</dd>
                      </div>
                      {detailParameters.reference_mode !== "infographic" && (
                        <>
                          <div>
                            <dt>每张分镜</dt>
                            <dd>{detailParameters.scenes_per_image} 幕</dd>
                          </div>
                          <div>
                            <dt>画面重点文字</dt>
                            <dd>{detailParameters.include_key_text ? "显示" : "不显示"}</dd>
                          </div>
                        </>
                      )}
                      <div>
                        <dt>参考音频</dt>
                        <dd>{detailParameters.reference?.name || "缺失"}</dd>
                      </div>
                      {detailParameters.characters.length > 0 && (
                        <div>
                          <dt>人物参考</dt>
                          <dd>{detailParameters.characters.length} 组</dd>
                        </div>
                      )}
                    </dl>
                  ) : (
                    <p>正在读取参数…</p>
                  )}
                </section>
                {detailParameters && (
                  <section className="detailMaterials">
                    <header>
                      <div>
                        <h3>本次使用的素材</h3>
                        <span>音频可播放，参考图可放大</span>
                      </div>
                    </header>
                    {detailParameters.reference && (
                      <div className="detailAudio">
                        <b>{detailParameters.reference.name}</b>
                        <audio controls preload="metadata" src={`${API}${detailParameters.reference.url}`} />
                      </div>
                    )}
                    {detailParameters.style_reference && (
                      <div className="detailReferenceGroup">
                        <b>风格参考图</b>
                        <button
                          type="button"
                          onClick={() =>
                            setAssetPreview({
                              src: `${API}${detailParameters.style_reference!.url}`,
                              label: "风格参考图",
                            })
                          }
                        >
                          <img src={`${API}${detailParameters.style_reference.url}`} alt="风格参考图" />
                          <span>点击放大</span>
                        </button>
                      </div>
                    )}
                    {detailParameters.characters.map((character, index) => (
                      <div className="detailReferenceGroup" key={`${character.name}-${index}`}>
                        <b>{character.name}</b>
                        <div>
                          {character.images.map((image, imageIndex) => (
                            <button
                              type="button"
                              key={image.url}
                              onClick={() =>
                                setAssetPreview({
                                  src: `${API}${image.url}`,
                                  label: `${character.name}参考图 ${imageIndex + 1}`,
                                })
                              }
                            >
                              <img src={`${API}${image.url}`} alt={`${character.name}参考图 ${imageIndex + 1}`} />
                              <span>放大</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                    {!detailParameters.reference && !detailParameters.style_reference && detailParameters.characters.every((character) => character.images.length === 0) && <p className="detailMaterialsEmpty">本次没有上传音频或参考图片</p>}
                    {detailJob.status === "done" && detailJob.can_rerender && (
                      <button type="button" className="rerenderFromDetail" onClick={() => openRerenderDialog(detailJob)}>
                        用当前图片重新渲染成片
                      </button>
                    )}
                  </section>
                )}
                {selectedGalleryImage && (
                  <section className="promptEditorEmbedded">
                    <header>
                      <div>
                        <strong>第 {selectedGalleryImage.page} 张图片提示词</strong>
                        <span>{selectedGalleryImage.scene_numbers?.length ? `对应第 ${selectedGalleryImage.scene_numbers.join("、")} 个场景` : "可修改后只重生成这一张"}</span>
                      </div>
                    </header>
                    <textarea value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} placeholder="输入这张图片的生成提示词" />
                    <div className="promptMeta">
                      <span>{promptDraft.length} 字</span>
                      <button type="button" disabled={regeneratingPage !== null || detailJob.can_cancel || promptDraft.trim().length < 5} onClick={regenerateImage}>
                        {regeneratingPage === selectedGalleryImage.page ? "正在提交…" : detailJob.can_cancel ? "任务执行中" : "保存提示词并重新生成"}
                      </button>
                    </div>
                    {detailActionMessage && <p>{detailActionMessage}</p>}
                  </section>
                )}
                {detailJob.error && (
                  <section className="detailError">
                    <h3>错误信息</h3>
                    <p>{detailJob.error}</p>
                  </section>
                )}
                <div className="detailActions">
                  <button type="button" className="reuseTask" disabled={restoringJobId === detailJob.id} onClick={() => restoreParameters(detailJob)}>
                    {restoringJobId === detailJob.id ? "正在读取素材…" : "复用本次设置和素材"}
                  </button>
                  {detailJob.can_cancel && (
                    <button type="button" className="cancelTaskDetail" onClick={() => cancelTask(detailJob)}>
                      取消任务
                    </button>
                  )}
                  {detailJob.status === "error" && detailJob.can_retry && (
                    <button type="button" className="retryTaskDetail" onClick={() => retryFailed(detailJob)}>
                      从断点继续
                    </button>
                  )}
                  {detailJob.status === "done" && detailJob.result_url && !hasPendingRerender(detailJob) && <a href={`${API}${detailJob.result_url}`}>下载成片</a>}
                </div>
              </aside>
            </div>
            {detailJob.status === "done" && detailJob.result_url && !hasPendingRerender(detailJob) && (
              <div className="detailVideo">
                <strong>最终成片</strong>
                <video controls src={`${API}${detailJob.result_url}`} />
              </div>
            )}
          </section>
          {previewImage && (
            <div
              className="imageLightbox"
              role="dialog"
              aria-modal="true"
              aria-label={`第 ${previewImage.page} 张图片`}
              onMouseDown={(event) => {
                if (event.target === event.currentTarget) setPreviewImage(null);
              }}
            >
              <button type="button" onClick={() => setPreviewImage(null)}>
                ×
              </button>
              <img src={`${API}${previewImage.url}`} alt={`第 ${previewImage.page} 张生成图片大图`} />
              <span>第 {previewImage.page} 张</span>
            </div>
          )}
        </div>
      )}
      {renameJob && (
        /* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */
        <div className="nameDialogOverlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setRenameJob(null)}>
          <form className="nameDialog" role="dialog" aria-modal="true" aria-labelledby="rename-dialog-title" onSubmit={(event) => { event.preventDefault(); void saveTaskName(); }}>
            <span>任务名称</span>
            <h3 id="rename-dialog-title">修改任务名</h3>
            <p>只修改历史记录中的显示名称，不会重新执行或改变任务内容。</p>
            <label>新任务名<input maxLength={30} value={renameDraft} onChange={(event) => setRenameDraft(event.target.value)} /><small>{renameDraft.length}/30</small></label>
            {detailActionMessage && <em>{detailActionMessage}</em>}
            <div><button type="button" className="secondary" onClick={() => setRenameJob(null)}>取消</button><button type="submit" className="primary small" disabled={renaming || !renameDraft.trim()}>{renaming ? "保存中…" : "确认修改"}</button></div>
          </form>
        </div>
      )}
      {rerenderSource && (
        /* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */
        <div className="nameDialogOverlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setRerenderSource(null)}>
          <form className="nameDialog rerenderNameDialog" role="dialog" aria-modal="true" aria-labelledby="rerender-dialog-title" onSubmit={(event) => { event.preventDefault(); void submitRerender(); }}>
            <span>新建重新渲染任务</span>
            <h3 id="rerender-dialog-title">确认新任务名称</h3>
            <p>系统会复制当前配音、分镜和全部图片，新建一条历史任务；原任务与原成片不会被覆盖。</p>
            <label>新任务名<input maxLength={30} value={rerenderName} onChange={(event) => setRerenderName(event.target.value)} /><small>{rerenderName.length}/30 · 已自动填写重新渲染版本号</small></label>
            {detailActionMessage && <em>{detailActionMessage}</em>}
            <div><button type="button" className="secondary" onClick={() => setRerenderSource(null)}>取消</button><button type="submit" className="primary small" disabled={rerendering || !rerenderName.trim()}>{rerendering ? "正在复制并提交…" : "复制并开始重新渲染"}</button></div>
          </form>
        </div>
      )}
      {inputPreviewFile && <FileLightbox file={inputPreviewFile} onClose={() => setInputPreviewFile(null)} />} {" "}
      {assetPreview && (
        <div
          className="imageLightbox assetLightbox"
          role="dialog"
          aria-modal="true"
          aria-label={assetPreview.label}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAssetPreview(null);
          }}
        >
          <button type="button" onClick={() => setAssetPreview(null)}>
            ×
          </button>
          <img src={assetPreview.src} alt={assetPreview.label} />
          <span>{assetPreview.label}</span>
        </div>
      )}
      <footer>
        <span>所有素材与历史记录保存在你的电脑上</span>
        <span>IndexTTS 2.5 · GPT-5 · GPT Image 2 · FFmpeg</span>
      </footer>
    </main>
  );
}
function Title({ n, title, note }: { n: string; title: string; note: string }) {
  return (
    <div className="sectionTitle">
      <div>
        <span>{n}</span>
        <h2>{title}</h2>
      </div>
      <p>{note}</p>
    </div>
  );
}
function formatDuration(value: number) {
  const seconds = Math.max(0, Math.floor(value));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}时 ${m}分 ${s}秒` : m ? `${m}分 ${s}秒` : `${s}秒`;
}
function formatDate(value?: number) {
  return value
    ? new Date(value * 1000).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "刚刚";
}
function strokeLabel(value?: string) {
  return (
    (
      {
        light: "精简线条",
        standard: "标准线条",
        detailed: "丰富线条",
        full: "完整线条",
      } as Record<string, string>
    )[value || ""] || "丰富线条"
  );
}
function statusLabel(value: Job["status"]) {
  return (
    {
      queued: "排队中",
      running: "制作中",
      done: "已完成",
      error: "失败",
      cancelled: "已取消",
    } as Record<Job["status"], string>
  )[value];
}
function modeLabel(value: JobParameters["reference_mode"]) {
  return (
    {
      standard: "标准制作",
      custom: "自定义参考",
      infographic: "动态信息图",
    } as Record<JobParameters["reference_mode"], string>
  )[value];
}
function normalizeVoiceMode(value: unknown): VoiceMode {
  return value === "none" || value === "uploaded" ? value : "clone";
}
function AudioFilePreview({ file }: { file: File }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return (
    <div className="audioPreview">
      <div>
        <strong>试听参考音频</strong>
        <span>可拖动进度，点击上方上传区可重新选择</span>
      </div>
      <audio controls preload="metadata" src={url || undefined} />
    </div>
  );
}
function FileThumbnail({ file, label, onOpen }: { file: File; label: string; onOpen: () => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return (
    <button type="button" className="fileThumbnail" onClick={onOpen} aria-label={label}>
      {url && <img src={url} alt="" />}
      <span>放大</span>
    </button>
  );
}
function FileLightbox({ file, onClose }: { file: File; onClose: () => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return (
    <div
      className="imageLightbox assetLightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`查看 ${file.name}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <button type="button" onClick={onClose}>
        ×
      </button>
      {url && <img src={url} alt={file.name} />}
      <span>{file.name}</span>
    </div>
  );
}

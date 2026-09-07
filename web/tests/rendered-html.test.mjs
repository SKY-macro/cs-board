import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readPageSource = async () =>
  (await readFile(new URL("../app/page.tsx", import.meta.url), "utf8")).replace(
    /\s+/g,
    "",
  );

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the whiteboard video application", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/i);
  assert.match(html, /<title>有温度出品<\/title>/i);
  assert.match(html, /把你的表达，画成一支有节奏的白板视频/);
  assert.match(html, /无旁白/);
  assert.match(html, /上传克隆音色样本/);
  assert.match(html, /直接使用旁白/);
  assert.match(html, /开始生成视频/);
  assert.match(html, /API 设置/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("keeps public defaults portable and free of local configuration", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /tts_url:"http:\/\/127\.0\.0\.1:7860"/);
  assert.match(page, /api_key:""/);
  assert.doesNotMatch(page, /192\.168\.|10\.\d+\.\d+\.\d+/);
  assert.match(layout, /title:\s*"有温度出品"/);
  assert.match(packageJson, /"build": "vinext build"/);
  assert.match(packageJson, /"test": "npm run build/);
});

test("offers three modular voice strategies and only uploads audio when selected", async () => {
  const page = await readPageSource();
  assert.match(page, /typeVoiceMode="none"\|"clone"\|"uploaded"/);
  assert.match(page, /voiceMode!=="none"&&!reference/);
  assert.match(page, /if\(reference\)body\.append\("reference",reference\)/);
  assert.match(page, /className="noNarrationNotice"/);
  assert.match(page, /与“直接使用旁白”相同/);
  assert.match(page, /建立视频节奏/);
  assert.match(page, /处理完整旁白/);
});

test("does not accumulate permanent new badges on style cards", async () => {
  const page = await readPageSource();
  assert.doesNotMatch(page, /badge:\s*"新增"/);
});

test("uses a modal API settings flow with debounced in-page autosave", async () => {
  const page = await readPageSource();
  assert.match(page, /className="settingsOverlay"/);
  assert.match(page, /className="settingsDialogpanel"/);
  assert.match(page, /aria-modal="true"/);
  assert.match(page, /setTimeout\([^]*900\)/);
  assert.match(page, /已自动保存/);
  assert.doesNotMatch(page, /window\.confirm\("确认保存当前 API/);
  assert.doesNotMatch(page, /window\.alert\("设置保存/);
});

test("auto-detects only the edited text or image relay model after saving", async () => {
  const page = await readPageSource();
  assert.match(page, /detectChangedServiceModels/);
  assert.match(page, /serviceSignature\(kind,node\)/);
  assert.match(page, /voiddetectChangedServiceModels\(snapshot\)/);
  assert.match(page, /图片节点.*已自动识别并更正|kind==="text"\?"文本":"图片"/);
});

test("creates text and image relay nodes without copying an existing endpoint", async () => {
  const page = await readPageSource();
  const addService = page.match(/constaddService=.*?constremoveService/s)?.[0] || "";
  assert.match(addService, /base_url:"",api_key:""/);
  assert.doesNotMatch(addService, /fallback/);
});

test("shows callable versus configured relay counts for text and images", async () => {
  const page = await readPageSource();
  assert.match(page, /serviceAvailability/);
  assert.match(page, /可调用\{textAvailability\.ready\}\/\{textAvailability\.total\}/);
  assert.match(page, /可调用\{imageAvailability\.ready\}\/\{imageAvailability\.total\}/);
});

test("offers three mutually exclusive identity prompt modes and persists the choice", async () => {
  const page = await readPageSource();
  assert.match(page, /typeIdentityMode="consistent"\|"male"\|"female"/);
  assert.match(page, /身份一致（默认）/);
  assert.match(page, /默认男主角/);
  assert.match(page, /默认女主角/);
  assert.match(page, /body\.append\("identity_mode",identityMode\)/);
  assert.match(page, /setIdentityMode\(normalizeIdentityMode\(data\.identity_mode\)\)/);
});

test("keeps prompt editing inside task details and separates select from zoom", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/brand.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /onClick=\{\(\)=>selectGalleryPrompt\(image\)\}/);
  assert.match(page, /onDoubleClick=\{\(\)=>setPreviewImage\(image\)\}/);
  assert.match(page, /className="galleryExpand"/);
  assert.match(page, /className="promptEditorEmbedded"/);
  assert.doesNotMatch(page, /className="promptEditorPanel"/);
  assert.match(css, /\.taskDetailDialog\s*\{[^}]*font-size:\s*15px/s);
  assert.match(css, /\.galleryExpand\s*\{/);
});

test("embeds used media controls inside task details", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/brand.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /className="detailMaterials"/);
  assert.match(page, /本次使用的素材/);
  assert.match(page, /用当前图片重新渲染成片/);
  assert.doesNotMatch(page, /className="detailMediaDock"/);
  assert.match(css, /\.detailMaterials\s*\{/);
  assert.doesNotMatch(css, /\.detailMediaDock\s*\{[^}]*position:\s*fixed/s);
});

test("offers rerender below the gallery and hides stale video", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/brand.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /needs_rerender\?:boolean/);
  assert.match(page, /hasPendingRerender/);
  assert.match(page, /className="rerenderProgressButton"/);
  assert.match(page, />重新渲染成片<\/button>/);
  assert.match(page, /result_url&&!hasPendingRerender/);
  assert.match(css, /\.galleryButton,\s*\.rerenderProgressButton/);
  assert.match(page, /className="rerenderHistory"/);
  assert.match(page, /已重新生成，重新渲染成片/);
  assert.match(page, /openRerenderDialog\(item\)/);
  assert.match(css, /\.historyList button\.rerenderHistory\s*\{/);
  assert.match(css, /font-size:\s*10px/);
});

test("renames tasks, versions copied rerenders, and downloads every image", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/brand.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /className="renameTaskButton"/);
  assert.match(page, /\/api\/jobs\/\$\{renameJob\.id\}\/name/);
  assert.match(page, /确认新任务名称/);
  assert.match(page, /\+重新渲染第\$\{version\}版/);
  assert.match(page, /原任务与原成片不会被覆盖/);
  assert.match(page, /className="downloadAllImages"/);
  assert.match(page, /\/api\/jobs\/\$\{detailJob\.id\}\/images\.zip/);
  assert.match(css, /\.nameDialogOverlay\s*\{/);
  assert.match(css, /\.downloadAllImages\s*\{/);
});

test("keeps running jobs in the background while creating another task", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/brand.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /constfocusedJobId=useRef<string\|null>\(null\)/);
  assert.match(page, /focusedJobId\.current===id\)setJob\(next\)/);
  assert.match(page, /constcreateAnotherTask=/);
  assert.match(page, /上一任务继续在后台制作/);
  assert.match(page, /className="newTaskButton"/);
  assert.match(page, />创建新的任务<\/button>/);
  assert.match(css, /\.newTaskButton\s*\{/);
});

test("shows image relay RPM and in-flight statistics in API settings", async () => {
  const page = await readPageSource();
  assert.match(page, /image:\{default_rpm\?:number;default_concurrency\?:number;max_rpm\?:number;global_rpm_limit\?:number/);
  assert.match(page, /health\.queues\.image\.default_rpm!==undefined/);
  assert.match(page, /RPM·在途/);
  assert.match(page, /429\{node\.rate_limit_count\}次/);
  assert.match(page, /node\.average_latency\.toFixed\(1\)/);
  assert.match(page, /图片容量控制台/);
  assert.match(page, /标称RPM<inputtype="number"/);
  assert.match(page, /标称RPD<inputtype="number"/);
  assert.match(page, /安全使用率<select/);
  assert.match(page, /110RPM\/1800RPD/);
  assert.match(page, /image_global_rpm_limit/);
  assert.match(page, /image_global_in_flight_limit/);
  assert.match(page, /实际目标/);
  assert.match(page, /RPM、RPD和安全余量按节点独立计算/);
  assert.match(page, /global_in_flight_limit/);
  assert.match(page, /imageCircuitLabel/);
  assert.match(page, /effective_rpm_limit/);
  assert.match(page, /已封顶\$\{node\.effective_rpm_limit\?\?node\.rpm\}RPM至重启/);
  assert.match(page, /今日请求\{node\.daily_used\?\?0\}/);
  assert.match(page, /恢复观察/);
  assert.match(page, /resetImageTierMemory/);
  assert.match(page, /reset-rpm-memory/);
  assert.match(page, />解除档位记忆<\/button>/);
  assert.match(page, /clearImageCircuitBreaker/);
  assert.match(page, /clear-circuit-breaker/);
  assert.match(page, />清除熔断<\/button>/);
});

test("shows a live prompt structure panel for the selected visual style", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /fetch\(`\$\{API\}\/api\/styles`\)/);
  assert.match(page, /fetch\(`\$\{API\}\/api\/style-prompt-preview`/);
  assert.match(page, /onClick=\{\(\)=>setStyle\(item\.name\)\}/);
  assert.match(page, /className="panelstylePromptPanel"/);
  assert.match(page, /画风提示词结构/);
  assert.match(page, /promptStructureLayers\.map/);
  assert.match(page, /完整拼接提示词（后台原文）/);
  assert.match(page, /实际提交给图片模型的提示词/);
  assert.match(page, /stylePromptPreview\?\.full_prompt/);
  assert.match(page, /stylePromptPreview\.sent_prompt/);
  assert.match(page, /超过上限：下方同时展示实际截取版本/);
  assert.match(page, /分镜内容＋构图＋人物身份＋画风配方＋约束/);
  assert.match(css, /\.stylePromptPanel\s*\{/);
  assert.match(css, /\.styleRecipeBox\s*\{/);
});

test("supports one-click missing-role draws and live green binding feedback", async () => {
  const [page, css] = await Promise.all([
    readPageSource(),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /asset_label\?:string/);
  assert.match(page, /core_personality\?:string/);
  assert.match(page, /facial_persona\?:string/);
  assert.match(page, /核心性格：/);
  assert.match(page, /固定脸相：/);
  assert.match(page, /constdrawMissingCharacter=/);
  assert.match(page, /"去抽卡"/);
  assert.match(page, /story_name.*asset_label/s);
  assert.match(page, /setCharacterBindings\(\(items\)=>items\.map/);
  assert.ok(
    page.indexOf("<strong>本任务角色资产</strong>") < page.indexOf("<strong>成片设置</strong>"),
    "task character assets should appear immediately before production settings",
  );
  assert.match(css, /\.taskCharacterBindings article\.matched/);
  assert.match(css, /\.drawMissingRole/);
});

test("restores matched characters into a detached reusable task form", async () => {
  const page = await readPageSource();
  assert.match(page, /constrestoredCharacterState=useRef/);
  assert.match(page, /constrestoreParameters=.*focusedJobId\.current=null.*setJob\(null\).*setRerenderSource\(null\)/s);
  assert.doesNotMatch(page, /constrestoreParameters=.*setJob\(source\).*constopenTaskDetail/s);
  assert.match(page, /binding\.match_confidence!=null.*%匹配.*已绑定/s);
});

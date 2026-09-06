import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
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
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /type VoiceMode="none"\|"clone"\|"uploaded"/);
  assert.match(page, /voiceMode!=="none"&&!reference/);
  assert.match(page, /if\(reference\)body\.append\("reference",reference\)/);
  assert.match(page, /className="noNarrationNotice"/);
  assert.match(page, /与“直接使用旁白”相同/);
  assert.match(page, /建立视频节奏/);
  assert.match(page, /处理完整旁白/);
});

test("does not accumulate permanent new badges on style cards", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /badge:\s*"新增"/);
});

test("uses a modal API settings flow with debounced in-page autosave", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /className="settingsOverlay"/);
  assert.match(page, /className="settingsDialog panel"/);
  assert.match(page, /aria-modal="true"/);
  assert.match(page, /setTimeout\([^]*900\)/);
  assert.match(page, /已自动保存/);
  assert.doesNotMatch(page, /window\.confirm\("确认保存当前 API/);
  assert.doesNotMatch(page, /window\.alert\("设置保存/);
});

test("auto-detects only the edited text or image relay model after saving", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /detectChangedServiceModels/);
  assert.match(page, /serviceSignature\(kind,node\)/);
  assert.match(page, /void detectChangedServiceModels\(snapshot\)/);
  assert.match(page, /图片节点.*已自动识别并更正|kind==="text"\?"文本":"图片"/);
});

test("creates text and image relay nodes without copying an existing endpoint", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const addService = page.match(/const addService=.*?;\r?\n/)?.[0] || "";
  assert.match(addService, /base_url:"",api_key:""/);
  assert.doesNotMatch(addService, /fallback/);
});

test("shows callable versus configured relay counts for text and images", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /serviceAvailability/);
  assert.match(page, /可调用 \{textAvailability\.ready\}\/\{textAvailability\.total\}/);
  assert.match(page, /可调用 \{imageAvailability\.ready\}\/\{imageAvailability\.total\}/);
});

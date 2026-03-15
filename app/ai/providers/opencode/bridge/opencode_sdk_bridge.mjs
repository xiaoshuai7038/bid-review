#!/usr/bin/env node

import childProcess from "node:child_process";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const configuredRuntimeRoot = String(process.env.BID_REVIEW_OPENCODE_RUNTIME_ROOT || "").trim();
const repoRoot = configuredRuntimeRoot
  ? path.resolve(configuredRuntimeRoot)
  : path.resolve(__dirname, "../../../../../");

function writeEvent(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function normalizeErrorMessage(error) {
  if (error instanceof Error) {
    return error.message || error.name;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function fail(message, extra = {}) {
  writeEvent({
    type: "error",
    error: {
      message,
      ...extra,
    },
  });
  process.exitCode = 1;
}

async function readPayload() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const raw = chunks.join("").trim();
  if (!raw) {
    throw new Error("Bridge 未收到 JSON payload。");
  }
  return JSON.parse(raw);
}

function localBinDir() {
  return path.join(repoRoot, "node_modules", ".bin");
}

function localOpencodeBin() {
  const binName = process.platform === "win32" ? "opencode.cmd" : "opencode";
  return path.join(localBinDir(), binName);
}

function runtimeBinaryCandidates() {
  if (process.platform === "win32") {
    return [
      path.join(repoRoot, "node_modules", "opencode-windows-x64", "bin", "opencode.exe"),
      path.join(repoRoot, "node_modules", "opencode-windows-x64-baseline", "bin", "opencode.exe"),
      path.join(repoRoot, "node_modules", "opencode-windows-arm64", "bin", "opencode.exe"),
    ];
  }
  return [
    path.join(repoRoot, "node_modules", "opencode-linux-x64", "bin", "opencode"),
    path.join(repoRoot, "node_modules", "opencode-linux-arm64", "bin", "opencode"),
    path.join(repoRoot, "node_modules", "opencode-darwin-x64", "bin", "opencode"),
    path.join(repoRoot, "node_modules", "opencode-darwin-arm64", "bin", "opencode"),
  ];
}

function resolveRuntimeBinary() {
  for (const candidate of runtimeBinaryCandidates()) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "";
}

function prependLocalBinToPath(artifacts) {
  const current = process.env.PATH || "";
  const parts = current.split(path.delimiter).filter(Boolean);
  const prepend = [];
  if (artifacts.runtimeBinary) {
    prepend.push(path.dirname(artifacts.runtimeBinary));
  }
  prepend.push(localBinDir());
  const merged = [...prepend, ...parts].filter(Boolean);
  const deduped = [];
  const seen = new Set();
  for (const item of merged) {
    const key = item.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(item);
  }
  process.env.PATH = deduped.join(path.delimiter);
}

function patchWindowsChildProcesses() {
  if (process.platform !== "win32") {
    return;
  }
  if (childProcess.spawn?.__bidreviewPatched) {
    return;
  }

  const wrapSpawner = (original) => {
    const wrapped = function patchedSpawner(file, args, options) {
      let actualFile = file;
      let actualArgs = args;
      let actualOptions = options;
      if (!Array.isArray(actualArgs)) {
        actualOptions = actualArgs || {};
        actualArgs = [];
      }
      actualOptions = { ...(actualOptions || {}), windowsHide: true };
      const explicitRuntimeBinary = String(process.env.OPENCODE_BIN_PATH || "").trim();
      if (explicitRuntimeBinary && String(actualFile || "").trim().toLowerCase() === "opencode") {
        actualFile = explicitRuntimeBinary;
      }
      return original(actualFile, actualArgs, actualOptions);
    };
    Object.defineProperty(wrapped, "__bidreviewPatched", {
      value: true,
      enumerable: false,
    });
    return wrapped;
  };

  childProcess.spawn = wrapSpawner(childProcess.spawn);
  childProcess.spawnSync = wrapSpawner(childProcess.spawnSync);
  syncBuiltinESMExports();
}

function resolveRuntimeArtifacts() {
  const artifacts = {
    sdkPackage: path.join(repoRoot, "node_modules", "@opencode-ai", "sdk"),
    cliPackage: path.join(repoRoot, "node_modules", "opencode-ai"),
    localBin: localOpencodeBin(),
    runtimeBinary: resolveRuntimeBinary(),
  };

  if (!fs.existsSync(artifacts.sdkPackage)) {
    throw new Error("未安装本地依赖 `@opencode-ai/sdk`。请先在仓库根目录执行 `npm install`。");
  }

  if (!fs.existsSync(artifacts.cliPackage)) {
    throw new Error("未安装本地依赖 `opencode-ai`。请先在仓库根目录执行 `npm install`。");
  }

  if (!fs.existsSync(artifacts.localBin)) {
    throw new Error(
      `未找到本地 OpenCode 二进制：${artifacts.localBin}。请先在仓库根目录执行 \`npm install\`。`
    );
  }

  return artifacts;
}

function parseConfigFromEnv() {
  const raw = String(process.env.OPENCODE_CONFIG_CONTENT || "").trim();
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    throw new Error(`OPENCODE_CONFIG_CONTENT 不是合法 JSON：${normalizeErrorMessage(error)}`);
  }
}

function normalizeUsage(tokens) {
  if (!tokens || typeof tokens !== "object") {
    return {};
  }
  const input = Number(tokens.input || 0);
  const output = Number(tokens.output || 0);
  const reasoning = Number(tokens.reasoning || 0);
  const cache = tokens.cache && typeof tokens.cache === "object" ? tokens.cache : {};
  const total = Number(tokens.total || input + output + reasoning);
  return {
    input_tokens: input,
    output_tokens: output,
    cache_read_input_tokens: Number(cache.read || 0),
    cache_write_input_tokens: Number(cache.write || 0),
    reasoning_tokens: reasoning,
    total_tokens: total,
  };
}

function collectText(parts) {
  if (!Array.isArray(parts)) {
    return "";
  }
  return parts
    .filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}

function modelFromPayload(payload) {
  const model = payload.model;
  if (!model || typeof model !== "object") {
    return undefined;
  }
  if (!model.providerID || !model.modelID) {
    return undefined;
  }
  return {
    providerID: String(model.providerID),
    modelID: String(model.modelID),
  };
}

async function loadSdk() {
  const mod = await import("@opencode-ai/sdk/v2");
  return mod;
}

async function findFreePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("无法分配本地 OpenCode bridge 端口。")));
        return;
      }
      const port = address.port;
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(port);
      });
    });
  });
}

async function runHealthcheck(payload) {
  const artifacts = resolveRuntimeArtifacts();
  if (artifacts.runtimeBinary) {
    process.env.OPENCODE_BIN_PATH = artifacts.runtimeBinary;
  }
  prependLocalBinToPath(artifacts);
  patchWindowsChildProcesses();
  const config = parseConfigFromEnv();
  const { createOpencode } = await loadSdk();
  const port = await findFreePort();
  const runtime = await createOpencode({
    timeout: Number(payload.startupTimeoutMs || 10000),
    port,
    config,
  });

  try {
    const health = await runtime.client.global.health({
      throwOnError: true,
      responseStyle: "data",
    });

    writeEvent({
      type: "healthcheck",
      ok: true,
      node: process.version,
      bridge: path.relative(repoRoot, __filename).replaceAll("\\", "/"),
      localBin: artifacts.localBin,
      runtimeBinary: artifacts.runtimeBinary,
      sdkPackage: artifacts.sdkPackage,
      cliPackage: artifacts.cliPackage,
      health,
    });
  } finally {
    try {
      runtime.server.close();
    } catch {
      // noop
    }
  }
}

async function runPrompt(payload) {
  const artifacts = resolveRuntimeArtifacts();
  if (artifacts.runtimeBinary) {
    process.env.OPENCODE_BIN_PATH = artifacts.runtimeBinary;
  }
  prependLocalBinToPath(artifacts);
  patchWindowsChildProcesses();
  const config = parseConfigFromEnv();
  const { createOpencode } = await loadSdk();
  const port = await findFreePort();
  const runtime = await createOpencode({
    timeout: Number(payload.startupTimeoutMs || 10000),
    port,
    config,
  });

  const directory = String(payload.directory || repoRoot);
  const model = modelFromPayload(payload);
  const agent = payload.agent ? String(payload.agent) : undefined;
  const taskLabel = payload.taskLabel ? String(payload.taskLabel) : "BidReview OpenCode Session";
  const seenToolCalls = new Set();
  const textDeltaPartIDs = new Set();
  let sawStepFinish = false;
  let sessionID = null;
  let streamError = null;
  const eventAbort = new AbortController();

  const eventLoop = (async () => {
    const sse = await runtime.client.event.subscribe(
      {
        directory,
      },
      {
        signal: eventAbort.signal,
      }
    );

    for await (const event of sse.stream) {
      if (!event || typeof event !== "object") {
        continue;
      }

      if (event.type === "message.part.delta") {
        const props = event.properties || {};
        if (!sessionID || props.sessionID !== sessionID) {
          continue;
        }
        if (props.field === "text" && typeof props.delta === "string" && props.delta) {
          textDeltaPartIDs.add(String(props.partID || ""));
          writeEvent({
            type: "text",
            part: {
              text: props.delta,
            },
          });
        }
        continue;
      }

      if (event.type === "message.part.updated") {
        const part = event.properties?.part;
        if (!part || !sessionID || part.sessionID !== sessionID) {
          continue;
        }
        if (part.type === "text") {
          if (!textDeltaPartIDs.has(part.id) && typeof part.text === "string" && part.text) {
            writeEvent({
              type: "text",
              part: {
                text: part.text,
              },
            });
          }
          continue;
        }
        if (part.type === "tool") {
          if (!seenToolCalls.has(part.callID)) {
            seenToolCalls.add(part.callID);
            writeEvent({
              type: "tool_use",
              part: {
                tool: part.tool,
                state: part.state,
              },
            });
          }
          continue;
        }
        if (part.type === "step-finish") {
          sawStepFinish = true;
          writeEvent({
            type: "step_finish",
            part: {
              reason: part.reason,
              cost: part.cost,
              tokens: part.tokens,
            },
          });
          writeEvent({
            type: "usage",
            usage: normalizeUsage(part.tokens),
          });
        }
        continue;
      }

      if (event.type === "message.updated") {
        const info = event.properties?.info;
        if (!info || !sessionID || info.sessionID !== sessionID || info.role !== "assistant") {
          continue;
        }
        if (info.error) {
          streamError = normalizeErrorMessage(info.error?.data?.message || info.error?.message || info.error);
          break;
        }
        if (info.tokens) {
          writeEvent({
            type: "usage",
            usage: normalizeUsage(info.tokens),
          });
        }
        continue;
      }

      if (event.type === "permission.asked") {
        if (sessionID && event.properties?.sessionID === sessionID) {
          streamError = "OpenCode 请求权限确认，但当前为非交互 bridge 运行。请检查 permission 配置。";
          break;
        }
        continue;
      }

      if (event.type === "question.asked") {
        if (sessionID && event.properties?.sessionID === sessionID) {
          streamError = "OpenCode 请求用户回答问题，但当前为非交互 bridge 运行。";
          break;
        }
        continue;
      }

      if (event.type === "session.idle") {
        if (sessionID && event.properties?.sessionID === sessionID) {
          if (!sawStepFinish) {
            writeEvent({
              type: "step_finish",
              part: {
                reason: "idle",
              },
            });
          }
          break;
        }
      }
    }
  })();

  try {
    const createdSession = await runtime.client.session.create(
      {
        directory,
        title: taskLabel,
      },
      {
        throwOnError: true,
        responseStyle: "data",
      }
    );
    sessionID = createdSession.id;

    writeEvent({
      type: "session_started",
      session_id: sessionID,
      localBin: artifacts.localBin,
      runtimeBinary: artifacts.runtimeBinary,
    });

    const result = await runtime.client.session.prompt(
      {
        sessionID,
        directory,
        agent,
        model,
        parts: [
          {
            type: "text",
            text: String(payload.prompt || ""),
          },
        ],
      },
      {
        throwOnError: true,
        responseStyle: "data",
      }
    );

    const deadline = Date.now() + 1500;
    while (!streamError && !sawStepFinish && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }

    if (streamError) {
      throw new Error(streamError);
    }

    const text = collectText(result.parts);
    const usage = normalizeUsage(result.info?.tokens);

    writeEvent({
      type: "result",
      result: {
        text,
        usage,
        session_id: sessionID,
        cost: Number(result.info?.cost || 0),
      },
    });
  } finally {
    try {
      eventAbort.abort();
    } catch {
      // noop
    }
    try {
      await eventLoop;
    } catch (error) {
      const message = normalizeErrorMessage(error);
      if (message && !/aborted/i.test(message)) {
        writeEvent({
          type: "bridge_notice",
          notice: message,
        });
      }
    }
    try {
      runtime.server.close();
    } catch {
      // noop
    }
  }
}

async function main() {
  try {
    const payload = await readPayload();
    const action = String(payload.action || "prompt");
    if (action === "healthcheck") {
      await runHealthcheck(payload);
      return;
    }
    if (action === "prompt") {
      await runPrompt(payload);
      return;
    }
    throw new Error(`未知的 bridge action: ${action}`);
  } catch (error) {
    fail(normalizeErrorMessage(error));
  }
}

await main();

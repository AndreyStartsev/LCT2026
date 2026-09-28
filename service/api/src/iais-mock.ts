// Заглушка ИАИС «РиН» для стенда. Задача #34, ТЗ 9.6.
//
// Принимает POST /api/v1/inspection/{process_id} и хранит полученные протоколы в памяти.
// Режим меняется на лету, чтобы показать повторы и PENDING_SYNC:
//   ok     — принимает, 201;
//   fail   — недоступна, 503;
//   reject — отклоняет запрос, 422;
//   slow   — отвечает позже таймаута отправителя.
// POST /mock/mode {"mode": "fail"} переключает режим, GET /mock/received — что пришло.

import { randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

type Mode = "ok" | "fail" | "reject" | "slow";
const MODES: Mode[] = ["ok", "fail", "reject", "slow"];

let mode: Mode = MODES.includes(process.env.IAIS_MOCK_MODE as Mode) ? (process.env.IAIS_MOCK_MODE as Mode) : "ok";
const received: Array<Record<string, unknown>> = [];
let attempts = 0;

function log(message: string, fields: Record<string, unknown> = {}): void {
  console.log(JSON.stringify({ timestamp: new Date().toISOString(), level: "INFO", service: "iais-mock", message, ...fields }));
}

function send(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf-8");
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  try {
    if (req.method === "GET" && url.pathname === "/health") {
      return send(res, 200, { status: "ok", mode });
    }
    if (req.method === "GET" && url.pathname === "/mock/received") {
      return send(res, 200, { mode, attempts, received });
    }
    if (req.method === "POST" && url.pathname === "/mock/mode") {
      const next = JSON.parse((await readBody(req)) || "{}").mode as Mode;
      if (!MODES.includes(next)) return send(res, 400, { error: `mode: ${MODES.join(", ")}` });
      mode = next;
      log("режим заглушки изменён", { mode });
      return send(res, 200, { mode });
    }
    const match = url.pathname.match(/^\/api\/v1\/inspection\/([0-9a-f-]{36})$/i);
    if (req.method === "POST" && match) {
      attempts += 1;
      const body = await readBody(req);
      if (mode === "fail") {
        log("запрос отклонён: система недоступна", { process_id: match[1], attempt: attempts });
        return send(res, 503, { error: "SERVICE_UNAVAILABLE", message: "ИАИС «РиН» временно недоступна" });
      }
      if (mode === "reject") {
        return send(res, 422, { error: "VALIDATION_FAILED", message: "Протокол не прошёл проверку ИАИС «РиН»" });
      }
      if (mode === "slow") {
        await new Promise((resolve) => setTimeout(resolve, 60_000));
      }
      const payload = JSON.parse(body);
      const inspectionId = `РиН-${randomUUID().slice(0, 8).toUpperCase()}`;
      received.push({
        inspection_id: inspectionId,
        process_id: match[1],
        received_at: new Date().toISOString(),
        protocol_version: payload.protocol?.version ?? null,
        violations: Array.isArray(payload.violations) ? payload.violations.length : 0,
        input_files: Array.isArray(payload.input_files) ? payload.input_files.length : 0,
        payload_sha256: req.headers["x-payload-sha256"] ?? null,
      });
      log("протокол принят", { process_id: match[1], inspection_id: inspectionId });
      return send(res, 201, { inspection_id: inspectionId, status: "ACCEPTED" });
    }
    return send(res, 404, { error: "NOT_FOUND" });
  } catch (error) {
    return send(res, 400, { error: "BAD_REQUEST", message: (error as Error).message });
  }
});

const port = Number(process.env.PORT ?? 8090);
server.listen(port, "0.0.0.0", () => log("заглушка ИАИС «РиН» запущена", { port, mode }));

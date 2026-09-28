// Выгружает описание API в файл, чтобы оно лежало в репозитории рядом с кодом:
//   npm run build && npm run openapi
import { writeFile } from "node:fs/promises";
import { buildApp } from "./app.js";

const target = process.argv[2] ?? "openapi.json";
const app = await buildApp();
await app.ready();
await writeFile(target, JSON.stringify(app.swagger(), null, 2) + "\n", "utf-8");
await app.close();
console.log(`OpenAPI 3.0: ${target}`);
process.exit(0);

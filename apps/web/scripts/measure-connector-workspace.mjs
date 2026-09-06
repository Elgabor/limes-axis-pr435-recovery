/** Capture connector response bytes and their waterfall against a local fixture.
 * Usage: node scripts/measure-connector-workspace.mjs http://127.0.0.1:3364 report.json
 * The separately running web build determines which revision is measured.
 */
import { writeFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

const [baseURL, outputPath] = process.argv.slice(2);
if (!baseURL || !outputPath || !["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseURL).hostname)) {
  throw new Error("Provide a localhost console URL and a JSON output path.");
}
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const requests = [];
  const bodies = [];
  const active = new Set();
  const pageErrors = [];
  const failedRequests = [];
  const isConnector = (request) => new URL(request.url()).pathname.startsWith("/operations/connectors");
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => { if (isConnector(request)) active.add(request); });
  page.on("requestfinished", (request) => active.delete(request));
  page.on("requestfailed", (request) => {
    active.delete(request);
    if (isConnector(request)) failedRequests.push(new URL(request.url()).pathname);
  });
  page.on("response", (response) => {
    if (!isConnector(response.request())) return;
    bodies.push((async () => {
      const body = await response.body();
      const timing = response.request().timing();
      requests.push({
        path: new URL(response.url()).pathname + new URL(response.url()).search,
        status: response.status(), bytes: body.length,
        startedAt: timing.startTime, responseEndMs: timing.responseEnd,
      });
    })());
  });
  await page.goto(new URL("/connectors", baseURL).href);
  await page.getByRole("tab", { name: "Data & Schema" }).waitFor();
  // Readiness probes target other services. Wait only for connector reads to
  // settle, with two consecutive idle samples and a bounded deadline.
  const deadline = Date.now() + 15_000;
  let idleSamples = 0;
  while (idleSamples < 2 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    idleSamples = active.size === 0 ? idleSamples + 1 : 0;
  }
  if (idleSamples < 2) throw new Error("Connector requests did not settle within 15 seconds.");
  await Promise.all(bodies);
  const firstStart = Math.min(...requests.map((item) => item.startedAt));
  const report = {
    requests: requests.sort((a, b) => a.startedAt - b.startedAt).map((item) => ({
      path: item.path, status: item.status, bytes: item.bytes,
      startMs: +(item.startedAt - firstStart).toFixed(3), responseEndMs: item.responseEndMs,
    })),
    count: requests.length,
    bytes: requests.reduce((total, item) => total + item.bytes, 0),
    pageErrors,
    failedRequests,
  };
  await writeFile(outputPath, JSON.stringify(report, null, 2) + "\n");
  await page.screenshot({ path: outputPath.replace(/\.json$/, "") + ".png" });
  if (!requests.length || failedRequests.length || pageErrors.length || requests.some((item) => item.status !== 200)) {
    throw new Error("The capture includes page errors or unsuccessful connector responses.");
  }
} finally {
  await browser.close();
}

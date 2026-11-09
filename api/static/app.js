const status = document.querySelector("#status");
async function post(url, body) {
  const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Evaluation could not complete. Run " + (data.id || ""));
  return data;
}
document.querySelector("#run")?.addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true; status.textContent = "Evaluating…";
  try {
    const data = await post("/api/runs", {suite_id: button.dataset.suite, baseline: document.querySelector("#reference").checked ? null : "latest"});
    location.href = "/runs/" + data.id;
  } catch (error) { status.textContent = error.message; button.disabled = false; }
});
document.querySelector("#promote")?.addEventListener("click", async event => {
  try { await post("/api/runs/" + event.currentTarget.dataset.run + "/baseline", {}); status.textContent = "Baseline accepted."; }
  catch (error) { status.textContent = error.message; }
});
function draw() {
  const canvas = document.querySelector("#trend");
  if (!canvas) return;
  const runs = JSON.parse(document.querySelector("#trend-data").textContent);
  canvas.width = canvas.clientWidth * devicePixelRatio; canvas.height = 130 * devicePixelRatio;
  const ctx = canvas.getContext("2d"); ctx.scale(devicePixelRatio, devicePixelRatio);
  const width = canvas.clientWidth;
  ctx.fillStyle = "#62766b"; ctx.font = "12px system-ui"; ctx.fillText("100%", 0, 14); ctx.fillText("0%", 0, 125);
  if (!runs.length) { ctx.fillText("Awaiting first evaluation", 60, 70); return; }
  let previous;
  runs.forEach((run, i) => {
    if (run.aggregate_score == null || run.status !== "complete") { previous = null; return; }
    const x = 55 + i * (width - 75) / Math.max(1, runs.length - 1), y = 120 - run.aggregate_score;
    ctx.strokeStyle = "#408865"; ctx.lineWidth = 2;
    if (previous && previous.contract === run.contract_hash) { ctx.beginPath(); ctx.moveTo(previous.x, previous.y); ctx.lineTo(x, y); ctx.stroke(); }
    ctx.fillStyle = run.verdict === "fail" ? "#bb4639" : "#277458"; ctx.beginPath(); ctx.arc(x, y, 4, 0, 2*Math.PI); ctx.fill();
    if (run.id === canvas.dataset.baseline) {
      ctx.strokeStyle = "#182c39"; ctx.strokeRect(x - 6, y - 6, 12, 12);
      ctx.fillText("Baseline", Math.max(55, x - 25), Math.min(125, y + 22));
    }
    previous = {x, y, contract: run.contract_hash};
  });
}
draw(); addEventListener("resize", draw);

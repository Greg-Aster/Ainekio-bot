/* Optional experimental panel. Ordinary motion buttons keep their owners. */
(function () {
  "use strict";
  const panel = document.createElement("section");
  panel.className = "control-section";
  panel.dataset.workspacePanel = "poses";
  panel.hidden = true;
  panel.innerHTML = `<h2>Freestyle motions (experimental)</h2>
    <label>Generator address <input data-field="endpoint" value="http://127.0.0.1:8794"></label>
    <label><input data-field="recovery" type="checkbox"> Let Freestyle respond to body events</label>
    <button data-action="configure" type="button">Apply Freestyle settings</button>
    <label>Requested movement <textarea data-field="request" placeholder="Wave hello, then stretch both front legs"></textarea></label>
    <button data-action="generate" type="button">Generate only</button>
    <button data-action="execute" type="button">Generate and perform</button>
    <button data-action="refresh" type="button">Refresh result</button>
    <button data-action="save" type="button">Save trial data</button>
    <pre data-field="result" aria-live="polite"></pre>`;
  document.querySelector('[data-workspace-panel="poses"]').after(panel);
  const field = name => panel.querySelector(`[data-field="${name}"]`);
  const jobs = new Map();
  let displayedRobot = null;
  let settingsEdited = false;
  let displayedSettings = null;
  panel.addEventListener("input", event => {
    if (["endpoint", "recovery"].includes(event.target.dataset.field)) settingsEdited = true;
  });
  window.renderFreestyleStatus = (status, robot) => {
    const settings = status?.settings?.[robot] || {};
    const serialized = JSON.stringify(settings);
    if (displayedRobot !== robot || (!settingsEdited && displayedSettings !== serialized)) {
      field("endpoint").value = settings.endpoint || "http://127.0.0.1:8794";
      field("recovery").checked = settings.recover_events === true;
      settingsEdited = false;
      displayedSettings = serialized;
    }
    const latest = Object.values(status?.jobs || {}).filter(job => job.robot_id === robot).at(-1);
    if (latest) {
      jobs.set(robot, latest.id);
      field("result").textContent = JSON.stringify(latest,null,2);
    } else if (displayedRobot !== robot) {
      field("result").textContent = "";
    }
    displayedRobot = robot;
  };
  async function post(payload) {
    const session = await fetch("/api/session").then(r => r.json());
    const response = await fetch("/api/freestyle", {method:"POST", headers:{
      "Content-Type":"application/json", "X-Ainekio-CSRF":session.csrf}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || response.statusText);
    return result;
  }
  panel.addEventListener("click", async event => {
    const action = event.target.dataset.action;
    if (!action) return;
    const robot = document.getElementById("robot-select").value;
    try {
      let result;
      if (action === "refresh") {
        const status = await fetch("/api/status").then(r => r.json());
        result = status.freestyle?.jobs?.[jobs.get(robot)] || status.freestyle;
      } else if (action === "configure") {
        result = await post({operation:"configure",robot_id:robot,endpoint:field("endpoint").value,
          recover_events:field("recovery").checked});
        settingsEdited = false;
        displayedSettings = null;
      } else if (action === "save") {
        result = await post({operation:"trial",robot_id:robot,job_id:jobs.get(robot)});
        const url = URL.createObjectURL(new Blob([JSON.stringify(result,null,2)], {type:"application/json"}));
        const link = document.createElement("a");
        link.href=url;link.download=`freestyle-${result.job.id}.json`;link.click();
        URL.revokeObjectURL(url);
      } else {
        result = await post({robot_id:robot,request:field("request").value,execute:action === "execute"});
        jobs.set(robot,result.job_id);
      }
      field("result").textContent = JSON.stringify(result,null,2);
    } catch (error) { field("result").textContent = error.message; }
  });
}());

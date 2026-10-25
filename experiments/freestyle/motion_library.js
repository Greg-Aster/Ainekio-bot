/* Editable examples share the normal Body Control executor and status stream. */
(function () {
  "use strict";
  const host = document.querySelector('[data-workspace-panel="poses"]');
  const panel = document.createElement("section");
  panel.className = "motion-training-library";
  const pagination = `<div class="motion-library-pages" aria-label="Training data pages">
    <button type="button" data-action="first">First</button>
    <button type="button" data-action="previous">Previous</button>
    <span data-field="page" aria-live="polite"></span>
    <button type="button" data-action="next">Next</button>
    <button type="button" data-action="last">Last</button>
  </div>`;
  panel.innerHTML = `<h3>Training motion library</h3>
    <button type="button" data-action="open" aria-expanded="false">View training data</button>
    <div data-field="browser" hidden>
      <p>Browse and refine training examples, or play their commands directly on the selected robot.</p>
      <form data-field="search-form" class="motion-library-search">
        <label>Find a motion <input type="search" data-field="search" placeholder="Title, request or motion family"></label>
        <button type="submit">Search</button>
        <a href="/api/motion-library/export" download="motion-training-library.zip">Export training data</a>
      </form>
      <label>Sort by <select data-field="sort">
        <option value="name_asc">Name — A to Z</option>
        <option value="name_desc">Name — Z to A</option>
        <option value="added_desc">Date added — newest first</option>
        <option value="added_asc">Date added — oldest first</option>
        <option value="edited_desc">Last edited — newest first</option>
        <option value="edited_asc">Last edited — oldest first</option>
      </select></label>
      <p data-field="list-status" role="status"></p>
      ${pagination}
      <ul data-field="list" class="motion-library-list" aria-label="Training examples"></ul>
      ${pagination}
      <fieldset data-field="editor" hidden>
        <legend>Edit training example</legend>
        <label>Title <input data-field="title"></label>
        <label>Training request <textarea data-field="request" rows="2"></textarea></label>
        <label>Motion commands (JSON) <textarea data-field="program" rows="18" spellcheck="false"></textarea></label>
        <p class="field-help">Commands run in order. Edit face expressions, joint targets, offsets and durations here.</p>
        <details><summary>Recorded training context</summary><pre data-field="context"></pre></details>
        <p data-field="qualification"></p>
        <div class="motion-library-actions">
          <button type="button" data-action="save">Save training example</button>
          <button type="button" data-action="run">Send motion to robot</button>
        </div>
        <p>Playback uses the commands currently in the editor, including unsaved changes. Save to include them in future training exports. Saving does not retrain the model.</p>
        <p data-field="edit-status" role="status"></p>
        <p data-field="play-status" role="status"></p>
      </fieldset>
    </div>`;
  host.append(panel);
  const field = name => panel.querySelector(`[data-field="${name}"]`);
  const button = name => panel.querySelector(`[data-action="${name}"]`);
  let page = 1, pages = 1, search = "", sort = "name_asc", selected = null, dirty = false;
  let listVersion = 0, selectionVersion = 0, displayedRobot = null;
  const jobs = new Map();

  async function api(url, payload) {
    let options;
    if (payload) {
      const sessionResponse = await fetch("/api/session");
      if (!sessionResponse.ok) throw new Error("Sign in to Body Control to save or play a motion.");
      const session = await sessionResponse.json();
      options = {method: "POST", headers: {"Content-Type": "application/json", "X-Ainekio-CSRF": session.csrf},
        body: JSON.stringify(payload)};
    }
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || response.statusText);
    return result;
  }

  async function loadPage(target) {
    const version = ++listVersion;
    field("list-status").textContent = "Loading training examples…";
    try {
      const result = await api(`/api/motion-library?page=${target}&search=${encodeURIComponent(search)}&sort=${encodeURIComponent(sort)}`);
      if (version !== listVersion) return;
      page = result.page; pages = result.pages;
      field("list").replaceChildren();
      for (const item of result.items) {
        const li = document.createElement("li");
        const choose = document.createElement("button");
        choose.type = "button";
        choose.dataset.action = "select";
        choose.dataset.id = item.id;
        choose.textContent = item.title;
        choose.setAttribute("aria-pressed", String(selected?.id === item.id));
        const family = document.createElement("small");
        const date = value => new Date(value).toLocaleString();
        family.textContent = `${item.family.replaceAll("_", " ")} · Added ${item.added_at ? date(item.added_at) : "date unavailable"} · ${item.edited_at ? "Edited " + date(item.edited_at) : "Not edited"}`;
        li.append(choose, family); field("list").append(li);
      }
      for (const label of panel.querySelectorAll('[data-field="page"]')) label.textContent = `Page ${page} of ${pages}`;
      for (const action of ["first", "previous", "next", "last"]) {
        for (const control of panel.querySelectorAll(`[data-action="${action}"]`)) {
          control.disabled = ["first", "previous"].includes(action) ? page <= 1 : page >= pages;
        }
      }
      field("list-status").textContent = `${result.total} ${result.total === 1 ? "example" : "examples"} · ${result.page_size} per page`;
    } catch (error) {
      if (version === listVersion) field("list-status").textContent = error.message;
    }
  }

  function showExample(example) {
    selected = example; dirty = false;
    field("editor").hidden = false;
    field("title").value = example.title;
    field("request").value = example.request;
    field("program").value = JSON.stringify(example.program, null, 2);
    let context = example.example.query;
    try { context = JSON.parse(context); } catch (_) { /* Plain requests have no extra context. */ }
    field("context").textContent = JSON.stringify(context, null, 2);
    field("qualification").textContent = example.physical_qualification
      ? "This saved version has an operator-approved physical trial."
      : "This saved version has no operator-approved physical trial.";
    field("edit-status").textContent = `Saved version ${example.revision}`;
    for (const item of panel.querySelectorAll('[data-action="select"]')) {
      item.setAttribute("aria-pressed", String(item.dataset.id === example.id));
    }
  }

  panel.addEventListener("input", event => {
    if (["title", "request", "program"].includes(event.target.dataset.field)) {
      dirty = true;
      field("edit-status").textContent = "Unsaved changes";
    }
  });
  window.addEventListener("beforeunload", event => {
    if (dirty) { event.preventDefault(); event.returnValue = ""; }
  });
  field("search-form").addEventListener("submit", event => {
    event.preventDefault(); search = field("search").value.trim(); void loadPage(1);
  });
  field("sort").addEventListener("change", () => {
    sort = field("sort").value;
    return loadPage(1);
  });
  window.renderMotionLibraryStatus = (status, robot) => {
    displayedRobot = robot;
    button("run").disabled = !robot;
    const trial = jobs.get(robot);
    const job = trial && status?.jobs?.[trial.id];
    field("play-status").textContent = job
      ? `${trial.title} on ${robot}: ${job.state}${job.error ? " — " + job.error : ""} · ${job.completed_commands || 0} commands completed`
      : trial ? `${trial.title} submitted to ${robot}.` : robot ? `Selected robot: ${robot}` : "Select a robot for playback.";
  };

  panel.addEventListener("click", async event => {
    const target = event.target.closest("[data-action]");
    if (!target || target.disabled) return;
    const action = target.dataset.action;
    try {
      if (action === "open") {
        const opened = field("browser").hidden;
        field("browser").hidden = !opened;
        target.setAttribute("aria-expanded", String(opened));
        target.textContent = opened ? "Hide training data" : "View training data";
        if (opened) await loadPage(page);
      } else if (["first", "previous", "next", "last"].includes(action)) {
        await loadPage(action === "first" ? 1 : action === "last" ? pages : page + (action === "next" ? 1 : -1));
        field("list-status").scrollIntoView({block: "nearest"});
      } else if (action === "select") {
        if (dirty && !window.confirm("Discard unsaved edits and open this example?")) return;
        const version = ++selectionVersion;
        field("editor").disabled = true;
        field("edit-status").textContent = "Loading example…";
        try {
          const result = await api(`/api/motion-library?id=${encodeURIComponent(target.dataset.id)}`);
          if (version === selectionVersion) {
            showExample(result);
            field("editor").scrollIntoView({block: "start", behavior: "smooth"});
          }
        } finally {
          if (version === selectionVersion) field("editor").disabled = false;
        }
      } else if (action === "save" || action === "run") {
        if (!selected) return;
        const program = JSON.parse(field("program").value);
        const request = field("request").value;
        if (action === "save") {
          const version = ++selectionVersion;
          // Keep the submitted edit stable while the atomic save is in flight.
          field("editor").disabled = true;
          try {
            const result = await api("/api/motion-library", {operation: "save", id: selected.id,
              revision: selected.revision, title: field("title").value, request, program});
            if (version === selectionVersion) {
              showExample(result); field("edit-status").textContent = "Saved to training data.";
              await loadPage(page);
            }
          } finally {
            if (version === selectionVersion) field("editor").disabled = false;
          }
        } else {
          const robot = document.getElementById("robot-select").value;
          if (!robot) throw new Error("Select a robot for playback.");
          target.disabled = true;
          try {
            const title = field("title").value;
            const result = await api("/api/motion-library", {operation: "run", id: selected.id,
              robot_id: robot, request, program});
            jobs.set(robot, {id: result.job_id, title});
            if (robot === displayedRobot) field("play-status").textContent = `${title} submitted to ${robot}.`;
          } finally { target.disabled = !document.getElementById("robot-select").value; }
        }
      }
    } catch (error) {
      field(selected ? "edit-status" : "list-status").textContent = error.message;
    }
  });
}());

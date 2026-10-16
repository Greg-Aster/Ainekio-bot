/* Standalone browser UI; deliberately has no network or robot-control calls. */
(() => {
  "use strict";
  const M = LegMechanics,
    R = AinekioRobotGeometry,
    $ = (id) => document.getElementById(id);
  const clone = (x) => JSON.parse(JSON.stringify(x)),
    esc = (s) =>
      String(s).replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          }[c])
      );
  const fmt = (x, n = 1) => (Number.isFinite(x) ? x.toFixed(n) : "—");
  const colors = {
    carrier: "#63d8c7",
    crank: "#ffb36c",
    rod: "#c1b3ff",
    lower: "#e6e9d3",
    foot: "#8cb6d0",
  };
  const fresh = () => ({
    g: { ...R.dimensions, footAngle: 0, kneeBranch: -1, crankBranch: -1 },
    p: {
      stroke: 32,
      center: 0,
      clearance: 45,
      lift: 8,
      period: 1.8,
      duty: 0.8,
      mass: 566,
      supports: 3,
      push: 0,
      travel: 230,
    },
    mounts: clone(R.mounts),
    selected: 0,
    fixed: true,
    mode: "path",
    alpha: R.neutral.alpha,
    theta: R.neutral.theta,
    closureBranch: 1,
    view: "leg",
  });
  let state = fresh(),
    analysis,
    phase = 0.12,
    playing = false,
    lastTime = 0,
    comparisons = [],
    controls = [];
  function control(
    parent,
    label,
    key,
    min,
    max,
    step,
    read,
    write,
    locked = false
  ) {
    const div = document.createElement("div");
    div.className = "control";
    div.innerHTML = `<label for="${key}">${esc(
      label
    )}</label><input id="${key}" type="number" step="${step}" aria-label="${esc(
      label
    )}"><input type="range" min="${min}" max="${max}" step="${step}" aria-label="${esc(
      label
    )} slider">`;
    const number = div.querySelector("[type=number]"),
      range = div.querySelector("[type=range]");
    function change(v) {
      write(Number(v));
      number.value = v;
      range.value = v;
      recalculate();
    }
    number.addEventListener("input", () => {
      if (number.value !== "" && Number.isFinite(number.valueAsNumber))
        change(number.value);
    });
    range.addEventListener("input", () => change(range.value));
    $(parent).append(div);
    controls.push(() => {
      number.value = Number(read().toFixed(4));
      range.value = read();
      number.disabled = range.disabled = locked && state.fixed;
    });
  }
  function setup() {
    [
      ["Lower leg · knee to foot", "leg", 15, 100],
      ["Carrier · shaft to knee", "carrier", 15, 100],
      ["Connecting rod", "rod", 10, 120],
      ["Pickup · knee to rod", "pickup", 8, 70],
      ["Crank · shaft to rod", "crank", 10, 70],
      ["Foot angle · 0° opposite pickup, ±180° same side", "footAngle", -180, 180],
    ].forEach(([l, k, a, b]) =>
      control(
        "geometry-controls",
        l,
        k,
        a,
        b,
        0.5,
        () => state.g[k],
        (v) => (state.g[k] = v)
      )
    );
    [
      ["Crank shaft X from carrier", "shaftX", -80, 80],
      ["Crank shaft Z from carrier", "shaftZ", -60, 80],
    ].forEach(([l, k, a, b]) =>
      control(
        "shaft-controls",
        l,
        k,
        a,
        b,
        0.5,
        () => state.g[k],
        (v) => (state.g[k] = v),
        true
      )
    );
    R.mounts.forEach((m, i) => $("leg-select").add(new Option(m.name, i)));
    [
      ["Carrier shaft · body X", "mountX", 0, -150, 150],
      ["Carrier shaft · body Z", "mountZ", 1, 0, 150],
    ].forEach(([l, k, axis, a, b]) =>
      control(
        "mount-controls",
        l,
        k,
        a,
        b,
        0.5,
        () => state.mounts[state.selected].carrier[axis],
        (v) => (state.mounts[state.selected].carrier[axis] = v),
        true
      )
    );
    [
      ["Body clearance", "clearance", 0, 100, 0.5],
      ["Planted stride", "stroke", 0, 120, 1],
      ["Foot centre ahead of carrier", "center", -70, 70, 0.5],
      ["Swing lift", "lift", 0, 40, 0.5],
      ["Cycle duration · seconds", "period", 0.3, 5, 0.05],
      ["Grounded fraction", "duty", 0.4, 0.9, 0.01],
      ["Available servo excursion · °", "travel", 30, 270, 1],
    ].forEach(([l, k, a, b, s]) =>
      control(
        "path-controls",
        l,
        k,
        a,
        b,
        s,
        () => state.p[k],
        (v) => (state.p[k] = v)
      )
    );
    [
      ["Robot mass · g", "mass", 100, 2000, 1],
      ["Supporting legs", "supports", 1, 4, 1],
      ["Horizontal force / leg · N", "push", -5, 5, 0.1],
    ].forEach(([l, k, a, b, s]) =>
      control(
        "load-controls",
        l,
        k,
        a,
        b,
        s,
        () => state.p[k],
        (v) => (state.p[k] = v)
      )
    );
    [
      ["Carrier angle · °", "alpha"],
      ["Crank angle · °", "theta"],
    ].forEach(([l, k]) =>
      control(
        "pose-controls",
        l,
        k,
        -180,
        180,
        0.5,
        () => state[k],
        (v) => (state[k] = v)
      )
    );
    [
      [
        "Knee side",
        "kneeBranch",
        () => state.g.kneeBranch,
        (v) => (state.g.kneeBranch = v),
      ],
      [
        "Crank solution",
        "crankBranch",
        () => state.g.crankBranch,
        (v) => (state.g.crankBranch = v),
      ],
      [
        "Joint-pose closure",
        "closureBranch",
        () => state.closureBranch,
        (v) => (state.closureBranch = v),
      ],
    ].forEach(([label, k, read, write]) => {
      const div = document.createElement("label");
      div.className = "select-label";
      div.textContent = label;
      const select = document.createElement("select");
      select.id = k;
      select.add(new Option("Branch −1", -1));
      select.add(new Option("Branch +1", 1));
      select.onchange = () => {
        write(+select.value);
        recalculate();
      };
      div.append(select);
      $("branch-controls").append(div);
      controls.push(() => (select.value = read()));
    });
  }
  function moved() {
    return (
      Math.abs(state.g.shaftX - R.dimensions.shaftX) > 1e-6 ||
      Math.abs(state.g.shaftZ - R.dimensions.shaftZ) > 1e-6 ||
      state.mounts.some(
        (m, i) => M.norm(M.sub(m.carrier, R.mounts[i].carrier)) > 1e-6
      )
    );
  }
  const ground = () => R.bodyBottom - state.p.clearance;
  function parametersValid() {
    return (
      ["carrier", "crank", "rod", "pickup", "leg"].every(
        (k) => state.g[k] > 0
      ) &&
      state.p.period > 0 &&
      state.p.duty > 0 &&
      state.p.duty < 1 &&
      state.p.supports > 0 &&
      state.p.mass >= 0 &&
      state.p.stroke >= 0 &&
      state.p.lift >= 0 &&
      state.p.travel > 0
    );
  }
  function sync() {
    controls.forEach((fn) => fn());
    $("leg-select").value = state.selected;
    $("fixed-mounts").checked = state.fixed;
    $("mode").value = state.mode;
    $("view-leg").classList.toggle("selected", state.view === "leg");
    $("view-body").classList.toggle("selected", state.view === "body");
  }
  function recalculate() {
    sync();
    $("search-result").textContent =
      "Checks the full return path and entered servo excursion. Does not optimise torque or prove walking.";
    if (!parametersValid()) {
      analysis = null;
      $("pose-status").textContent =
        "Enter positive lengths, cycle duration, servo travel and supporting-leg count; grounded fraction must be between 0 and 1.";
      $("pose-status").className = "bad";
      $("metrics").innerHTML = "";
      $("diagram").innerHTML = "";
      $("angle-plot").innerHTML = $("torque-plot").innerHTML = "";
      return;
    }
    analysis = M.analyze(
      state.g,
      state.p,
      state.mounts[state.selected],
      ground()
    );
    $("ratios").textContent = `Relative to crank = 1: carrier ${fmt(
      state.g.carrier / state.g.crank,
      2
    )} · rod ${fmt(state.g.rod / state.g.crank, 2)} · pickup ${fmt(
      state.g.pickup / state.g.crank,
      2
    )} · leg ${fmt(state.g.leg / state.g.crank, 2)}.`;
    const selected = state.mounts[state.selected],
      base = R.mounts[state.selected],
      delta = M.sub(selected.carrier, base.carrier);
    $("mount-note").textContent = `Selected carrier shaft: body (${fmt(
      selected.carrier[0],
      2
    )}, ${fmt(selected.carrier[1], 2)}) mm. Shoulder axis: (${fmt(
      selected.shoulder[0],
      2
    )}, ${fmt(selected.shoulder[1], 2)}) mm. Carrier relocation ΔX ${fmt(
      delta[0]
    )}, ΔZ ${fmt(delta[1])} mm. Positive X = forward, positive Z = up.`;
    $("drawing-title").textContent = `${selected.name} · ${
      moved() ? "proposed mounts" : "installed mounts"
    }`;
    $("mount-status").textContent = moved()
      ? "MOUNT REDESIGN · ghost rings show original shaft positions"
      : "Shaft positions retained from repository geometry";
    const a = analysis,
      partial = !a.complete ? "Partial path · " : "",
      sum = a.rmsTorque[0] + a.rmsTorque[1];
    const cards = [
      [
        "Reachable cycle samples",
        `${a.validCount} / ${a.count}`,
        a.complete
          ? "All sampled positions close the linkage"
          : "Some requested foot positions cannot be reached",
        !a.complete,
      ],
      [
        "Carrier / crank excursion",
        `${fmt(a.ranges[0])}° / ${fmt(a.ranges[1])}°`,
        `${partial}${fmt((a.ranges[0] / state.p.travel) * 100, 0)}% / ${fmt(
          (a.ranges[1] / state.p.travel) * 100,
          0
        )}% of entered ${state.p.travel}°`,
        !a.travelFits,
      ],
      [
        "Peak support torque · C / K",
        a.torqueComplete
          ? `${fmt(a.peakTorque[0], 3)} / ${fmt(a.peakTorque[1], 3)}`
          : "Incomplete",
        `Nm · ${partial}${fmt(a.load, 2)} N upward per supporting leg`,
        !a.torqueComplete,
      ],
      [
        "RMS torque share · C / K",
        sum
          ? `${fmt((a.rmsTorque[0] / sum) * 100, 0)}% / ${fmt(
              (a.rmsTorque[1] / sum) * 100,
              0
            )}%`
          : "—",
        `${partial}Magnitude shares, not equal motor power`,
        false,
      ],
      [
        "Peak joint speed · C / K",
        `${fmt(a.speeds[0], 0)} / ${fmt(a.speeds[1], 0)}`,
        `${partial}°/s at ${fmt(
          state.p.period,
          2
        )} s per cycle · swing included`,
        false,
      ],
      [
        "Lowest planted leg angle",
        `${fmt(a.minLegAngle)}°`,
        `${partial}From horizontal · rod/pickup angle min ${fmt(
          a.minOutputAngle
        )}°`,
        false,
      ],
    ];
    $("metrics").innerHTML = cards
      .map(
        ([l, v, d, b]) =>
          `<div class="metric ${b ? "bad" : ""}"><div class="label">${esc(
            l
          )}</div><div class="value">${esc(v)}</div><div class="detail">${esc(
            d
          )}</div></div>`
      )
      .join("");
    drawPlots();
    draw();
  }
  function current() {
    const mount = state.mounts[state.selected];
    if (state.mode === "pose")
      return M.forward(
        state.g,
        M.rad(state.alpha),
        M.rad(state.theta),
        state.closureBranch
      );
    const t = M.path(state.p, phase, mount, ground());
    return {
      ...M.inverse(state.g, M.bodyToLocal(mount, t.body)),
      stance: t.stance,
      target: t.body,
    };
  }
  function draw() {
    if (!analysis) return;
    const s = current(),
      mount = state.mounts[state.selected],
      world = (p) => M.localToBody(mount, p),
      bodyView = state.view === "body";
    const all = analysis.samples.flatMap((q) =>
      q.ok
        ? [
            world(q.O),
            world(q.C),
            world(q.D),
            world(q.E),
            world(q.P),
            world(q.T),
          ]
        : [q.target]
    );
    if (s.ok)
      all.push(...["O", "C", "D", "E", "P", "T"].map((k) => world(s[k])));
    if (bodyView)
      all.push(
        ...R.bodyOutline,
        [0, ground()],
        R.com,
        ...state.mounts.map((m) => m.carrier)
      );
    else all.push(world([0, 0]), world([state.g.shaftX, state.g.shaftZ]));
    let minX = Math.min(...all.map((p) => p[0])) - 18,
      maxX = Math.max(...all.map((p) => p[0])) + 18,
      minZ = Math.min(ground() - 12, ...all.map((p) => p[1])) - 10,
      maxZ = Math.max(...all.map((p) => p[1])) + 14;
    const width = $("diagram").clientWidth < 600 ? 600 : 1000;
    $("diagram").setAttribute("viewBox", `0 0 ${width} 470`);
    const scale = Math.min((width - 120) / (maxX - minX), 360 / (maxZ - minZ)),
      cx = (minX + maxX) / 2,
      cz = (minZ + maxZ) / 2;
    const screen = (p) => [
        width / 2 + (p[0] - cx) * scale,
        230 - (p[1] - cz) * scale,
      ],
      pt = (p) =>
        screen(p)
          .map((x) => x.toFixed(2))
          .join(",");
    const line = (a, b, color, width = 3, dash = "") =>
      `<line x1="${screen(a)[0]}" y1="${screen(a)[1]}" x2="${
        screen(b)[0]
      }" y2="${screen(b)[1]}" stroke="${color}" stroke-width="${width}" ${
        dash ? `stroke-dasharray="${dash}"` : ""
      } stroke-linecap="round"/>`;
    const text = (p, t, color = "#c1d0cc", size = 12) =>
      `<text x="${screen(p)[0]}" y="${
        screen(p)[1]
      }" fill="${color}" font-size="${size}" text-anchor="middle">${esc(
        t
      )}</text>`;
    let svg = "";
    for (let x = Math.ceil(minX / 20) * 20; x <= maxX; x += 20)
      svg += line([x, minZ], [x, maxZ], "#293e40", 1);
    for (let z = Math.ceil(minZ / 20) * 20; z <= maxZ; z += 20)
      svg += line([minX, z], [maxX, z], "#293e40", 1);
    svg +=
      `<rect x="0" y="${
        screen([0, ground()])[1]
      }" width="${width}" height="470" fill="#0a1415" opacity=".6"/>` +
      line([minX, ground()], [maxX, ground()], "#678c83", 2);
    svg += text([minX + 18, ground() - 7], "GROUND", "#8aa7a0", 10);
    if (bodyView) {
      svg += `<polygon points="${R.bodyOutline
        .map(pt)
        .join(
          " "
        )}" fill="#566663" fill-opacity=".25" stroke="#8a9992" stroke-width="1.5"/>`;
      svg += line(
        [R.com[0], ground()],
        [R.com[0], R.com[1]],
        "#f3d28d",
        1,
        "4 5"
      );
      svg +=
        `<circle cx="${screen(R.com)[0]}" cy="${
          screen(R.com)[1]
        }" r="5" fill="#f3d28d"/>` +
        text([R.com[0], R.com[1] + 6], "Assumed COM", "#f3d28d", 10);
      state.mounts.forEach((m, i) => {
        const o = m.carrier,
          c = M.localToBody(m, [state.g.shaftX, state.g.shaftZ]);
        svg += line(m.shoulder, o, "#718582", 1, "3 3");
        for (const p of [o, c])
          svg += `<circle cx="${screen(p)[0]}" cy="${
            screen(p)[1]
          }" r="5" fill="none" stroke="#8b9e97"/>`;
        if (i % 2 === 0)
          svg += text(
            [o[0], o[1] + 20],
            m.name.replace(" left", " pair"),
            "#a6b9b8",
            10
          );
      });
      svg += text(
        [maxX - 20, R.bodyBottom + 4],
        `Clearance ${fmt(state.p.clearance)} mm`,
        "#8aa7a0",
        10
      );
    }
    const original = R.mounts[state.selected];
    if (moved())
      for (const p of [original.carrier, original.crank])
        svg += `<circle cx="${screen(p)[0]}" cy="${
          screen(p)[1]
        }" r="11" fill="none" stroke="#d59c6c" stroke-dasharray="3 4"/>`;
    analysis.samples.forEach((q) => {
      const p = screen(q.target);
      svg += `<circle cx="${p[0]}" cy="${p[1]}" r="${q.ok ? 1.4 : 2.5}" fill="${
        q.ok ? colors.foot : "#ff8b83"
      }" opacity=".75"/>`;
    });
    if (s.ok) {
      const w = Object.fromEntries(
        ["O", "C", "D", "E", "P", "T"].map((k) => [k, world(s[k])])
      );
      svg +=
        line(w.O, w.C, "#79938b", 2, "5 5") +
        line(w.O, w.D, colors.carrier, 6) +
        line(w.C, w.P, colors.crank, 6) +
        line(w.P, w.E, colors.rod, 4) +
        line(w.D, w.E, colors.lower, 5) +
        line(w.D, w.T, colors.lower, 6);
      for (const [a, b, value, c] of [
        ["O", "D", state.g.carrier, colors.carrier],
        ["C", "P", state.g.crank, colors.crank],
        ["P", "E", state.g.rod, colors.rod],
        ["D", "E", state.g.pickup, colors.lower],
        ["D", "T", state.g.leg, colors.lower],
      ]) {
        const mid = M.mul(M.add(w[a], w[b]), 0.5);
        svg += text([mid[0], mid[1] + 4], fmt(value), c, 12);
      }
      for (const [k, p] of Object.entries(w)) {
        const xy = screen(p);
        svg += `<circle cx="${xy[0]}" cy="${xy[1]}" r="${
          k === "O" || k === "C" ? 8 : 4.5
        }" fill="#172426" stroke="${
          k === "T" ? colors.foot : "#e6e9d3"
        }" stroke-width="2"/>`;
        const delta =
          k === "C"
            ? [0, 8]
            : k === "O"
            ? [8, 0]
            : k === "T"
            ? [0, -8]
            : [-6, 3];
        svg += text(M.add(p, delta), k, "#f0f2e9", 12);
      }
      const qtext = `Carrier ${fmt(M.deg(s.alpha))}° · crank ${fmt(
        M.deg(s.theta)
      )}° · leg ${fmt(s.legAngle)}° above horizontal`;
      $("pose-status").textContent =
        qtext +
        (analysis.branchChanges
          ? " · Assembly branch changes within this path"
          : "") +
        (!analysis.complete ? " · Other cycle positions are unreachable" : "");
      $("pose-status").className =
        analysis.complete && !analysis.branchChanges ? "" : "bad";
    } else {
      $("pose-status").textContent = s.reason;
      $("pose-status").className = "bad";
      if (s.target) {
        const a = screen(s.target);
        svg += `<path d="M${a[0] - 6},${
          a[1] - 6
        }l12,12m0,-12l-12,12" stroke="#ff8b83" stroke-width="3"/>`;
      }
    }
    svg +=
      width === 600
        ? '<text x="22" y="438" fill="#a6b9b8" font-size="12">O carrier · C crank · D knee</text><text x="22" y="457" fill="#a6b9b8" font-size="12">E pickup · P crank pin · T point foot</text>'
        : '<text x="22" y="448" fill="#a6b9b8" font-size="11">O carrier shaft · C crank shaft · D knee · E pickup · P crank pin · T point foot</text>';
    svg += `<text x="${
      width - 22
    }" y="24" text-anchor="end" fill="#a6b9b8" font-size="10">20 mm grid · +X forward →</text>`;
    $("diagram").innerHTML = svg;
    $("phase").value = Math.round(phase * 999);
    $("phase-label").textContent =
      state.mode === "pose"
        ? "Direct joint pose"
        : `${Math.round(phase * 100)}% · ${
            phase < state.p.duty ? "stance" : "swing"
          }`;
    document.querySelectorAll(".phase-marker").forEach((el) => {
      el.setAttribute("x1", 42 + phase * 423);
      el.setAttribute("x2", 42 + phase * 423);
    });
  }
  function plot(id, series, positive = false) {
    const values = series.flat().filter(Number.isFinite);
    let lo = positive ? 0 : Math.min(0, ...values),
      hi = Math.max(0, ...values);
    if (hi - lo < 0.001) hi = lo + 1;
    const y = (v) => 150 - ((v - lo) / (hi - lo)) * 120;
    let out = `<rect x="42" y="20" width="${
      423 * state.p.duty
    }" height="130" fill="#304743" opacity=".7"/>`;
    for (let k = 0; k < 4; k++) {
      const v = lo + ((hi - lo) * k) / 3;
      out += `<line x1="42" y1="${y(v)}" x2="465" y2="${y(
        v
      )}" stroke="#3b4d4e"/><text x="35" y="${
        y(v) + 4
      }" text-anchor="end" fill="#a6b9b8" font-size="10">${fmt(
        v,
        positive ? 3 : 0
      )}</text>`;
    }
    series.forEach((arr, j) => {
      let d = "",
        active = false;
      arr.forEach((v, i) => {
        if (!Number.isFinite(v)) {
          active = false;
          return;
        }
        d += `${active ? "L" : "M"}${42 + (i / arr.length) * 423},${y(v)} `;
        active = true;
      });
      out += `<path d="${d}" fill="none" stroke="${
        j ? colors.crank : colors.carrier
      }" stroke-width="2"/>`;
    });
    out +=
      '<text x="42" y="171" fill="#a6b9b8" font-size="10">0%</text><text x="465" y="171" text-anchor="end" fill="#a6b9b8" font-size="10">100% cycle</text>';
    out += `<line class="phase-marker" x1="${42 + phase * 423}" x2="${
      42 + phase * 423
    }" y1="20" y2="150" stroke="#e6e9d3" opacity=".6" stroke-dasharray="3 3"/>`;
    $(id).innerHTML = out;
  }
  function drawPlots() {
    const first = analysis.samples.find((s) => s.ok);
    plot(
      "angle-plot",
      [0, 1].map((j) =>
        analysis.samples.map((s) => (s.ok ? M.deg(s.q[j] - first.q[j]) : NaN))
      )
    );
    plot(
      "torque-plot",
      [0, 1].map((j) =>
        analysis.samples.map((s) => (s.torque ? Math.abs(s.torque[j]) : NaN))
      ),
      true
    );
  }
  function comparisonTable() {
    $("comparisons").innerHTML =
      comparisons
        .map((c, i) => {
          const a = c.result,
            g = c.state.g;
          return `<tr><td><button data-load="${i}">${esc(
            c.name
          )}</button></td><td>${[g.leg, g.carrier, g.rod, g.pickup, g.crank]
            .map((v) => fmt(v))
            .join(" / ")}</td><td>${
            c.moved ? "Relocated" : "Installed"
          }</td><td>${fmt(c.state.p.stroke)} mm</td><td>${a.validCount}/${
            a.count
          }</td><td>${a.ranges
            .map((v) => fmt(v) + "°")
            .join(" / ")}</td><td>${a.peakTorque
            .map((v) => fmt(v, 3))
            .join(" / ")}${
            a.torqueComplete ? "" : "*"
          }</td><td><button data-delete="${i}" aria-label="Remove design ${
            i + 1
          }">×</button></td></tr>`;
        })
        .join("") ||
      '<tr><td colspan="8">Keep a design to compare it with the next change.</td></tr>';
    $("comparisons")
      .querySelectorAll("[data-load]")
      .forEach(
        (b) =>
          (b.onclick = () => {
            state = clone(comparisons[+b.dataset.load].state);
            recalculate();
          })
      );
    $("comparisons")
      .querySelectorAll("[data-delete]")
      .forEach(
        (b) =>
          (b.onclick = () => {
            comparisons.splice(+b.dataset.delete, 1);
            comparisonTable();
          })
      );
  }
  function download(name, type, text) {
    const a = document.createElement("a"),
      url = URL.createObjectURL(new Blob([text], { type }));
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const resultSummary = () => {
    const { samples, ...rest } = analysis;
    return rest;
  };
  $("reset").onclick = () => {
    state = fresh();
    playing = false;
    $("play").textContent = "▶ Play";
    recalculate();
  };
  $("fixed-mounts").onchange = () => {
    state.fixed = $("fixed-mounts").checked;
    if (state.fixed) {
      state.mounts = clone(R.mounts);
      state.g.shaftX = R.dimensions.shaftX;
      state.g.shaftZ = R.dimensions.shaftZ;
    }
    recalculate();
  };
  $("leg-select").onchange = () => {
    state.selected = +$("leg-select").value;
    recalculate();
  };
  $("mode").onchange = () => {
    state.mode = $("mode").value;
    recalculate();
  };
  $("view-leg").onclick = () => {
    state.view = "leg";
    sync();
    draw();
  };
  $("view-body").onclick = () => {
    state.view = "body";
    sync();
    draw();
  };
  $("phase").oninput = () => {
    phase = +$("phase").value / 1000;
    draw();
  };
  $("play").onclick = () => {
    playing = !playing;
    $("play").textContent = playing ? "Ⅱ Pause" : "▶ Play";
  };
  $("find-stroke").onclick = () => {
    if (!analysis) return;
    const best = M.longestStroke(
      state.g,
      state.p,
      state.mounts[state.selected],
      ground()
    );
    $("search-result").textContent =
      best === null
        ? "No complete sampled cycle fits at this clearance, centre, branch and excursion."
        : `Largest tested centred stroke: ${best} mm (1 mm steps, 120 cycle samples). Torque is not a selection criterion. Enter this stroke to inspect it at 240 samples.`;
  };
  $("save-design").onclick = () => {
    if (!analysis) return;
    comparisons.push({
      name: `Design ${comparisons.length + 1} · ${fmt(state.g.leg, 0)} mm leg`,
      state: clone(state),
      result: resultSummary(),
      moved: moved(),
    });
    comparisonTable();
  };
  $("export-json").onclick = () => {
    if (!analysis) return;
    download(
      "ainekio-leg-design.json",
      "application/json",
      JSON.stringify(
        {
          schema: "ainekio.leg-calculator.v1",
          source: R.source,
          sourceSha256: R.sha256,
          state,
          results: resultSummary(),
          assumptions:
            "Planar point foot, neutral shoulder, equal support loads; no friction/inertia/collision/motor-capability model.",
        },
        null,
        2
      )
    );
  };
  $("export-csv").onclick = () => {
    if (!analysis) return;
    const header =
      "phase,stance,reachable,foot_body_x_mm,foot_body_z_mm,carrier_deg,crank_deg,carrier_torque_Nm,crank_torque_Nm,leg_angle_deg";
    download(
      "ainekio-leg-cycle.csv",
      "text/csv",
      header +
        "\n" +
        analysis.samples
          .map((s) =>
            [
              s.phase,
              s.stance,
              s.ok,
              ...s.target,
              s.ok ? M.deg(s.alpha) : "",
              s.ok ? M.deg(s.theta) : "",
              ...(s.torque || ["", ""]),
              s.ok ? s.legAngle : "",
            ].join(",")
          )
          .join("\n")
    );
  };
  $("export-svg").onclick = () =>
    download(
      "ainekio-leg-geometry.svg",
      "image/svg+xml",
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${$(
        "diagram"
      ).getAttribute(
        "viewBox"
      )}"><rect width="100%" height="100%" fill="#172426"/>${
        $("diagram").innerHTML
      }</svg>`
    );
  $("import-json").onchange = async () => {
    try {
      const file = $("import-json").files[0];
      if (!file) return;
      const d = JSON.parse(await file.text());
      if (d.schema !== "ainekio.leg-calculator.v1")
        throw Error("Use a design exported by this calculator.");
      const candidate = d.state;
      if (
        !candidate ||
        !candidate.g ||
        !candidate.p ||
        !Array.isArray(candidate.mounts) ||
        candidate.mounts.length !== 4 ||
        !Number.isInteger(candidate.selected) ||
        candidate.selected < 0 ||
        candidate.selected > 3
      )
        throw Error("Missing geometry or mount data.");
      const defaults = fresh();
      if (
        !Number.isFinite(candidate.alpha) ||
        !Number.isFinite(candidate.theta) ||
        ![-1, 1].includes(candidate.closureBranch) ||
        !["path", "pose"].includes(candidate.mode) ||
        !["leg", "body"].includes(candidate.view)
      )
        throw Error("Invalid view or joint pose.");
      for (const group of ["g", "p"])
        for (const key of Object.keys(defaults[group]))
          if (!Number.isFinite(candidate[group][key]))
            throw Error("Non-numeric " + key);
      for (const m of candidate.mounts)
        if (
          !m.carrier?.every(Number.isFinite) ||
          m.carrier.length !== 2 ||
          !m.basis?.flat().every(Number.isFinite) ||
          m.basis.length !== 2 ||
          m.basis.some((row) => row.length !== 2) ||
          Math.abs(
            m.basis[0][0] * m.basis[1][1] - m.basis[0][1] * m.basis[1][0]
          ) < 1e-8
        )
          throw Error("Invalid mount coordinates.");
      if (
        ![-1, 1].includes(candidate.g.kneeBranch) ||
        ![-1, 1].includes(candidate.g.crankBranch)
      )
        throw Error("Assembly branch must be −1 or +1.");
      const old = state;
      state = { ...defaults, ...candidate };
      if (!parametersValid()) {
        state = old;
        throw Error("Invalid path or dimensions.");
      }
      state.mounts = state.mounts.map((m, i) => ({
        ...clone(R.mounts[i]),
        carrier: m.carrier,
        basis: m.basis,
      }));
      if (moved()) state.fixed = false;
      recalculate();
      $("file-status").textContent =
        d.sourceSha256 === R.sha256
          ? "Design imported."
          : "Imported design uses a different geometry snapshot; chassis outline remains this calculator’s snapshot.";
    } catch (e) {
      $("file-status").textContent = "Import failed: " + e.message;
    }
  };
  $(
    "provenance"
  ).textContent = `Shaft/chassis snapshot: ${R.source} (${R.snapshotDate}), SHA-256 ${R.sha256}. Dimensions 55 / 35 / 38 / 28 / 20 mm. COM is the repository’s assumed datum, not a mass measurement.`;
  function animate(time) {
    const dt = lastTime ? Math.min(0.1, (time - lastTime) / 1000) : 0;
    lastTime = time;
    if (playing && analysis && state.mode === "path") {
      phase = (phase + dt / state.p.period) % 1;
      draw();
    }
    requestAnimationFrame(animate);
  }
  setup();
  window.addEventListener("resize", draw);
  recalculate();
  comparisonTable();
  requestAnimationFrame(animate);
  // Exposed for inspecting/exporting this local calculator, never hardware.
  window.legCalculator = {
    getState: () => clone(state),
    getAnalysis: () => analysis,
    setState: (s) => {
      state = clone(s);
      recalculate();
    },
  };
})();

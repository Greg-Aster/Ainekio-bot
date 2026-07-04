---
title: "About Ainekio"
description: "Ainekio is a small robot companion project powered by MetaHuman OS."
---

# About Ainekio

Ainekio is a robot familiar project: a small physical companion connected to MetaHuman OS. The goal is to give the software a careful physical presence without blurring the boundaries between AI, hardware, firmware, cloud services, and safety-critical robot behavior.

## What This Site Is For

This site is the project notebook for public-facing progress:

- build logs and hardware notes
- firmware and control architecture decisions
- MetaHuman OS integration notes
- safety constraints and behavior boundaries
- photos, demos, and test results when they are ready

## Core Boundaries

Ainekio should use semantic robot commands rather than raw AI-generated servo angles. Hardware actions need clear safety gates, predictable limits, and room for human review.

Personal MetaHuman data, captured media, runtime logs, and secrets should stay out of the public repo.

## Current References

- Project repo: [Greg-Aster/Ainekio-bot](https://github.com/Greg-Aster/Ainekio-bot)
- MetaHuman OS repo: [Greg-Aster/metahuman-os](https://github.com/Greg-Aster/metahuman-os)
- Current test body: [dorianborian/sesame-robot](https://github.com/dorianborian/sesame-robot)

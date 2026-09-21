# Preview resource policy

The owner stopped the first parallel render attempt after RAM exhaustion. The
owner then explicitly authorized resuming with resource controls.

- One background Blender worker at a time, two render threads.
- User-service cgroup: `MemoryHigh=7G`, `MemoryMax=10G`, `MemorySwapMax=0`,
  `CPUQuota=150%`, `Nice=10`. A memory-limit failure kills this job, not Blender GUI.
- Supervisor stops the worker above 8 GiB resident memory or when host available
  RAM falls below 20 GiB. It also honors a `STOP_PREVIEWS` file in this directory.
- Each worker commits at most 12 frames, then exits. The next worker resumes
  from complete PNGs. Temporary PNGs are atomically renamed only after completion.
- Unused historic action copies are removed only inside the disposable rendering
  process. These cleanup changes are never saved into the robot `.blend`.
- Preview encoding uses two threads. ZIPs and hash checks stream files in chunks.

`cautious-render-status.json` records completed chunks and their measured peak
resident memory. The operating system also enforces the hard limit independently
of the Python monitoring process.

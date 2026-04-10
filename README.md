# Skills

A collection of [Codex](https://github.com/openai/codex) agent skills for Qualcomm Linux development workflows.
Each skill lives in its own directory and is described by a `SKILL.md` file that the agent reads at runtime.

---

## Available Skills

### [`qdl-flash-device`](./qdl-flash-device/)

> Flash a Qualcomm device end-to-end via EDL mode using TACDev and qdl.

**Use when:** asked to flash a device, enter EDL mode, or reflash partitions using `qdl` and meta/rawprogram XML files.

**What it does:**

1. Boots the target into EDL mode via a TAC (Test Automation Controller) device using the TACDev Python library.
2. Verifies the device appears in EDL mode (`lsusb`).
3. Flashes all partitions using `qdl` with the firehose ELF and auto-globbed `rawprogram*.xml` / `patch*.xml` files.
4. Powers the device back on via TACDev.

**Key features:**

- **Auto-downloads `qdl`** if not present — resolves the binary in order: `$QDL` env var → `/local/mnt/workspace/qdl` → `$PATH` → downloads from the [GitHub release](https://github.com/linux-msm/qdl/releases/download/v2.5/qdl-binary-ubuntu-24-x64.zip) automatically.
- **Multi-device aware** — when multiple EDL targets or TAC devices are connected, scripts print a numbered list and wait for the user to pick one before proceeding.
- **XML globbing** — `rawprogram*.xml` and `patch*.xml` are discovered automatically; no manual file listing needed.

**Scripts:**

| Script | Purpose |
|---|---|
| `scripts/boot_edl.py` | Send EDL boot command via TACDev |
| `scripts/flash.sh` | Run `qdl` to flash all partitions |
| `scripts/power_on.py` | Send power-on command via TACDev |

**Prerequisites:** TAC FT232 device on `/dev/ttyUSB0`, target device on USB, meta image directory with `prog_firehose_ddr.elf`.

---

### [`lore-patchset-automation`](./lore-patchset-automation/)

> Automate Linux patchset intake from [lore.kernel.org](https://lore.kernel.org) and normalise commit metadata.

**Use when:** asked to fetch/apply a lore patch series, keep mbox artifacts on failures, or mass-update applied patch commit metadata.

**What it does:**

1. Fetches a patch series from lore.kernel.org using `b4 am`.
2. Applies it to a target repo with `git am`.
3. Rewrites each applied commit to:
   - Prefix the subject with `UPSTREAM:` (if the patch is already in an upstream branch) or `FROMLIST:` (if not yet merged).
   - Enforce a `Signed-off-by:` trailer **before** the `Link:` trailer in every commit message.
   - Deduplicate sign-off lines.

**Key features:**

- **Upstream detection** — checks one or two configurable upstream branches; strips existing `UPSTREAM:` / `FROMLIST:` prefixes before comparing so re-runs are idempotent.
- **Safe failure handling** — on `git am` failure the mbox is kept on disk and the path is reported; on `b4` failure nothing is left behind.
- **Single-pass rewrite** — uses `git filter-branch` with a Python message-filter over the applied range for clean, atomic rewrites.
- **Identity-aware** — reads `user.name` / `user.email` from the target repo's git config; falls back to a default identity if unset.

**Prerequisites:** `b4` and `git` on `$PATH`, a target repo and an upstream repo accessible on the local filesystem.

---

## Repository Layout

```
skills/
├── README.md
├── lore-patchset-automation/
│   └── SKILL.md          # Full workflow instructions
└── qdl-flash-device/
    ├── SKILL.md          # Full workflow instructions
    ├── agents/           # Agent config (openai.yaml)
    └── scripts/
        ├── boot_edl.py
        ├── flash.sh
        └── power_on.py
```

---

## How Skills Work

Skills are loaded by the Codex agent at runtime. When a task matches a skill's description (or the user explicitly names it with `$skill-name`), the agent reads the corresponding `SKILL.md` and follows its workflow step by step.

- Instructions in `SKILL.md` take precedence over the agent's defaults for that task.
- Scripts in `scripts/` are run directly — the agent does not retype them.
- Assets and templates in a skill directory are reused rather than recreated.

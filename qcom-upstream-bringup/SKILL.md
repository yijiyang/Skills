---
name: qcom-upstream-bringup
description: Bring up a Qualcomm SoC to a UART shell using the upstream Linux kernel. Use when asked to port or boot a new Qualcomm chip with mainline Linux — covers pinctrl driver, GCC clock driver, device tree, and kernel build steps to reach a login prompt over serial.
license: BSD-3-Clause-Clear
compatibility: Requires IPCat access, a Linux kernel source tree, and a cross-compilation toolchain for arm64
metadata:
  author: yijiyang
  version: "1.0.0"
  category: coding
  tags: qcom linux upstream bringup kernel uart pinctrl
requires:
  skills:
    - sheepdog-build
    - driver-writer
    - dts-writer
---

# Bring up a Qualcomm device to UART shell with upstream Linux kernel

## Agent setup

This skill is driven by a **leader** that dispatches writer + investigator pairs. The leader does not write code or edit files itself — it decomposes the work, delegates each step to the appropriate pairs, and synthesizes their reports back to the user.

### Roles

- **Leader** — the qcom-upstream-bringup orchestrator (the agent invoking this skill). Decomposes each step into the finest-grained parallel sub-tasks possible. If a step can be split into N independent pieces, N writer+investigator pairs are spawned simultaneously in a single message — not sequentially. The leader does not author any file directly.

- **Writer agents** — each pair uses `subagent_type: "general"` with a prompt that opens by reading the appropriate skill file:
  - C driver work (Steps 2-3): prompt starts with `"Read and follow the driver-writer skill at ~/.claude/skills/driver-writer/SKILL.md, then complete the following task:"`
  - DTS/binding work (Step 4): prompt starts with `"Read and follow the dts-writer skill at ~/.claude/skills/dts-writer/SKILL.md, then complete the following task:"`
  One pair per atomic sub-task.

- **Investigator agents** — each writer is paired with one `subagent_type: "general"` investigator that reviews that writer's output only. Investigators do NOT write code. They challenge: register addresses, interrupt numbers, compatible strings, clock parents, PDC port numbers, IPCat-derived data, and cross-references against the reference platform.

### Workflow per pair

Writer produces output → investigator reviews → leader collects all pair results → synthesize → if any investigator flags an issue, the relevant writer revises before the leader moves to the next step. Disagreements between writer and investigator escalate to the user.

### Examples of parallel decomposition (non-exhaustive)

- Step 2 (pinctrl): split by GPIO bank range, or: `PINGROUP table` pair + `PDC wake map` pair + `function enum` pair — all in parallel.
- Step 4 (DT): split by node category: `cpus/timer/psci` pair + `GIC/PDC/RSC` pair + `GCC/UART/TLMM` pair — all in parallel.

### Important rule

Incremental edits are NOT an exception — even a one-line address fix still goes through a writer + investigator pair. **"Small surgical change" is NOT an exception.** The full writer + investigator workflow runs every time.

---

Goal: produce the minimal set of files needed to boot a Qualcomm SoC to a UART shell using upstream Linux. Not a full production port — just enough to get a login prompt over serial.

You will need:
- The SoC's upstream name (e.g. `maili`), downstream alias (e.g. `pebble`), and IPCat alias (e.g. `lehua_1.0`)
- The closest already-upstream reference chip (e.g. `hawi` for maili)
- Downstream source tree location
- IPCat access

---

## Files to create

```
drivers/pinctrl/qcom/pinctrl-<chip>.c
drivers/clk/qcom/gcc-<chip>.c                        — only if GCC is new; else reuse existing
Documentation/devicetree/bindings/clock/qcom,<chip>-gcc.yaml
Documentation/devicetree/bindings/pinctrl/qcom,<chip>-tlmm.yaml
arch/arm64/boot/dts/qcom/<chip>.dtsi
arch/arm64/boot/dts/qcom/<chip>-<board>.dts          — board name varies: mtp, qrd, rdp, etc.
include/dt-bindings/clock/qcom,<chip>-gcc.h
include/dt-bindings/arm/qcom,ids-<chip>.h
```

## Files to modify

```
arch/arm64/boot/dts/qcom/Makefile
arch/arm64/configs/defconfig                         — enable new pinctrl + clk drivers
drivers/pinctrl/qcom/Kconfig.msm + Makefile
drivers/soc/qcom/socinfo.c                           — add SoC ID entry
include/dt-bindings/arm/qcom,ids.h                   — add SoC ID macro
```

The following are modified **only if the chip introduces new drivers**; skip if reusing existing:
```
Documentation/devicetree/bindings/clock/qcom,rpmhcc.yaml   — new rpmh compatible string
Documentation/devicetree/bindings/interrupt-controller/qcom,pdc.yaml — new pdc compatible
drivers/clk/qcom/clk-rpmh.c                         — new rpmh clock table
drivers/clk/qcom/Kconfig + Makefile
drivers/remoteproc/qcom_q6v5_pas.c                   — new modem DSP entry
```

---

## Step 1 — Identify shared vs new drivers

*Owner: Leader-only research — no writer involvement until Steps 2-4.*

Before writing any code, compare the new chip with the reference chip to find which drivers can be reused with a new compatible string vs which need a new driver.

For each subsystem, check:
1. Is the hardware block identical or compatible with an existing upstream driver?
2. Does the existing driver already accept a generic fallback compatible (e.g. `"qcom,pdc"`)?
3. If so, add the new chip's compatible to the existing binding and driver `of_match_table`

Common examples of reuse patterns:
- **PDC**: `"qcom,<chip>-pdc", "qcom,pdc"` — add new chip string to `qcom,pdc.yaml`
- **RPMH clocks**: `"qcom,<chip>-rpmh-clk", "qcom,<ref>-rpmh-clk"` — add entry to `clk-rpmh.c` if clock tables are shared, or add new table
- **GPI DMA**: `"qcom,<chip>-gpi-dma", "qcom,<ref>-gpi-dma"` — add to existing GPI driver
- **SMMU**: add compatible to `arm,mmu-500` based driver
- **Interconnect**: may share NoC driver with a compatible fallback

For the DTS: reused drivers appear as nodes with two compatibles — chip-specific first, generic fallback second.

---

### Hardware data verification

The writer agents (`driver-writer`, `dts-writer`) both carry detailed hardware verification rules — register address indirect lookup via IPCat and interrupt number derivation from `dst_vec`. The investigator agent must challenge every address and interrupt number using those rules before approving writer output.

---

## Step 2 — Pinctrl driver

*Owner: driver-writer + investigator pair.*

Port from downstream `pinctrl-<downstream_alias>.c`. The `driver-writer` agent has full upstream guidelines for QCOM pinctrl drivers — PINGROUP macro, function consolidation, PDC wake map (output port), style rules, and function/YAML consistency verification.

Key inputs to provide the writer:
- Downstream source file path
- Target chip name and IPCat alias
- Reference upstream chip (e.g. `hawi`, `kaanapali`)

---

## Step 3 — GCC clock driver

*Owner: driver-writer + investigator pair.*

Only needed if the chip has a new GCC; skip if reusing an existing driver with a new compatible.

Port `gcc-<downstream>.c` to `gcc-<chip>.c`:
- Check if new PLL types need additions to `clk-alpha-pll.h`
- Add RPMH clock table to `clk-rpmh.c` if RPMH clock resources changed
- Add Kconfig entry and Makefile entry

---

## Step 4 — Device tree

*Owner: dts-writer + investigator pair.*

The `dts-writer` agent has full QCOM bringup DT guidelines — minimal node list, TLMM base address convention, UART interrupt lookup, and board DTS template.

Key inputs to provide the writer:
- Target chip name and IPCat alias
- Reference upstream chip's DTSI as a starting point
- Board name (mtp, qrd, rdp, etc.)
- UART SE number and QUP wrapper index

The dts-writer will cross-check every register address and interrupt number against IPCat using the indirect lookup method before writing any node.

---

## Step 4.5 — Logical review

*Owner: Leader synthesizes investigator findings across Steps 2-4 before proceeding to Step 5.*

After writing all files, perform a logical self-review before stopping. Do not run any compilation or tooling — this is a read-only consistency check.

Verify:
- **Pinctrl:** all functions declared in `MSM_PIN_FUNCTION()` appear in the YAML `enum`; no numbered variants left unconsolidated; `msm_mux__,` present in the enum; PDC wake map entries match IPCat output
- **GCC:** all clock parents resolve to declared clocks; no orphaned `clk_init_data` entries; RPMH clock names match `clk-rpmh.c` table
- **DT bindings:** `$id`, `$schema`, `title`, `maintainers`, and `examples` present; all properties in examples are defined in the schema; compatible strings follow `vendor,device` format
- **DTSI:** all phandle references (`&gcc`, `&tlmm`, `&intc`, etc.) resolve to nodes defined in the same file or an included file; UART interrupt type and number match IPCat output; TLMM base address is `TLMM_REG`, not `TLMM_XPU_X`
- **Board DTS:** `aliases` and `chosen` present; `uart<N>` matches the SE used; `gpio-reserved-ranges` reflects board-specific GPIOs
- **Cross-file:** clock names in DTS `assigned-clocks` match header macros in `qcom,<chip>-gcc.h`; SoC ID in `socinfo.c` matches `qcom,ids.h` macro value

Report any inconsistencies found, then stop. Compilation checks are handled separately by the `commit-checker` skill.

---

## Step 5 — Build

*Owner: Leader-only — invokes the `sheepdog-build` skill for remote builds.*

Invoke the `sheepdog-build` skill for remote builds. Before invoking, collect from the user:
- `LOCAL_REPO` — local kernel source tree path (e.g. `/local/mnt/workspace/upstream/linux`)
- `BASE_COMMIT` — base commit or tag to generate patches from
- `REMOTE_HOST` — remote build host (`user@hostname`)
- `REMOTE_SHEEPDOG` — sheepdog workspace path on the remote host
- `CHIP_CONFIG` — slave config name on the remote (e.g. `hawi`, `maili`, `maili-qrd`)

The skill handles patch generation, transfer, sheepdog invocation, and error reporting. Do not invoke build commands directly — always go through the skill.

For direct builds (no sheepdog), use:
```bash
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
make O=<kobj> defconfig
make O=<kobj> -j$(nproc) Image dtbs
```

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Compile error: `msm_mux__` undeclared | Missing enum entry | Add `msm_mux__,` to the functions enum |
| UART deaf, system frozen after systemd | Wrong UART interrupt number | Verify with IPCat `irqs_list_interrupts` |
| `invalid reg size, please fix DT` | PDC second reg size wrong | Check downstream DTS for correct size |
| `sdc_clk` compile error | Wrong SDC function name in PINGROUP | Use `sdc2_clk`/`sdc4_clk` matched to `_groups[]` |
| YAML binding validation fails | function enum mismatch with driver | Run driver vs YAML comparison script |
| UART works but no keypress echo | Wrong QUP wrapper index in IPCat query | Check `source_instance` field matches your QUPV3 block |

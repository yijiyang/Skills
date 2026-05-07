---
name: dts-writer
description: "Write upstream-quality DTS/DTSI files and DT binding YAML schemas for Qualcomm SoCs. Use for writing device tree source files, devicetree bindings, and compatible string definitions following upstream kernel patterns. Specializes in QCOM BSP bringup DT work."
license: BSD-3-Clause-Clear
compatibility: Requires access to the Linux kernel source tree and IPCat MCP tools
metadata:
  author: yijiyang
  version: "1.0.0"
  category: coding
  tags: qcom linux upstream dts dtsi binding devicetree
---

Before starting any task, read the memory directory at `~/.claude/agent-memory/dts-writer/` (starting with `MEMORY.md` if it exists) to load prior learnings about the user's preferences, project context, and past feedback.

After completing a task, reflect on what you learned and save anything non-obvious to memory: user preferences about DT style or review feedback, platform-specific quirks discovered, corrections to prior assumptions, or binding patterns worth reusing. Skip anything already in the code or derivable from `git log`. Write each memory to its own file under `~/.claude/agent-memory/dts-writer/` and update `MEMORY.md` with a one-line pointer.

Write clean, upstream-quality DTS/DTSI files and DT binding YAML schemas for Qualcomm SoCs.

## Ground Rules

- Always follow the patterns of the most recently upstreamed similar platform in the tree
- Never copy downstream DTS directly — rewrite clean for upstream
- Alphabetical node ordering within a DTS file
- Do not add properties to DTS nodes that are not defined in the binding spec
- All new bindings must be YAML schema (Documentation/devicetree/bindings/)
- Every new compatible string must have a corresponding binding YAML
- Include `#address-cells` and `#size-cells` only where children require them
- Use `reg-names` and `interrupt-names` when a node has multiple regs or interrupts
- Phandle references must point to nodes defined in the same or included DTSI

## IPCat Cross-Check

Before writing any DTS node, cross-check hardware data against IPCat MCP:

- Use IPCat MCP tools (`mcp__ipcat__*`) to verify: register base addresses, interrupt numbers, GPIO/TLMM mappings, clock IDs, QUP assignments, and bus topology for the target chip
- If IPCat data conflicts with what you were given or with another source (downstream DTS, spreadsheet, etc.), **stop and prompt the user** — describe the conflict explicitly (e.g., "IPCat says base address is 0x00990000 but the input says 0x00980000") and wait for their instruction before proceeding
- Do not silently pick one source over another; unresolved conflicts must block writing

## Reference Platform Lookup

Before writing any DTS or binding, identify the most recently upstreamed similar platform:
1. `git log --oneline arch/arm64/boot/dts/qcom/ | head -30` to find recent additions
2. Read that platform's DTS/DTSI as the reference
3. `git log --oneline Documentation/devicetree/bindings/ | head -30` for recent binding additions
4. Follow the structure, node naming, and property conventions precisely

## DT Coding Style

- Tabs for indentation inside nodes
- One blank line between top-level nodes
- Node labels in `snake_case`; compatible strings in `"vendor,chip-block"` form
- Pin state nodes named `default`, `sleep`, `active` as appropriate
- Clock and regulator names must match the binding's `clock-names` / `regulator-names` exactly
- Append `_pins` suffix to pinctrl nodes, `_state` suffix to pin state subnodes

## Binding YAML Style

- Required properties listed under `required:` in the order they appear in `properties:`
- `additionalProperties: false` unless the binding explicitly allows extension
- Example node in `examples:` must be syntactically valid and exercise all required properties
- Run `make dt_binding_check SCHEMA_FILES=Documentation/devicetree/bindings/<path>` to validate

## QCOM Bringup DT

Tips specific to writing minimal DTS/DTSI for a new Qualcomm SoC bringup.

### Hardware data verification

**Register base addresses — indirect lookup required:**
Never copy a base address directly from a reference platform's DTS.
Two-step IPCat method:
1. Query IPCat for the **reference chip** at the known address → identify the register block name.
2. Query IPCat for the **target chip** using that same block name → get the target address.
3. Use the target chip's address. Never use the reference chip's address directly.

A one-register offset (e.g. `0x310b7500` vs `0x310b7400`) compiles cleanly but causes a silent ramdump on first MMIO access.

**Interrupt numbers:**
1. Query `irqs_list_interrupts(chip)` and find the entry by source signal name.
2. Read `dst_vec` for the Apps GIC.
3. Apply: `dst_vec >= 4096` → `GIC_ESPI (dst_vec - 4096)`; `dst_vec < 4096` → `GIC_SPI (dst_vec - 32)`.

### Minimal nodes for UART boot

Only these nodes are needed to reach a login prompt over serial:

| Node | What to verify in IPCat |
|---|---|
| `memory@...` | placeholder, filled by bootloader |
| `cpus` | CPU MPIDR regs |
| `psci` | standard, method = smc |
| `timer` | standard armv8-timer PIR |
| `gcc` | base addr, reg size (`swi_get_module_details`) |
| `intc` (GICv3) | GICD + redistributor base addrs |
| `apps_rsc` | 3 DRV region addrs, TCS config |
| `rpmhcc` | compatible: chip-specific + fallback if shared |
| `pdc` | base addr; second reg size (check downstream); `qcom,pdc-ranges` |
| `qupv3_N` | base addr, AHB clock names |
| `uart` | base addr; interrupt — verify from IPCat (see below) |
| `tlmm` | `TLMM_REG` base, not `TLMM_XPU_X`; node name = first reg addr |
| `reserved-memory` | `aop-cmd-db` region |

### TLMM base address

- Downstream maps from `TLMM_XPU_X` (e.g. `0xf000000`) with `REG_BASE=0x100000`
- Upstream: map directly from `TLMM_REG` (e.g. `0xf100000`) — no REG_BASE in driver
- Node name must match first reg: `pinctrl@f100000 { reg = <0x0 0xf100000 ...> }`

### UART interrupt lookup

Wrong interrupt = UART deaf to keypresses = system appears frozen after systemd starts.

```python
# irqs_list_interrupts(chip): vec = raw GIC INTID
# ESPI: vec >= 4096 → GIC_ESPI (vec - 4096)
# SPI:  vec <  4096 → GIC_SPI  (vec - 32)
for i in irqs:
    if i['source_instance'] == 'u_qupv3_wrapper_1':  # adjust N for your QUP wrapper
        if 'qupv3_se_irq' in i['name']:
            se  = int(re.search(r'\[(\d+)\]', i['name']).group(1))
            vec = i['destination_vector']
            if vec >= 4096:
                print(f"SE{se}: <GIC_ESPI {vec - 4096} IRQ_TYPE_LEVEL_HIGH>")
            else:
                print(f"SE{se}: <GIC_SPI {vec - 32} IRQ_TYPE_LEVEL_HIGH>")
```

### Board DTS template

```dts
/ {
    model = "Qualcomm Technologies, Inc. <Chip> <Board>";
    compatible = "qcom,<chip>-<board>", "qcom,<chip>";
    chassis-type = "handset";  /* or "embedded", "desktop", etc. */

    aliases { serial0 = &uart<N>; };
    chosen  { stdout-path = "serial0:115200n8"; };

    clocks {
        xo_board:        /* fixed-clock, 76800000 Hz */
        sleep_clk:       /* fixed-clock, 32764 Hz */
        bi_tcxo_div2:    /* fixed-factor, clocks = rpmhcc RPMH_CXO_CLK, mult=1 div=2 */
        bi_tcxo_ao_div2: /* fixed-factor, clocks = rpmhcc RPMH_CXO_CLK_A, mult=1 div=2 */
    };
};

&tlmm  { gpio-reserved-ranges = ...; }
&uart<N> { status = "okay"; }
```

## Known Platform Quirks

Accumulated learnings from past work — non-obvious hardware behaviours and workarounds.

### QCOM SCMI shmem: add `no-map` reserved-memory when SRAM base is in DDR range

On Qualcomm SoCs where the SCMI shmem `mmio-sram` physical address falls inside the DDR range (e.g. `0x81xxxxxx` on Hawi-family and Glymur-family chips), a `reserved-memory` child with `no-map` covering the enclosing region is **mandatory**. Without it, the kernel classifies the page as normal RAM and `devm_ioremap` fails with `"ioremap attempted on RAM pfn"`, killing `arm-scmi` probe.

- `mmio-sram` alone does not mark the backing memory as reserved — the `reserved-memory` entry is what removes the range from memblock so ioremap succeeds.
- Contrast: `sm8750.dtsi` places its SCMI SRAM at `0x17b4e000` (SoC MMIO, not DDR) and needs no reservation. The pattern applies only when the base is in DDR.
- Size the carveout to match the sibling SoC (typically 1–2 MiB), not just the SRAM section.
- Keep `reserved-memory` children ordered by ascending base address.

Example (Hawi/Maili):
```dts
reserved-memory {
    pdp_ns_shared_mem: pdp-ns-shared@81f00000 {
        reg = <0x0 0x81f00000 0x0 0x100000>;
        no-map;
    };
};
```

---
name: qdl-flash-device
description: Flash a Qualcomm device via EDL mode using TACDev and qdl. Use when asked to flash a device, enter EDL mode, or reflash partitions using qdl and meta/rawprogram XML files.
---

# QDL Flash Device

Flash a Qualcomm device end-to-end: boot to EDL via TACDev, flash with qdl, then power on.

## Prerequisites

- TAC device connected (FT232, `/dev/ttyUSB0`)
- Target device connected via USB
- Meta files directory containing `prog_firehose_ddr.elf`, `rawprogram*.xml`, `patch*.xml`
- qdl binary: `/local/mnt/workspace/qdl`

## Workflow

### Step 1 — Boot to EDL

```bash
python3 scripts/boot_edl.py
```

### Step 2 — Verify EDL

```bash
lsusb | grep "QDL mode"
```

### Step 3 — Get device serial (recommended)

```bash
/local/mnt/workspace/qdl list
```

### Step 4 — Flash

```bash
scripts/flash.sh <meta-dir> [serial]
# Example:
scripts/flash.sh /local/mnt/workspace/qcom-multimedia-image-qcs615-ride 0AA94EFD
```

### Step 5 — Power on

```bash
python3 scripts/power_on.py
```

## Notes

- The TAC FT232 device disappears from USB while the target is in EDL — this is expected.
- `power_on.py` waits up to 15s for the TAC to re-enumerate automatically.
- Always pass the device serial (`-S`) to qdl when multiple devices are connected.
- TACDev scripts must run with CWD set to `/opt/qcom/Alpaca/examples/python/AutomationTestTAC` — the scripts handle this internally via `os.chdir()`.
- Storage type is UFS (`-s ufs`) for QCS615. Adjust `flash.sh` for other storage types.

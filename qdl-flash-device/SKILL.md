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
- qdl binary: resolved automatically (see below)

## qdl Binary Resolution

`flash.sh` locates qdl in this order — no manual setup required:

1. `$QDL` environment variable (if set and executable)
2. `/local/mnt/workspace/qdl` (default install path)
3. `qdl` on `$PATH`
4. **Auto-download** from `https://github.com/linux-msm/qdl/releases/download/v2.5/qdl-binary-ubuntu-24-x64.zip`
   — extracted to `/local/mnt/workspace/qdl` and made executable automatically.

To use a different qdl version or path, set `QDL=/path/to/qdl` before running.

## Workflow

### Step 1 — Boot to EDL

```bash
python3 scripts/boot_edl.py
```

If multiple TAC devices are connected, the script lists them and prompts for a choice.

### Step 2 — Verify EDL

```bash
lsusb | grep "QDL mode"
```

### Step 3 — Flash

```bash
scripts/flash.sh <meta-dir> [serial]
# Examples:
scripts/flash.sh /local/mnt/workspace/qcom-multimedia-image-qcs615-ride
scripts/flash.sh /local/mnt/workspace/qcom-multimedia-image-qcs615-ride 0AA94EFD
```

- `rawprogram*.xml` and `patch*.xml` are **globbed automatically** — no need to list them manually.
- If **no serial** is given and **multiple EDL devices** are detected via `qdl list`, the script
  prints a numbered list and waits for the user to choose before flashing.
- If only one device is present, it is selected automatically.

### Step 4 — Power on

```bash
python3 scripts/power_on.py
```

If multiple TAC devices are connected, the script lists them and prompts for a choice.

## Notes

- The TAC FT232 device disappears from USB while the target is in EDL — this is expected.
- `power_on.py` waits up to 15 s for the TAC to re-enumerate automatically.
- Storage type is UFS (`-s ufs`) for QCS615. To override, set the `QDL_STORAGE` env var or edit `flash.sh`.
- TACDev scripts must run with CWD set to `/opt/qcom/Alpaca/examples/python/AutomationTestTAC` — the scripts handle this internally via `os.chdir()`.

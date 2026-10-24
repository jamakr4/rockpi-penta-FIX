# ROCK Pi Penta SATA — Fixes in this fork

This fork contains fixes and extensions for the Radxa Penta SATA HAT top board software.

For hardware information, see the [Radxa Penta SATA HAT documentation](https://docs.radxa.com/en/accessories/storage/penta-sata-hat) and the [upstream rockpi-penta repository](https://github.com/radxa/rockpi-penta).

![Penta SATA HAT](images/penta-sata-hat.png)

## Fixes and additions

- **Fan really turns off below `lv0`.** Temperatures below the first threshold request 0% duty instead of almost 100%.
- **Correct fan PWM duty.** GPIO PWM uses the requested duty as the high time and holds the output low at 0%, preventing the brief start/stop cycle. Duty values are clamped to the 0–100% range.
- **Debian Trixie / Raspberry Pi 5 GPIO support.** Fan output and button input use the `gpiod` v2 API.
- **Drive temperature fan control.** When SMART temperatures are available, the fan follows the hottest detected disk temperature. It falls back to CPU temperature when no disk temperature is available. The package recommends `smartmontools` for this feature.
- **More OLED pages.** The display can show configured mountpoint usage, disk read/write rates, network receive/transmit rates, and detected disk temperatures, alongside the existing system information.
- **Configurable data sources.** Choose mountpoints and network interfaces in `rockpi-penta.conf`; `interfaces = auto` selects all interfaces except loopback.
- **Independent OLED updates.** Separate timer processes request automatic page changes and periodic data refreshes. One display worker serializes OLED writes to avoid overlapping I²C access. Set the refresh interval with `slider.refresh`.

## Fan curve

The thresholds are configured in `/etc/rockpi-penta.conf`. The default curve is:

| Temperature | Fan duty |
| --- | ---: |
| Below `lv0` | 0% (off) |
| At or above `lv0` | 25% |
| At or above `lv1` | 50% |
| At or above `lv2` | 75% |
| At or above `lv3` | 100% |

With drive temperature control enabled, tune these thresholds for the disks and cooling setup. If SMART data is unavailable, the controller uses CPU temperature instead.

## OLED configuration

Edit `/etc/rockpi-penta.conf` and restart the service after changing settings:

```ini
[slider]
auto = true
time = 10
refresh = 1.0

[disk]
space_usage_mnt_points = /|/mnt/storage
io_usage_mnt_points = /mnt/storage
disks_temp = true

[network]
interfaces = auto
```

Mountpoint and interface lists use `|` separators. Set `io_usage_mnt_points` to an empty value to hide disk I/O pages, or set `disks_temp = false` to hide the OLED temperature page. SMART-based fan control still uses drive temperatures when available.

Apply changes with:

```sh
sudo systemctl restart rockpi-penta.service
```

## Build and install

From the repository root, build and install the Debian package together with `smartmontools`:

```bash
sudo ./install.sh
```

The installer rebuilds `rockpi-penta.deb` from the checked-out files, then installs it and `smartmontools` through apt. The package also declares `smartmontools` as a recommendation, so apt installs it in the usual case even without the script. The package depends on Python 3, libgpiod, and Pillow.

## Scope

The `gpiod` v2 changes target Raspberry Pi OS / Debian Trixie on Raspberry Pi 5. Hardware PWM and the existing Radxa board-specific configuration remain available for other supported boards. This fork does not add the Raspberry Pi 5 PCIe configuration; follow the [Radxa setup guide](https://docs.radxa.com/en/accessories/storage/penta-sata-hat) for board and overlay setup.

## Credits

This fork includes adapted fixes and ideas from:

- [radxa/rockpi-penta PR #15](https://github.com/radxa/rockpi-penta/pull/15) — fan duty handling and the correct off behavior below `lv0`.
- [radxa/rockpi-penta PR #1](https://github.com/radxa/rockpi-penta/pull/1) — expanded OLED information and periodic display updates.
- [HabiRabbu/rockpi-penta-pi5-fix](https://github.com/HabiRabbu/rockpi-penta-pi5-fix), especially [commit 46f937c](https://github.com/HabiRabbu/rockpi-penta-pi5-fix/commit/46f937ccd3af6da4f68c2b7f77d74e1053918dd1) — `gpiod` v2 support and SMART-based drive temperature fan control.

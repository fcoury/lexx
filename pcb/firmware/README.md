# Lexx expanded MX firmware

Each hand has a Seeed Studio XIAO nRF52840. The left controller talks to the computer over USB or Bluetooth. The right controller sends key events to the left over Bluetooth. Each thumb board scans its own 29 switches.

## Flash the controllers

1. Connect one XIAO to USB and press its reset button twice quickly. A UF2 drive should appear.
2. Copy the matching [left UF2](bin/lexx_left.uf2) or [right UF2](bin/lexx_right.uf2) to that drive. The controller reboots automatically. Repeat for the other hand.
3. Power both hands. On a fresh pair, reset both within a few seconds of each other and let them bond. Connect the host to the left USB port, or pair with **Lexx MX** over Bluetooth.
4. Test each key individually, then hold a key on each hand together. Hold the left middle thumb key for navigation and F1–F12. Hold the right middle thumb key and press 1–5 to pick a Bluetooth profile, or Backspace to clear the selected profile.

The supplied binaries were built with ZMK v0.3.0, Zephyr revision `dacab4875df7`, and Zephyr SDK 0.16.9. Both UF2s use the nRF52840 family ID and start at flash address 0x27000. The UF2 bootloader must already be present. Initial hardware testing is pending. The [third-party notices](bin/third-party-notices.zip) accompany both UF2s, including ZMK, Zephyr, Arm CMSIS, Nordic and TinyCrypt source credits, Picolibc and the GCC runtime. [ZMK split pairing](https://zmk.dev/docs/troubleshooting/connection-issues) · [Seeed XIAO nRF52840](https://wiki.seeedstudio.com/XIAO_BLE/)

## Edit and rebuild

Edit [the keymap](config/lexx.keymap) for bindings. [The shield](config/boards/shields/lexx/lexx.dtsi) defines the electrical matrix and physical key order. R0/C0–C2 are the three thumb keys. R0/C3–C4 are the two extra finger keys. R1–R4 run from the near edge to the far edge and C0–C5 run from the hinge outward. R0/C5 is vacant on both hands.

With a [ZMK-compatible local toolchain](https://zmk.dev/docs/development/local-toolchain/setup), run these commands from this directory. Use a fresh temporary workspace for the clean checkout.

```fish
set project (pwd)
set buildroot (mktemp -d)
cp -R "$project/config" "$buildroot/config"
cd "$buildroot"
west init -l config
west update
west zephyr-export
west build -s zmk/app -b seeeduino_xiao_ble -d build-left -- -DSHIELD=lexx_left -DZMK_CONFIG="$project/config"
west build -s zmk/app -b seeeduino_xiao_ble -d build-right -- -DSHIELD=lexx_right -DZMK_CONFIG="$project/config"
```

The resulting files are `build-left/zephyr/zmk.uf2` and `build-right/zephyr/zmk.uf2`. Each controller scans COL2ROW using R0–R4 on D1, D2, D3, D6, D0 and C0–C5 on D10, D9, D8, D7, D4, D5. All header GPIOs serve the matrix. Adding a trackball will require a hardware and firmware revision.

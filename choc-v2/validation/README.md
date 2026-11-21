# Choc V2 footprint and matrix audit

## Switch, socket and cap

The reference switch is the black-bottom Kailh Choc V2 Red, PG1353, **CPG135301D01**. Kailh lists Brown as D02 and Blue as D03. The Red drawing defines this design. Other switches sold as “Choc V2” need a matching base, pin layout and keycap skirt. [Kailh product and specification links](https://www.kailh.net/products/kailh-choc-v2-low-profile-switch-set) · [Kailh Red drawing, revision A](https://cdn.shopify.com/s/files/1/0657/6075/5954/files/SPEC-CPG135301D01_Kailh_Choc_V2_Low_Profile_Red_Switch_03cd29a8-065e-45f8-8053-b72dcd70616d.pdf?v=1667190153)

The underside socket is **Kailh CPG135001S30**. Its two 2.90 mm sleeves enter the board from below. The mating pins on the switch enter from above. Kailh describes this socket as a Choc V1 accessory. Its contact geometry also fits the V2 layout, and Thorn Audio specifies this exact socket with its Choc V2 clicky switch. Red fit here is a dimensional design inference. Test a purchased switch and socket as a pair. [Kailh socket drawing](https://cdn-shop.adafruit.com/product-files/5118/5118-Choc-Socket.pdf) · [Kailh catalog](https://www.kailhswitch.com/mechanical-keyboard-switches/box-switches/choc-type-hot-swap-socket.html) · [Thorn Audio parts](https://thorn.audio/splines)

Kailh’s cross stem spans 4.00 mm with 1.30 mm arms. The surrounding stem ring is 6.50 mm across. Use a 1u, short-skirt, Choc V2-compatible cross-stem cap and test its full 3.2 mm nominal travel. The drawing gives a 15 mm flange and a 13.95 ± 0.05 mm lower housing. Our 14.10 mm square printed aperture and 1.20 mm plate are prototype dimensions. Print the [plate coupon](../case/choc-fit-coupon.stl) using the planned filament, settings and build orientation. Check that both clips latch, the cap bottoms out freely and lifting the cap leaves the switch seated. [Kailh Red drawing](https://cdn.shopify.com/s/files/1/0657/6075/5954/files/SPEC-CPG135301D01_Kailh_Choc_V2_Low_Profile_Red_Switch_03cd29a8-065e-45f8-8053-b72dcd70616d.pdf?v=1667190153)

## Physical registration

Here +X points right and +Y points toward the typist when seen **from the keycaps**. Dimensions are millimeters, relative to the stem center of a straight switch. The underside view mirrors this pattern. Both hands use the same asymmetric hardware. Each thumb switch rotates around its own stem.

| Feature | X | Y | Finished feature |
| --- | ---: | ---: | --- |
| Center peg | 0 | 0 | Ø5.00 non-plated hole |
| Socket sleeve for contact 1 | +5.00 | −3.75 | Ø3.00 non-plated hole |
| Socket sleeve for contact 2 | 0 | −5.95 | Ø3.00 non-plated hole |
| V2 locator | −5.00 | +5.15 | Non-plated oblong, 1.65 wide × 2.05 long |
| Socket land 1 | +8.245 | −3.75 | 2.60 mm square, underside |
| Socket land 2 | −3.245 | −5.95 | 2.60 mm square, underside |
| Switch LED window | 0 | +4.93 | Molded feature facing the typist |

The socket uses a 2.20 mm offset between sleeves. The switch pins have a 2.10 mm offset. Centering the socket between them leaves a nominal 0.05 mm difference at each pin. The April 2020 Red drawing calls for a 1.5 × 2.0 mm locator opening. Its 2019 predecessor showed a Ø1.60 mm opening in the same location. The production slot includes clearance for both nominal patterns. On the fanned thumbs, the slot rotates with the two sleeves. [Current switch drawing](https://cdn.shopify.com/s/files/1/0657/6075/5954/files/SPEC-CPG135301D01_Kailh_Choc_V2_Low_Profile_Red_Switch_03cd29a8-065e-45f8-8053-b72dcd70616d.pdf?v=1667190153) · [2019 preliminary drawing](https://raw.githubusercontent.com/keyboardio/keyswitch_documentation/master/datasheets/Kailh/CPG135301D01.pdf) · [Socket layout](https://cdn-shop.adafruit.com/product-files/5118/5118-Choc-Socket.pdf)

The printed plate top sits 2.20 mm above the PCB top. The 1.20 mm clip land leaves 1.00 mm from its underside to the PCB. On a 1.60 mm board the center peg projects about 1.70 mm below the PCB. The socket body extends up to 1.95 mm below it under the drawing tolerance. Check seating and clip retention on the actual build. [Switch side views](https://cdn.shopify.com/s/files/1/0657/6075/5954/files/SPEC-CPG135301D01_Kailh_Choc_V2_Low_Profile_Red_Switch_03cd29a8-065e-45f8-8053-b72dcd70616d.pdf?v=1667190153) · [Socket side views](https://cdn-shop.adafruit.com/product-files/5118/5118-Choc-Socket.pdf)

## Repeat the audit

Use Python with KiCad 10's bundled `pcbnew`. The script uses the Python standard library for everything else. From the repository root, run the following command with that interpreter.

```sh
python3 choc-v2/validation/verify.py --report choc-v2/validation/audit.json
```

The [layout datums](key-centers.csv) come from the expanded plate layout. They use assembly Y pointing away from the typist. The verifier reflects the **key centers** for the right hand, rotates each underlying asymmetric pin pattern independently, and measures each drilled shape in the native board. It also reads the finished Excellon and bottom Gerber files directly from each order ZIP and compares the physical matrix to the packaged firmware source. The UF2 checks cover block structure, target family and embedded device name. Desk testing the actual controllers is a separate step. Use `--native-only` to run the placement checks before plotting.

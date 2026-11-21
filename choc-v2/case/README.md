# Choc V2 case and hinge

Print the four parts for each hand at 100% in millimeters. The fixed shell holds 26 keys. The thumb shell holds three fanned keys, the controller and the optional battery. Both use a common indexed M3 hinge. [Left STLs](print/left/) · [Right STLs](print/right/) · [Editable Blender master](Expanded-Choc-V2.blend)

## Switch fit

Print the **22 × 22 mm one-switch coupon** with the same filament and slicer compensation as the plates. Insert a Kailh Choc V2 PG1353 from above. Check that both clips hold, the flange lies flush, and the cap returns freely from full travel. The reference switch is Kailh Red CPG135301D01, with a 13.95 ±0.05 mm lower body, 15 mm flange, 6.40 mm unloaded stem height above its seat and 3.20 ±0.25 mm travel. The prototype uses a 14.10 mm square opening and a 1.20 mm clip field. The manufacturer's drawing gives the housing and seated heights. A physical switch determines clip retention in the printed opening. [Fit coupon](choc-fit-coupon.stl) · [Kailh switch drawing](https://cdn.shopify.com/s/files/1/0657/6075/5954/files/SPEC-CPG135301D01_Kailh_Choc_V2_Low_Profile_Red_Switch_03cd29a8-065e-45f8-8053-b72dcd70616d.pdf?v=1667190153)

| Assembled dimension | mm above the shell base |
| --- | ---: |
| Floor top | 2.40 |
| Upper surface of insulating board supports | 11.20 |
| PCB bottom / top | 11.40 / 13.00 |
| Plate bottom / switch flange seating surface | 14.00 / 15.20 |
| Unloaded stem top | 21.60 |

The eight Choc STLs already include the lowered shell rims, flat plate faces, both handed sets of fastener holes, and the rear hinge clearance. Face-down plates put their screw posts upright. Print shells with the floor on the bed. Use local support for the horizontal hinge bores and inspect the short roofs of the USB and power-switch openings. The saved model allows an 18.2 × 18.2 mm 1u keycap gauge at each key, rotated with the thumb fan. Adjacent gauges clear by at least 0.85 mm on each finger deck and 2.93 mm on each thumb deck. Check skirt depth on the switch coupon with the intended caps.

## Assemble one hand

1. **Dry-fit the electronics.** Check the board perimeter, all posts, the USB plug’s overmold, and the slide-switch travel. The finger flex socket is centered at X = ±20, Y = 53.75 mm. Each flex exit opens to the rim through an 8 mm slot. The thumb USB opening is 12 × 6.8 mm, centered at Y = +0.5 mm. The slide opening is 9 × 3.8 mm, centered at Y = −14 mm.
2. **Seat the switches with support.** The 1.6 mm boards rest 0.20 mm above the three insulating lands at each deck. Back each socket directly when first seating its switch. All 58 asymmetric switch slots and south-facing sockets follow their actual handed PCB placement. SW1 has local relief at the front of the fixed hinge web. A relocated thumb support clears SW27’s retaining leg.
3. **Fit the flex and optional cell.** Slide the reinforced ribbon ends straight into their sockets and close the latches. The thumb ribbon leaves its connector at 9° toward the rear slot. The nominal protected-cell envelope is 18 × 24 × 4 mm at X = ±21, Y = −21, Z = 2.9–6.9 mm. Allow for the protection board, lead exit, mated plug and retention material. Keep wire and metal clear of the XIAO antenna near the hinge, then check Bluetooth with the battery and case installed.
4. **Install the hinge.** With the bare thumb shell detached, heat-set the 4 mm OD × 4 mm M3 insert into the single offset 3.65 mm pilot. Insert from its rear face and seat it flush. Use an M3 × 50 axle and a locknut up to 6.4 mm across its envelope. Fit the nine M2.5 × 8 countersunk thread-forming plate screws from below. The M3 × 10 indexing screw sets 0° or 60°. Remove it fully before moving the thumb. [Hardware BOM](../BOM.csv)
5. **Test the cable loop.** Route slack behind the hinge. Check the loop at both stops and intermediate angles with the keyboard on the desk. Confirm switch continuity while operating the fold and inspect both cable exits after cycling.

## Inspect the editable assembly

Open **Edit left hand** in the Blender master. Select **Controls**, then change **thumb_fold_deg** in its custom properties. **Split keyboard** drives both mirrored mechanisms with this slider. **PCB workbench** shows the four separate editable boards, their mechanical holes, sockets, retaining pins and component envelopes. Each right-hand board and its components use its own KiCad file. Production copper and drill output are in the four KiCad projects. [Blender master](Expanded-Choc-V2.blend) · [Electronics](../pcb/)

## Verified clearances

| Check | Smallest nominal result, either hand |
| --- | ---: |
| PCB edge to shell / to plate posts | 0.383 / 0.369 mm |
| Socket envelope to shell / to plate posts | 0.720 / 1.456 mm |
| Socket copper to plastic / to milled board edge | 1.096 / 0.637 mm |
| Locating pegs to shell or support / to posts | 0.356 / 1.325 mm |
| Socket, pads and pegs to other component keepouts | 1.120 mm |
| Insulating support disk to underside component keepouts | 0.353 mm |
| Rigid fold, closest sampled / conservative through-motion bound | 0.248 / 0.204 mm |
| Boards and electronics to opposite assemblies throughout the fold | ≥1.000 mm, reporting ceiling |

- **STLs and switch field.** The eight printable parts and the coupon each form one closed, outward-facing solid. The exported triangles passed self-intersection, edge, winding and degeneracy checks. All 58 square openings, clip thicknesses and plate heights were measured from the STL facets. All 18 plate pilots and floor seats, both USB and slider windows, the battery space, and both desktop connector approaches passed. [STL topology](shell-checks.json) · [Per-board measurements](board-fit.json)
- **Boards and sockets.** The actual KiCad board outlines were compared with the printed shell and post surfaces throughout the laminate thickness. The socket check includes its terminals, separate copper-pad rectangles, the center peg and the metal retaining-leg envelope. The socket envelope uses maximum dimensions from Kailh drawing KHA-PG1350-005EN. Square shoulder allowances enclose the tapered body. Both solder tails occupy the full 1.95 mm depth in the clearance test. [Socket profile](../pcb/socket-profile.json) · [Kailh socket drawing](https://www.kailhswitch.com/Content/upload/pdf/202115927/CPG135001S30-data-sheet.pdf)
- **Fold and hardware.** Blender 5.2.4 LTS evaluated 121 driven poses from 0° to 60°. A triangle travel bound covers intermediate rigid angles. A second sweep checked both hands’ actual boards, components and battery envelopes. The purchased fasteners passed 61 sampled poses and both locked insertion paths. Cable motion, skin fit, fastener wear, heat-set retention and printed-layer strength need a physical prototype. [Fold report](fold.json) · [Hardware access](hardware.json) · [Electronics motion](electronics-fold.json)

## Rebuild in the repository

The Blender source starts from the expanded PCB master to retain its editable scenes and hinge. The enclosed finger profiles are sufficient for a normal rebuild. To recalculate them from changed Choc board outlines, first run `python3 choc-v2/case/finger_profiles.py`. The Python mesh checks use NumPy and Shapely 2. Use the approved outside-sandbox Blender invocation on this Mac.

```sh
/Applications/Blender.app/Contents/MacOS/Blender -b --python-exit-code 1 --python choc-v2/case/build_case.py
python3 choc-v2/case/check_fit.py
/Applications/Blender.app/Contents/MacOS/Blender -b --python-exit-code 1 --python choc-v2/case/check_motion.py -- case
/Applications/Blender.app/Contents/MacOS/Blender -b --python-exit-code 1 --python choc-v2/case/check_motion.py -- hardware
/Applications/Blender.app/Contents/MacOS/Blender -b --python-exit-code 1 --python choc-v2/case/check_motion.py -- electronics
```

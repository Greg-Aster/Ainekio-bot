XIITIA 1.9-inch ST7789 display — reconstructed reference model
Amazon ASIN B0DFWMC16W

This is a newly constructed reference model based on the listing photos and
published dimensions. It is NOT manufacturer CAD, a downloaded third-party
model, or a measured copy of Greg's physical board.

BLENDER
Unzip this package. File > Import > glTF 2.0, select one .glb file.
Use the "no_header" version for bare solder pads, or "with_header" for a
representative straight male header on the back. Each is a complete model.
The GLB files use metres: the PCB should measure 0.029 x 0.062 m (29 x 62 mm)
in a default metric Blender scene. Parts have separate names and materials.
STEP files use millimetres and are provided for CAD applications.

DIMENSION BASIS (mm)
PCB width: 29, listing photo and text agree.
PCB length: 62, listing dimensioned photo. The description instead says 57.9.
The 62 mm option was selected because it agrees with the photographed board
proportions and other listings of this long blue board. Confirm physical length
before treating this model as final fabrication geometry.
Active display: 22.695 x 42.72, Amazon description.
Viewing window: 23.695 x 43.72, Amazon description.

REFERENCE / ESTIMATED GEOMETRY — NOT VERIFIED ON THIS ASIN
LCD package: 25.8 x 49.72 x 1.43; representative 1.9-inch ST7789 panel.
PCB: 1.6 thick; front adhesive: 0.3 thick.
Mounting holes: 2.5 diameter, centers on a 25 x 58 rectangle (2 mm edge inset).
Corner radius, hole dimensions, window position, flex slot, rear connector,
small components, solder and header dimensions are representative estimates.
Body envelope excluding optional pins: 29 x 62 x 5.1.
Optional header: 8 pins, 2.54 pitch; rear extension 8.5 mm from PCB back.
The header model does not include a mating connector or wire bend clearance.
Do not use the estimated hole pattern to finalize printed mounting posts
without checking it against the physical module.

COORDINATES IN THE SOURCE CAD
X = board width; Y = board length, header toward +Y.
Z = toward the screen. PCB back surface Z=0; PCB front surface Z=1.6.
XY origin = center of PCB outline.

SOURCES
Purchased product and photos:
https://www.amazon.com/dp/B0DFWMC16W
Dimensioned listing photo (29 x 62):
https://m.media-amazon.com/images/I/61+SRVQAjTL._AC_SL1500_.jpg
Additional listing of the long blue board (29 x 62 x 5.1):
https://elektroweb.pl/pl/wyswietlacze-lcd/1785-wyswietlacz-lcd-19-170x320-kolorowy-tft-spi-st7789.html
Representative panel dimensions:
https://www.chenghaolcd.com/doc/36251851/custom-1-9-inch-tft-lcd-display-170-320-resolution-with-st7789.pdf

Created 2026-09-27. Model and source script are provided for unrestricted reuse.
make_model.py requires CadQuery and NumPy. No account is needed for these files.

GY-LSM6DS3 — purple two-hole breakout reference model

Reconstructed for Greg's robot layout, 2026-09-27.
This is newly created reference geometry based on the supplied board photo,
NOYITO Amazon B07K5LVMZ2 listing photos and published board dimensions.
It is NOT factory CAD, measured hardware, or the SparkFun four-hole board.

BLENDER
Unzip. File > Import > glTF 2.0. Choose one complete model:
  GY_LSM6DS3_reference_no_headers.glb
  GY_LSM6DS3_reference_with_headers.glb
Both have named parts and materials. GLB uses metres; in a default metric
scene the board footprint is 0.013 x 0.018 m (13 x 18 mm).
STEP files use millimetres and are for CAD software.

DIMENSIONS / CONFIDENCE
Board outline: 13 x 18 mm, as listed by NOYITO and Easyelecmodule.
Pad count: 7 on one side, 5 on the other, confirmed visually from photos.
Mount count and general position: 2, both on the five-pad side, as photographed.
Sensor package: 2.5 x 3 x 0.83 mm, ST LSM6DS3 datasheet.

ESTIMATED — CHECK BEFORE FINALIZING PRINTED MOUNTS
PCB thickness 1.6 mm; corner radius 0.45 mm.
Mounting holes diameter 3.0 mm, centers X=2.5, Y=+/-7.1 mm.
Mount-to-mount center distance 14.2 mm.
Origin at PCB center; +Y points toward the small regulator; +Z faces components.
Pad rows X=+/-5.08 mm, 2.54 mm pitch; pad bores about 1 mm.
Hole positions, PCB thickness, component placement, regulator/passive dimensions,
header lengths, solder details and silkscreen are representative estimates.
The trace and axis graphics are decorative and not an electrical schematic or
authoritative sensor-coordinate definition.
Header variant: straight male pins protrude 8.5 mm behind the PCB; pin blocks
are 2.5 mm thick. It does not include mating sockets or wire clearance.
Model body thickness is approximately 2.75 mm excluding optional header pins.

SOURCES
User's supplied image: 1-750x750.JPG (purple two-hole module).
https://www.amazon.com/dp/B07K5LVMZ2
https://easyelecmodule.com/product/gy-lsm6ds3-6-axis-imu/
https://community.st.com/ysqtg83639/attachments/ysqtg83639/mems-sensors-forum/21052/1/st_imu_lsm6ds3_datasheet.pdf

make_model.py requires CadQuery. Model and script are available for unrestricted
reuse. No account is required to use these files.

"""Exercise the actual ISP profile and the saturated-white color boundary."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


class CameraPipelineTest(unittest.TestCase):
    def test_sensor_white_balance_has_no_competing_isp_owner(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        defaults = (root / "sdkconfig.defaults").read_text()
        self.assertIn("CONFIG_CAMERA_OV5647_CUSTOMIZED_IPA_JSON_CONFIGURATION_FILE=y", defaults)
        path = re.search(
            r'^CONFIG_CAMERA_OV5647_CUSTOMIZED_IPA_JSON_CONFIGURATION_FILE_PATH="([^"]+)"$',
            defaults, re.M,
        ).group(1)
        generator = root / "managed_components/espressif__esp_ipa/tools/config/esp_ipa_config.py"
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "ipa.c"
            subprocess.run([sys.executable, "-B", str(generator), "-i", str(root / path),
                            "-o", str(output), "-v", "1"], check=True, capture_output=True)
            generated = output.read_text()
        names = re.search(r's_ipa_OV5647_0_names\[\] = \{(.*?)\};', generated, re.S).group(1)
        self.assertNotIn('"esp_ipa_awb"', names)
        self.assertNotIn('.awb = &', generated)
        # Color/noise processing remains in the existing pipeline; no second
        # gain/shutter controller competes with the sensor's AEC/AGC.
        for name in ('ian', 'adn', 'aen', 'acc'):
            self.assertIn(f'"esp_ipa_{name}"', names)
        self.assertNotIn('"esp_ipa_agc"', names)

    def test_clipped_white_stays_neutral_after_sensor_white_balance(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        config = json.loads((root / 'components/ainekio_p4_media/ov5647_ipa.json').read_text())['OV5647']
        matrix = config['acc']['ccm']['table'][0]['matrix']
        def render(rgb):
            return [min(1, max(0, sum(matrix[3*r+c]*rgb[c] for c in range(3)))) for r in range(3)]
        # The old P4 path combines WB with CCM before clipping. A bright neutral
        # scene then loses green. Native WB clips before the neutral CCM instead.
        for red, blue in ((1.5, 1.5), (1.2, 2.0), (2.0, 1.2)):
            old = render([red, 1, blue])
            self.assertLess(old[1], min(old[0], old[2]))
            corrected = render([min(1, red), 1, min(1, blue)])
            for channel in corrected:
                self.assertAlmostEqual(channel, 1.0, places=4)
        # Unsaturated colors retain the same transform; this is not global
        # desaturation or a post-JPEG replacement of pink pixels.
        rgb = [0.15, 0.3, 0.2]
        gains = [1.5, 1.0, 1.8]
        self.assertEqual(render([x*g for x,g in zip(rgb,gains)]),
                         render([min(1,x*g) for x,g in zip(rgb,gains)]))


if __name__ == "__main__":
    unittest.main()

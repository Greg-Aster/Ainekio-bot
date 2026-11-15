"""Regression tests for ESP32-P4 RISC-V PIE coprocessor save/restore and esp-nn loops."""
import os
import pathlib
import re
import subprocess
import tempfile
import unittest


def find_riscv_tool(name: str) -> pathlib.Path:
    env_dir = os.environ.get("AINEKIO_RISCV_TOOLCHAIN_BIN")
    if env_dir:
        candidate = pathlib.Path(env_dir) / name
        if candidate.is_file():
            return candidate
    espressif_root = pathlib.Path.home() / ".espressif/tools/riscv32-esp-elf"
    if espressif_root.is_dir():
        matches = sorted(espressif_root.glob(f"*/riscv32-esp-elf/bin/{name}"))
        if matches:
            return matches[-1]
    raise FileNotFoundError(f"Could not locate {name} under ~/.espressif/tools/riscv32-esp-elf")


def find_idf_path() -> pathlib.Path:
    env_idf = os.environ.get("IDF_PATH")
    if env_idf and pathlib.Path(env_idf).is_dir():
        return pathlib.Path(env_idf)
    default_idf = pathlib.Path.home() / "esp/esp-idf-v5.5.4"
    if default_idf.is_dir():
        return default_idf
    raise FileNotFoundError("Could not locate ESP-IDF v5.5.4 at $IDF_PATH or ~/esp/esp-idf-v5.5.4")


class PieCoprocRegressionTest(unittest.TestCase):
    def test_generated_pie_context_and_esp_nn_kernels(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        idf_path = find_idf_path()
        gcc = find_riscv_tool("riscv32-esp-elf-gcc")
        objdump = find_riscv_tool("riscv32-esp-elf-objdump")

        riscv_dir = idf_path / "components/riscv"
        freertos_dir = idf_path / "components/freertos"
        esp_nn_dir = root / "managed_components/espressif__esp-nn"

        with tempfile.TemporaryDirectory(prefix="ainekio-pie-coproc-") as tmp:
            work = pathlib.Path(tmp)
            (work / "stub.c").write_text("int riscv_stub_sym;\n")
            (work / "CMakeLists.txt").write_text(f"""
cmake_minimum_required(VERSION 3.16)
project(pie_coproc_test C ASM)
add_library(riscv_stub STATIC "{work}/stub.c")
add_library(freertos_stub STATIC "{freertos_dir}/FreeRTOS-Kernel/portable/riscv/portasm.S")
add_library(esp_nn_stub STATIC
    "{esp_nn_dir}/src/common/esp_nn_multicore.c"
    "{esp_nn_dir}/src/common/esp_nn_mean_s8_riscv_pie.c"
    "{esp_nn_dir}/src/activation_functions/esp_nn_relu_s8_riscv_pie.c"
    "{esp_nn_dir}/src/convolution/esp_nn_depthwise_conv_riscv_pie.c"
    "{esp_nn_dir}/src/convolution/esp_nn_conv_riscv_pie.c"
    "{esp_nn_dir}/src/fully_connected/esp_nn_fully_connected_s8_riscv_pie.c"
    "{esp_nn_dir}/src/pooling/esp_nn_avg_pool_s8_riscv_pie.c"
    "{esp_nn_dir}/src/pooling/esp_nn_max_pool_s8_riscv_pie.c"
    "{esp_nn_dir}/src/softmax/esp_nn_softmax_s8_riscv_pie.c")
function(idf_component_get_property variable component property)
    if(component STREQUAL "riscv")
        if(property STREQUAL "COMPONENT_LIB")
            set(${{variable}} riscv_stub PARENT_SCOPE)
        else()
            set(${{variable}} "{riscv_dir}" PARENT_SCOPE)
        endif()
    elseif(component STREQUAL "freertos")
        if(property STREQUAL "COMPONENT_LIB")
            set(${{variable}} freertos_stub PARENT_SCOPE)
        else()
            set(${{variable}} "{freertos_dir}" PARENT_SCOPE)
        endif()
    elseif(component STREQUAL "espressif__esp-nn")
        if(property STREQUAL "COMPONENT_LIB")
            set(${{variable}} esp_nn_stub PARENT_SCOPE)
        else()
            set(${{variable}} "{esp_nn_dir}" PARENT_SCOPE)
        endif()
    endif()
endfunction()
include("{root}/cmake/idf_pie_coproc.cmake")
""")
            subprocess.run(
                ["cmake", "-S", str(work), "-B", str(work / "build")],
                check=True,
                capture_output=True,
                text=True,
            )
            generated = work / "build/ainekio-idf"

            # 1. Verify RvPIESaveArea C size == assembly RvPIESaveAreaSize == 220 bytes
            #    (8*16 Q regs + 4*16 QACC + 16 UA_STATE + 8 XACC + 4 MISC).
            (work / "sdkconfig.h").write_text(
                "#pragma once\n"
                "#define CONFIG_IDF_TARGET_ESP32P4 1\n"
                "#define CONFIG_FREERTOS_NUMBER_OF_CORES 2\n"
            )
            size_check_c = work / "size_check.c"
            size_check_c.write_text(
                '#include "sdkconfig.h"\n'
                '#include "riscv/rvruntime-frames.h"\n'
                "_Static_assert(sizeof(RvPIESaveArea) == 220, \"RvPIESaveArea must be 220 bytes\");\n"
                "_Static_assert(RV_COPROC2_SIZE == 220, \"RV_COPROC2_SIZE must be 220 bytes\");\n"
                "int pie_frame_size(void) { return sizeof(RvPIESaveArea); }\n"
            )
            subprocess.run(
                [
                    str(gcc),
                    "-march=rv32imafc_zicsr_zifencei_xesppie",
                    "-mabi=ilp32f",
                    "-I", str(work),
                    "-I", str(generated / "pie_include"),
                    "-I", str(idf_path / "components/soc/esp32p4/include"),
                    "-c", str(size_check_c),
                    "-o", str(work / "size_check.o"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # 2. Assemble patched portasm.S and verify rtos_save_pie_coproc saves/restores
            #    q0..q7 (including q3) and unpacks FFT_BIT_WIDTH, SAR_BYTES, SAR, and CFG
            #    in the exact bit order packed by pie_save_regs.
            portasm_obj = work / "portasm.o"
            subprocess.run(
                [
                    str(gcc),
                    "-march=rv32imafc_zicsr_zifencei_xesppie",
                    "-mabi=ilp32f",
                    "-I", str(work),
                    "-I", str(generated / "pie_include"),
                    "-I", str(freertos_dir / "FreeRTOS-Kernel/portable/riscv/include/freertos"),
                    "-I", str(freertos_dir / "FreeRTOS-Kernel/include"),
                    "-I", str(freertos_dir / "config/include"),
                    "-I", str(freertos_dir / "config/include/freertos"),
                    "-I", str(freertos_dir / "config/riscv/include"),
                    "-I", str(freertos_dir / "esp_additions/include"),
                    "-I", str(idf_path / "components/soc/esp32p4/include"),
                    "-I", str(riscv_dir / "include"),
                    "-I", str(idf_path / "components/esp_common/include"),
                    "-c", str(generated / "portasm.S"),
                    "-o", str(portasm_obj),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            portasm_dis = subprocess.check_output([str(objdump), "-d", str(portasm_obj)], text=True)
            pie_sec = portasm_dis.split("<rtos_save_pie_coproc>:", 1)[1]
            if "<rtos_save_fpu_coproc>:" in pie_sec:
                pie_sec = pie_sec.split("<rtos_save_fpu_coproc>:", 1)[0]

            # Encoding of esp.vst.128.ip qN, a0, 16 and esp.vld.128.ip qN, a0, 16:
            # q0..q7 -> rd/rs fields increment by 0x00000400 (0x8201223b .. 0x82013e3b)
            for q in range(8):
                vst_word = f"{0x8201223b + (q << 10):08x}"
                vld_word = f"{0x0201223b + (q << 10):08x}"
                self.assertIn(vst_word, pie_sec, f"Missing q{q} save in rtos_save_pie_coproc")
                self.assertIn(vld_word, pie_sec, f"Missing q{q} restore in rtos_save_pie_coproc")

            # Verify save reads CFG (80d001df), SAR (80b001df), SAR_BYTES (88b001df), FFT_BIT_WIDTH (84d001df)
            # and restore writes FFT_BIT_WIDTH (94d1805f) BEFORE SAR_BYTES (98b1805f) BEFORE SAR (90b1805f) BEFORE CFG (90d1805f).
            for insn_hex in ("80d001df", "80b001df", "88b001df", "84d001df"):
                self.assertIn(insn_hex, pie_sec)
            pos_fft_w = pie_sec.index("94d1805f")
            pos_sarb_w = pie_sec.index("98b1805f")
            pos_sar_w = pie_sec.index("90b1805f")
            pos_cfg_w = pie_sec.index("90d1805f")
            self.assertLess(pos_fft_w, pos_sarb_w)
            self.assertLess(pos_sarb_w, pos_sar_w)
            self.assertLess(pos_sar_w, pos_cfg_w)

            # 3. Compile every patched esp-nn RISC-V PIE kernel and prove:
            #    - zero opcode-0x2b (esp.lp.setup / esp.lp.setupi) instructions exist,
            #    - zero direct CSR 0x7f2 accesses exist,
            #    - PIE SIMD vector MAC/load instructions remain active.
            nn_kernels = [
                generated / "esp_nn/src/common/esp_nn_mean_s8_riscv_pie.c",
                generated / "esp_nn/src/activation_functions/esp_nn_relu_s8_riscv_pie.c",
                generated / "esp_nn/src/convolution/esp_nn_depthwise_conv_riscv_pie.c",
                generated / "esp_nn/src/convolution/esp_nn_conv_riscv_pie.c",
                generated / "esp_nn/src/fully_connected/esp_nn_fully_connected_s8_riscv_pie.c",
                generated / "esp_nn/src/pooling/esp_nn_avg_pool_s8_riscv_pie.c",
                generated / "esp_nn/src/pooling/esp_nn_max_pool_s8_riscv_pie.c",
                generated / "esp_nn/src/softmax/esp_nn_softmax_s8_riscv_pie.c",
            ]
            total_pie_macs = 0
            for src in nn_kernels:
                obj = work / f"{src.stem}.o"
                subprocess.run(
                    [
                        str(gcc),
                        "-O2",
                        "-march=rv32imafc_zicsr_zifencei_xesppie",
                        "-mabi=ilp32f",
                        "-DCONFIG_IDF_TARGET_ESP32P4=1",
                        "-I", str(work),
                        "-I", str(generated / "esp_nn/src/common"),
                        "-I", str(esp_nn_dir / "include"),
                        "-I", str(esp_nn_dir / "src/common"),
                        "-Wno-unused-function",
                        "-c", str(src),
                        "-o", str(obj),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                dis = subprocess.check_output([str(objdump), "-d", str(obj)], text=True)
                self.assertNotIn("0x7f2", dis, f"Direct CSR 0x7f2 remained in {src.name}")
                for m in re.finditer(r":\s+([0-9a-f]{8})\s+", dis):
                    word = int(m.group(1), 16)
                    self.assertNotEqual(
                        word & 0x7F,
                        0x2B,
                        f"Illegal HWLP opcode 0x{word:08x} remained in {src.name}",
                    )
                    if word in (0x064762BB, 0x4E476ABB, 0x044762BB, 0x4C476ABB):
                        total_pie_macs += 1
            self.assertGreater(total_pie_macs, 0, "PIE fused MAC+load instructions must remain active")

        # 4. If a linked firmware ELF is present, verify the whole binary has zero
        #    opcode-0x2b HWLP instructions, zero csrsi 0x7f2 writes, and 220-byte PIE save area.
        firmware_elf = root / "build/ainekio_p4_body.elf"
        if firmware_elf.is_file():
            elf_dis = subprocess.check_output([str(objdump), "-d", str(firmware_elf)], text=True)
            for m in re.finditer(r":\s+([0-9a-f]{8})\s+", elf_dis):
                word = int(m.group(1), 16)
                self.assertNotEqual(word & 0x7F, 0x2B, f"HWLP opcode 0x{word:08x} in firmware ELF")
                self.assertNotEqual(word, 0x7F20E073, "Direct csrsi 0x7f2,1 in firmware ELF")
            coproc_fn = elf_dis.split("<pxPortGetCoprocArea>:", 1)[1].split("\n\n", 1)[0]
            self.assertIn("0dc00", coproc_fn, "pxPortGetCoprocArea must allocate 220 (0xdc) bytes for PIE")


if __name__ == "__main__":
    unittest.main()

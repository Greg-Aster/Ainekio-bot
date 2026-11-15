# ESP32-P4 RISC-V PIE coprocessor & hardware-loop fixes (ESP-IDF 5.5.4 + esp-nn):
#
# 1. esp-nn emits 2- to 4-instruction esp.lp.setup loops ending on PIE vector or
#    compressed instructions (e.g. qacc16_mac_continue at 4 insns / 16 B ending
#    on esp.vldbc.8.xp, plus unaligned and count==1 loops). ESP32-P4 HWLP
#    requires >= 8 32-bit instructions (32 B), 4-byte alignment, count >= 2, and
#    a 32-bit scalar terminal instruction; an interrupt at the loop boundary
#    otherwise corrupts PC into IRAM (observed live: wild jump into
#    pxPortGetCoprocArea with a2 = cpair = 99 >= SOC_CPU_COPROC_NUM). Replace
#    those short esp.lp.setup loops with standard addi + bnez software-pipelined
#    loops, which dual-issue in the scalar slot alongside PIE ops.
#
# 2. esp-nn writes CSR_PIE_STATE_REG (csrsi 0x7f2, 0b01) directly in task code,
#    bypassing FreeRTOS's lazy PIE trap (rtos_save_pie_coproc), skipping core
#    pinning, and clobbering any prior owner's live PIE registers. Remove direct
#    0x7f2 writes so the first PIE instruction traps once through FreeRTOS.
#
# 3. ESP-IDF 5.5.4 portasm.S omits q3 in pie_save_regs/pie_restore_regs, swaps
#    SAR with FFT_BIT_WIDTH on restore, omits PIE CFG, and sizes RV_PIE_XACC at
#    4 bytes instead of 8 bytes in rvruntime-frames.h. Compile project-local
#    copies in ${CMAKE_BINARY_DIR}/ainekio-idf without touching the host SDK or
#    managed_components.

function(ainekio_pie_replace var_name old_text new_text label)
    set(input "${${var_name}}")
    string(FIND "${input}" "${old_text}" pos)
    if(pos EQUAL -1)
        message(FATAL_ERROR "idf_pie_coproc: expected pattern not found for ${label}")
    endif()
    string(REPLACE "${old_text}" "${new_text}" output "${input}")
    set(${var_name} "${output}" PARENT_SCOPE)
endfunction()

set(pie_idf_dir "${CMAKE_BINARY_DIR}/ainekio-idf")
file(MAKE_DIRECTORY "${pie_idf_dir}/pie_include/riscv")

# --- 1. ESP-IDF riscv + freertos PIE context frame & save/restore ---
idf_component_get_property(riscv_lib riscv COMPONENT_LIB)
idf_component_get_property(riscv_dir riscv COMPONENT_DIR)
set(rvruntime_source "${riscv_dir}/include/riscv/rvruntime-frames.h")
file(READ "${rvruntime_source}" rvruntime_contents)
ainekio_pie_replace(rvruntime_contents
    "STRUCT_FIELD  (long, 4,  RV_PIE_XACC,      xacc)"
    "STRUCT_AFIELD (long, 4,  RV_PIE_XACC,      xacc,       2)"
    "rvruntime-frames.h RV_PIE_XACC 8-byte slot")
set(rvruntime_fixed "${pie_idf_dir}/pie_include/riscv/rvruntime-frames.h")
file(CONFIGURE OUTPUT "${rvruntime_fixed}" CONTENT "${rvruntime_contents}" @ONLY)
target_include_directories(${riscv_lib} BEFORE PUBLIC "${pie_idf_dir}/pie_include")

idf_component_get_property(freertos_lib freertos COMPONENT_LIB)
idf_component_get_property(freertos_dir freertos COMPONENT_DIR)
set(portasm_source "${freertos_dir}/FreeRTOS-Kernel/portable/riscv/portasm.S")
file(READ "${portasm_source}" portasm_contents)
ainekio_pie_replace(portasm_contents [=[
.macro pie_save_regs frame=a0
    /* Save the 128-bit Q registers from the frame memory and then frame += 16 */
    esp.vst.128.ip  q0, \frame, 16
    esp.vst.128.ip  q1, \frame, 16
    esp.vst.128.ip  q2, \frame, 16
    esp.vst.128.ip  q4, \frame, 16
    esp.vst.128.ip  q5, \frame, 16
    esp.vst.128.ip  q6, \frame, 16
    esp.vst.128.ip  q7, \frame, 16
    /* Save the QACC_H and QACC_L registers, each being 256 bits big */
    esp.st.qacc.l.l.128.ip \frame, 16
    esp.st.qacc.l.h.128.ip \frame, 16
    esp.st.qacc.h.l.128.ip \frame, 16
    esp.st.qacc.h.h.128.ip \frame, 16
    /* UA_STATE register (128 bits) */
    esp.st.ua.state.ip \frame, 16
    /* XACC register (40 bits) */
    esp.st.u.xacc.ip \frame, 8
    /* The following registers will be stored in the same word */
    /* SAR register (6 bits) */
    esp.movx.r.sar a1
    slli a2, a1, 8
    /* SAR_BYTES register (4 bits) */
    esp.movx.r.sar.bytes a1
    slli a1, a1, 4
    or   a2, a2, a1
    /* FFT_BIT_WIDTH register (4 bits) */
    esp.movx.r.fft.bit.width a1
    or  a2, a2, a1
    sw  a2, (\frame)
.endm


.macro pie_restore_regs frame=a0
    /* Restore the 128-bit Q registers from the frame memory and then frame += 16 */
    esp.vld.128.ip  q0, \frame, 16
    esp.vld.128.ip  q1, \frame, 16
    esp.vld.128.ip  q2, \frame, 16
    esp.vld.128.ip  q4, \frame, 16
    esp.vld.128.ip  q5, \frame, 16
    esp.vld.128.ip  q6, \frame, 16
    esp.vld.128.ip  q7, \frame, 16
    /* Save the QACC_H and QACC_L registers, each being 256 bits big */
    esp.ld.qacc.l.l.128.ip \frame, 16
    esp.ld.qacc.l.h.128.ip \frame, 16
    esp.ld.qacc.h.l.128.ip \frame, 16
    esp.ld.qacc.h.h.128.ip \frame, 16
    /* UA_STATE register (128 bits) */
    esp.ld.ua.state.ip \frame, 16
    /* XACC register (40 bits) */
    esp.ld.xacc.ip \frame, 8
    /* The following registers are stored in the same word */
    lw  a2, (\frame)
    /* FFT_BIT_WIDTH register (4 bits) */
    andi a1, a2, 0xf
    esp.movx.w.sar a1
    /* SAR_BYTES register (4 bits) */
    srli a2, a2, 4
    andi a1, a2, 0xf
    esp.movx.w.sar.bytes a1
    /* SAR register (6 bits) */
    srli a2, a2, 4
    andi a1, a2, 0x3f
    esp.movx.w.fft.bit.width a1
.endm
]=] [=[
.macro pie_save_regs frame=a0
    /* Save all eight 128-bit Q registers (q0..q7) */
    esp.vst.128.ip  q0, \frame, 16
    esp.vst.128.ip  q1, \frame, 16
    esp.vst.128.ip  q2, \frame, 16
    esp.vst.128.ip  q3, \frame, 16
    esp.vst.128.ip  q4, \frame, 16
    esp.vst.128.ip  q5, \frame, 16
    esp.vst.128.ip  q6, \frame, 16
    esp.vst.128.ip  q7, \frame, 16
    /* Save the QACC_H and QACC_L registers, each being 256 bits big */
    esp.st.qacc.l.l.128.ip \frame, 16
    esp.st.qacc.l.h.128.ip \frame, 16
    esp.st.qacc.h.l.128.ip \frame, 16
    esp.st.qacc.h.h.128.ip \frame, 16
    /* UA_STATE register (128 bits) */
    esp.st.ua.state.ip \frame, 16
    /* XACC register (40 bits) */
    esp.st.u.xacc.ip \frame, 8
    /* Pack CFG[23:16] | SAR[13:8] | SAR_BYTES[7:4] | FFT_BIT_WIDTH[3:0] */
    esp.movx.r.cfg a1
    slli a2, a1, 16
    esp.movx.r.sar a1
    slli a1, a1, 8
    or   a2, a2, a1
    esp.movx.r.sar.bytes a1
    slli a1, a1, 4
    or   a2, a2, a1
    esp.movx.r.fft.bit.width a1
    or   a2, a2, a1
    sw   a2, (\frame)
.endm


.macro pie_restore_regs frame=a0
    /* Restore all eight 128-bit Q registers (q0..q7) */
    esp.vld.128.ip  q0, \frame, 16
    esp.vld.128.ip  q1, \frame, 16
    esp.vld.128.ip  q2, \frame, 16
    esp.vld.128.ip  q3, \frame, 16
    esp.vld.128.ip  q4, \frame, 16
    esp.vld.128.ip  q5, \frame, 16
    esp.vld.128.ip  q6, \frame, 16
    esp.vld.128.ip  q7, \frame, 16
    /* Restore the QACC_H and QACC_L registers, each being 256 bits big */
    esp.ld.qacc.l.l.128.ip \frame, 16
    esp.ld.qacc.l.h.128.ip \frame, 16
    esp.ld.qacc.h.l.128.ip \frame, 16
    esp.ld.qacc.h.h.128.ip \frame, 16
    /* UA_STATE register (128 bits) */
    esp.ld.ua.state.ip \frame, 16
    /* XACC register (40 bits) */
    esp.ld.xacc.ip \frame, 8
    /* Unpack CFG[23:16] | SAR[13:8] | SAR_BYTES[7:4] | FFT_BIT_WIDTH[3:0] */
    lw   a2, (\frame)
    andi a1, a2, 0xf
    esp.movx.w.fft.bit.width a1
    srli a2, a2, 4
    andi a1, a2, 0xf
    esp.movx.w.sar.bytes a1
    srli a2, a2, 4
    andi a1, a2, 0x3f
    esp.movx.w.sar a1
    srli a2, a2, 8
    andi a1, a2, 0xff
    esp.movx.w.cfg a1
.endm
]=] "portasm.S pie_save_regs/pie_restore_regs")
set(portasm_fixed "${pie_idf_dir}/portasm.S")
file(CONFIGURE OUTPUT "${portasm_fixed}" CONTENT "${portasm_contents}" @ONLY)
target_include_directories(${freertos_lib} BEFORE PRIVATE "${pie_idf_dir}/pie_include")
get_target_property(freertos_sources ${freertos_lib} SOURCES)
list(FILTER freertos_sources EXCLUDE REGEX "(^|/)portable/riscv/portasm\\.S$")
set_property(TARGET ${freertos_lib} PROPERTY SOURCES "${freertos_sources}")
target_sources(${freertos_lib} PRIVATE "${portasm_fixed}")

# --- 2. espressif__esp-nn PIE lazy-ownership & software-pipelined loops ---
idf_component_get_property(esp_nn_lib espressif__esp-nn COMPONENT_LIB)
idf_component_get_property(esp_nn_dir espressif__esp-nn COMPONENT_DIR)
set(esp_nn_copy "${pie_idf_dir}/esp_nn")

foreach(subdir common convolution fully_connected activation_functions pooling softmax)
    file(MAKE_DIRECTORY "${esp_nn_copy}/src/${subdir}")
    file(GLOB subdir_headers "${esp_nn_dir}/src/${subdir}/*.h")
    foreach(hdr IN LISTS subdir_headers)
        get_filename_component(hdr_name "${hdr}" NAME)
        configure_file("${hdr}" "${esp_nn_copy}/src/${subdir}/${hdr_name}" COPYONLY)
    endforeach()
endforeach()

set(nn_common_hdr "${esp_nn_dir}/src/common/common_functions.h")
file(READ "${nn_common_hdr}" nn_common_contents)
ainekio_pie_replace(nn_common_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\" \\\n"
    ""
    "common_functions.h ESP_NN_PIE_ENABLE csrsi 0x7f2")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/common/common_functions.h"
    CONTENT "${nn_common_contents}" @ONLY)
target_include_directories(${esp_nn_lib} BEFORE PRIVATE "${esp_nn_copy}/src/common")

# 2a. esp_nn_multicore.c
set(nn_multicore_src "${esp_nn_dir}/src/common/esp_nn_multicore.c")
file(READ "${nn_multicore_src}" nn_multicore_contents)
ainekio_pie_replace(nn_multicore_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_multicore.c csrsi 0x7f2")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/common/esp_nn_multicore.c"
    CONTENT "${nn_multicore_contents}" @ONLY)

# 2b. esp_nn_mean_s8_riscv_pie.c
set(nn_mean_src "${esp_nn_dir}/src/common/esp_nn_mean_s8_riscv_pie.c")
file(READ "${nn_mean_src}" nn_mean_contents)
ainekio_pie_replace(nn_mean_contents
    "            \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_mean_s8_riscv_pie.c csrsi 0x7f2")
ainekio_pie_replace(nn_mean_contents [=[
            /* zero-overhead loop; end label ON last body insn */
            "esp.lp.setup 0, %[cnt], 1f     \n\t"
            "esp.vld.128.ip  q0, x30, 0     \n\t"
            "esp.vmulas.s8.qacc q0, q7      \n\t"
            "1:                             \n\t"
            "add    x30, x30, %[stride]     \n\t"
            :
            : [one] "r"(&one_val), [base] "r"(base_ptr),
              [cnt] "r"(num_elements), [stride] "r"((int32_t)channels)
            : "x30"
]=] [=[
            "blez   %[cnt], 2f              \n\t"
            "mv     x29, %[cnt]             \n\t"
            "1:                             \n\t"
            "esp.vld.128.ip  q0, x30, 0     \n\t"
            "esp.vmulas.s8.qacc q0, q7      \n\t"
            "add    x30, x30, %[stride]     \n\t"
            "addi   x29, x29, -1            \n\t"
            "bnez   x29, 1b                 \n\t"
            "2:                             \n\t"
            :
            : [one] "r"(&one_val), [base] "r"(base_ptr),
              [cnt] "r"(num_elements), [stride] "r"((int32_t)channels)
            : "x29", "x30"
]=] "esp_nn_mean_s8_riscv_pie.c loop")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/common/esp_nn_mean_s8_riscv_pie.c"
    CONTENT "${nn_mean_contents}" @ONLY)

# 2c. esp_nn_relu_s8_riscv_pie.c
set(nn_relu_src "${esp_nn_dir}/src/activation_functions/esp_nn_relu_s8_riscv_pie.c")
file(READ "${nn_relu_src}" nn_relu_contents)
ainekio_pie_replace(nn_relu_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_relu_s8_riscv_pie.c csrsi 0x7f2")
ainekio_pie_replace(nn_relu_contents [=[
            /* zero-overhead hardware loop; end label sits ON the last insn */
            "esp.lp.setup     0, %[cnt], 1f \n\t"
            "esp.vld.128.ip   q0, x30, 0    \n\t"  /* load 16 bytes, no auto-increment */
            "esp.vmax.s8      q0, q0, q2    \n\t"  /* max(val, 0) */
            "esp.vmin.s8      q0, q0, q3    \n\t"  /* min(val, 6) */
            "1:                             \n\t"
            "esp.vst.128.xp   q0, x30, x29  \n\t"  /* store and advance ptr by 16 */

            :
            : [ptr] "r"(data + i), [cnt] "r"(count), [stride] "r"(stride)
            : "x29", "x30", "memory"
]=] [=[
            "mv     x28, %[cnt]             \n\t"
            "1:                             \n\t"
            "esp.vld.128.ip   q0, x30, 0    \n\t"  /* load 16 bytes, no auto-increment */
            "esp.vmax.s8      q0, q0, q2    \n\t"  /* max(val, 0) */
            "esp.vmin.s8      q0, q0, q3    \n\t"  /* min(val, 6) */
            "esp.vst.128.xp   q0, x30, x29  \n\t"  /* store and advance ptr by 16 */
            "addi   x28, x28, -1            \n\t"
            "bnez   x28, 1b                 \n\t"

            :
            : [ptr] "r"(data + i), [cnt] "r"(count), [stride] "r"(stride)
            : "x28", "x29", "x30", "memory"
]=] "esp_nn_relu_s8_riscv_pie.c loop")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/activation_functions/esp_nn_relu_s8_riscv_pie.c"
    CONTENT "${nn_relu_contents}" @ONLY)

# 2d. esp_nn_depthwise_conv_riscv_pie.c
set(nn_dw_src "${esp_nn_dir}/src/convolution/esp_nn_depthwise_conv_riscv_pie.c")
file(READ "${nn_dw_src}" nn_dw_contents)
ainekio_pie_replace(nn_dw_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_depthwise_conv_riscv_pie.c csrsi 0x7f2")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/convolution/esp_nn_depthwise_conv_riscv_pie.c"
    CONTENT "${nn_dw_contents}" @ONLY)

# 2e. esp_nn_conv_riscv_pie.c
set(nn_conv_src "${esp_nn_dir}/src/convolution/esp_nn_conv_riscv_pie.c")
file(READ "${nn_conv_src}" nn_conv_contents)
ainekio_pie_replace(nn_conv_contents
    "        \"csrsi 0x7f2, 0b01      \\n\\t\" // enable `esp` vector extension\n"
    ""
    "esp_nn_conv_riscv_pie.c set_conv_scratch_buf csrsi 0x7f2")
ainekio_pie_replace(nn_conv_contents
    "                \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_conv_riscv_pie.c batch16_deep csrsi 0x7f2")
ainekio_pie_replace(nn_conv_contents
    "            \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_conv_riscv_pie.c conv/im2col csrsi 0x7f2")
ainekio_pie_replace(nn_conv_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_conv_riscv_pie.c conv_1x1_batch16 csrsi 0x7f2")
ainekio_pie_replace(nn_conv_contents [=[
            /* zero-overhead loop; end label ON last body insn */
            "esp.lp.setup 0, %[c32], 1f             \n\t"
            "esp.vmulas.s8.xacc.ld.ip q0, x30, 16, q0, q1 \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc.ld.ip q2, x30, 16, q2, q3 \n\t"
            "1:                                     \n\t"
            "esp.vld.128.ip  q3, x31, 16            \n\t"
            "2:                                     \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "esp.vmulas.s8.xacc  q2, q3             \n\t"
            "beqz   %[rem], 3f                      \n\t"
            "esp.vld.128.ip  q0, x30, 16            \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "3:                                     \n\t"
            :
            : [inp] "r"(in + r * in_stride), [flt] "r"(filt + r * row_size),
              [c32] "r"(c32), [rem] "r"(rem16)
            : "x30", "x31"
]=] [=[
            "mv     x29, %[c32]                     \n\t"
            "1:                                     \n\t"
            "esp.vmulas.s8.xacc.ld.ip q0, x30, 16, q0, q1 \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc.ld.ip q2, x30, 16, q2, q3 \n\t"
            "esp.vld.128.ip  q3, x31, 16            \n\t"
            "addi   x29, x29, -1                    \n\t"
            "bnez   x29, 1b                         \n\t"
            "2:                                     \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "esp.vmulas.s8.xacc  q2, q3             \n\t"
            "beqz   %[rem], 3f                      \n\t"
            "esp.vld.128.ip  q0, x30, 16            \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "3:                                     \n\t"
            :
            : [inp] "r"(in + r * in_stride), [flt] "r"(filt + r * row_size),
              [c32] "r"(c32), [rem] "r"(rem16)
            : "x29", "x30", "x31"
]=] "esp_nn_conv_riscv_pie.c conv_dot_rows_pie loop")
ainekio_pie_replace(nn_conv_contents [=[
            /* zero-overhead loop; end label ON last body insn */
            "esp.lp.setup 0, %[c32], 1f             \n\t"
            "esp.vmulas.s8.xacc.ld.ip q0, x30, 16, q0, q1 \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc.ld.ip q2, x30, 16, q2, q3 \n\t"
            "1:                                     \n\t"
            "esp.vld.128.ip  q3, x31, 16            \n\t"
            "2:                                     \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "esp.vmulas.s8.xacc  q2, q3             \n\t"
            "beqz   %[rem16], 3f                    \n\t"
            "esp.vld.128.ip  q0, x30, 16            \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "3:                                     \n\t"
            "esp.movx.r.xacc.l   x30                \n\t"
            "mv     %[res], x30                     \n\t"
            : [res] "=r"(result)
            : [in] "r"(a), [flt] "r"(b), [c32] "r"(c32), [rem16] "r"(rem16)
            : "x30", "x31"
]=] [=[
            "mv     x29, %[c32]                     \n\t"
            "1:                                     \n\t"
            "esp.vmulas.s8.xacc.ld.ip q0, x30, 16, q0, q1 \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc.ld.ip q2, x30, 16, q2, q3 \n\t"
            "esp.vld.128.ip  q3, x31, 16            \n\t"
            "addi   x29, x29, -1                    \n\t"
            "bnez   x29, 1b                         \n\t"
            "2:                                     \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "esp.vmulas.s8.xacc  q2, q3             \n\t"
            "beqz   %[rem16], 3f                    \n\t"
            "esp.vld.128.ip  q0, x30, 16            \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "3:                                     \n\t"
            "esp.movx.r.xacc.l   x30                \n\t"
            "mv     %[res], x30                     \n\t"
            : [res] "=r"(result)
            : [in] "r"(a), [flt] "r"(b), [c32] "r"(c32), [rem16] "r"(rem16)
            : "x29", "x30", "x31"
]=] "esp_nn_conv_riscv_pie.c pie_dot_s8 loop")
ainekio_pie_replace(nn_conv_contents [=[
        "beqz   %[cpair], 2f                 \n\t"
        "esp.lp.setup 0, %[cpair], 1f        \n\t"
        "esp.vmulas.s8.qacc.ld.ip q0, x30, 16, q0, q1 \n\t"
        "esp.vldbc.8.xp  q1, x31, t3         \n\t"
        "esp.vmulas.s8.qacc.ld.ip q2, x30, 16, q2, q3 \n\t"
        "1:                                  \n\t"
        "esp.vldbc.8.xp  q3, x31, t3         \n\t"
        "2:                                  \n\t"
        "esp.vmulas.s8.qacc q0, q1           \n\t"
        "esp.vmulas.s8.qacc q2, q3           \n\t"
        :
        : [trans] "r"(trans), [flt] "r"(filt),
          [cpair] "r"(cnt / 2 - 1)
        : "x30", "x31", "t3"
]=] [=[
        "beqz   %[cpair], 2f                 \n\t"
        "mv     x29, %[cpair]                \n\t"
        "1:                                  \n\t"
        "esp.vmulas.s8.qacc.ld.ip q0, x30, 16, q0, q1 \n\t"
        "esp.vldbc.8.xp  q1, x31, t3         \n\t"
        "esp.vmulas.s8.qacc.ld.ip q2, x30, 16, q2, q3 \n\t"
        "esp.vldbc.8.xp  q3, x31, t3         \n\t"
        "addi   x29, x29, -1                 \n\t"
        "bnez   x29, 1b                      \n\t"
        "2:                                  \n\t"
        "esp.vmulas.s8.qacc q0, q1           \n\t"
        "esp.vmulas.s8.qacc q2, q3           \n\t"
        :
        : [trans] "r"(trans), [flt] "r"(filt),
          [cpair] "r"(cnt / 2 - 1)
        : "x29", "x30", "x31", "t3"
]=] "esp_nn_conv_riscv_pie.c qacc16_mac_continue loop")
ainekio_pie_replace(nn_conv_contents [=[
                    "beqz %[c16], 2f                \n\t"
                    /* zero-overhead loop; end label ON last body insn */
                    "esp.lp.setup 0, %[c16], 1f     \n\t"
                    "esp.vmulas.s8.xacc.ld.ip  q0, x30, 16, q0, q1   \n\t"
                    "1:                             \n\t"
                    "esp.vld.128.ip  q1, x31, 16    \n\t"
                    "2:                             \n\t"
]=] [=[
                    "beqz %[c16], 2f                \n\t"
                    "mv   x29, %[c16]               \n\t"
                    "1:                             \n\t"
                    "esp.vmulas.s8.xacc.ld.ip  q0, x30, 16, q0, q1   \n\t"
                    "esp.vld.128.ip  q1, x31, 16    \n\t"
                    "addi x29, x29, -1              \n\t"
                    "bnez x29, 1b                   \n\t"
                    "2:                             \n\t"
]=] "esp_nn_conv_riscv_pie.c conv_s8_1x1 xacc loop")
ainekio_pie_replace(nn_conv_contents [=[
                    if (c16 >= 4) {
                        asm volatile (
                            "mv x30, %[inp]                 \n\t"
                            "mv x31, %[flt]                 \n\t"
                            "esp.vld.128.ip  q0, x30, 16    \n\t"
                            "esp.vld.128.ip  q1, x31, 16    \n\t"

                            /* zero-overhead loop; end label ON last body insn */
                            "esp.lp.setup 0, %[c16], 1f     \n\t"
                            "esp.vmulas.s8.xacc.ld.ip  q0, x30, 16, q0, q1   \n\t"
                            "1:                             \n\t"
                            "esp.vld.128.ip  q1, x31, 16    \n\t"

                            // move input_ptr and filter_ptr
                            "mv %[inp], x30                 \n\t"
                            "mv %[flt], x31                 \n\t"
                            "esp.vmulas.s8.xacc  q0, q1     \n\t"

                            : [inp] "+r" (input_data_ptr), [flt] "+r" (filter_data_ptr)
                            : [c16] "r"(c16)
                            : "x30", "x31"
                        );
                    } else {
]=] [=[
                    {
]=] "esp_nn_conv_riscv_pie.c conv_s8_padded loop")
ainekio_pie_replace(nn_conv_contents [=[
static void conv_pie_rows_mt_worker(void *p)
{
    const conv_pie_rows_mt_job_t *j = (const conv_pie_rows_mt_job_t *)p;
]=] [=[
static void conv_pie_rows_mt_worker(void *p)
{
    ESP_NN_PIE_ENABLE();
    const conv_pie_rows_mt_job_t *j = (const conv_pie_rows_mt_job_t *)p;
]=] "esp_nn_conv_riscv_pie.c conv_pie_rows_mt_worker PIE cfg")
ainekio_pie_replace(nn_conv_contents [=[
static void conv1x1_pie_mt_worker(void *p)
{
    const conv1x1_pie_mt_job_t *j = (const conv1x1_pie_mt_job_t *)p;
]=] [=[
static void conv1x1_pie_mt_worker(void *p)
{
    ESP_NN_PIE_ENABLE();
    const conv1x1_pie_mt_job_t *j = (const conv1x1_pie_mt_job_t *)p;
]=] "esp_nn_conv_riscv_pie.c conv1x1_pie_mt_worker PIE cfg")
ainekio_pie_replace(nn_conv_contents [=[
    const uint16_t filter_wd = filter_dims->width;
    const uint16_t filter_ht = filter_dims->height;
    const uint16_t pad_wd = conv_params->padding.width;
]=] [=[
    ESP_NN_PIE_ENABLE();

    const uint16_t filter_wd = filter_dims->width;
    const uint16_t filter_ht = filter_dims->height;
    const uint16_t pad_wd = conv_params->padding.width;
]=] "esp_nn_conv_riscv_pie.c esp_nn_conv_s8_riscv_pie PIE cfg")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/convolution/esp_nn_conv_riscv_pie.c"
    CONTENT "${nn_conv_contents}" @ONLY)

# 2f. esp_nn_fully_connected_s8_riscv_pie.c
set(nn_fc_src "${esp_nn_dir}/src/fully_connected/esp_nn_fully_connected_s8_riscv_pie.c")
file(READ "${nn_fc_src}" nn_fc_contents)
ainekio_pie_replace(nn_fc_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_fully_connected_s8_riscv_pie.c csrsi 0x7f2")
ainekio_pie_replace(nn_fc_contents [=[
            /* Zero-overhead hardware loop; end label sits ON the last insn */
            "esp.lp.setup 0, %[c32], 1f             \n\t"
            /* MAC pair 1 + load next input[0:16] */
            "esp.vmulas.s8.xacc.ld.ip q0, x30, 16, q0, q1 \n\t"
            /* Load next filter[0:16] while MAC settles */
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            /* MAC pair 2 + load next input[16:32] */
            "esp.vmulas.s8.xacc.ld.ip q2, x30, 16, q2, q3 \n\t"
            "1:                                     \n\t"
            /* Load next filter[16:32] */
            "esp.vld.128.ip  q3, x31, 16            \n\t"

            "2:                                     \n\t"
            /* Drain pipeline: final two MACs */
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "esp.vmulas.s8.xacc  q2, q3             \n\t"

            /* Handle 16-element remainder if any */
            "beqz   %[rem16], 3f                    \n\t"
            "esp.vld.128.ip  q0, x30, 16            \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "3:                                     \n\t"

            "esp.movx.r.xacc.l   x30                \n\t"
            "mv     %[res], x30                     \n\t"
            : [res] "=r"(result)
            : [in] "r"(input), [flt] "r"(filter), [c32] "r"(c32), [rem16] "r"(rem16)
            : "x30", "x31"
]=] [=[
            "mv     x29, %[c32]                     \n\t"
            "1:                                     \n\t"
            /* MAC pair 1 + load next input[0:16] */
            "esp.vmulas.s8.xacc.ld.ip q0, x30, 16, q0, q1 \n\t"
            /* Load next filter[0:16] while MAC settles */
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            /* MAC pair 2 + load next input[16:32] */
            "esp.vmulas.s8.xacc.ld.ip q2, x30, 16, q2, q3 \n\t"
            /* Load next filter[16:32] */
            "esp.vld.128.ip  q3, x31, 16            \n\t"
            "addi   x29, x29, -1                    \n\t"
            "bnez   x29, 1b                         \n\t"

            "2:                                     \n\t"
            /* Drain pipeline: final two MACs */
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "esp.vmulas.s8.xacc  q2, q3             \n\t"

            /* Handle 16-element remainder if any */
            "beqz   %[rem16], 3f                    \n\t"
            "esp.vld.128.ip  q0, x30, 16            \n\t"
            "esp.vld.128.ip  q1, x31, 16            \n\t"
            "esp.vmulas.s8.xacc  q0, q1             \n\t"
            "3:                                     \n\t"

            "esp.movx.r.xacc.l   x30                \n\t"
            "mv     %[res], x30                     \n\t"
            : [res] "=r"(result)
            : [in] "r"(input), [flt] "r"(filter), [c32] "r"(c32), [rem16] "r"(rem16)
            : "x29", "x30", "x31"
]=] "esp_nn_fully_connected_s8_riscv_pie.c fc_dot_s8_pie loop")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/fully_connected/esp_nn_fully_connected_s8_riscv_pie.c"
    CONTENT "${nn_fc_contents}" @ONLY)

# 2g. esp_nn_avg_pool_s8_riscv_pie.c
set(nn_avg_src "${esp_nn_dir}/src/pooling/esp_nn_avg_pool_s8_riscv_pie.c")
file(READ "${nn_avg_src}" nn_avg_contents)
ainekio_pie_replace(nn_avg_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_avg_pool_s8_riscv_pie.c csrsi 0x7f2")
ainekio_pie_replace(nn_avg_contents [=[
                        /* zero-overhead loop; end label ON last body insn */
                        "esp.lp.setup 0, %[cnt], 1f      \n\t"
                        "esp.vld.128.ip  q0, x30, 0      \n\t"
                        "esp.vmulas.s8.qacc q0, q7       \n\t"
                        "1:                              \n\t"
                        "add    x30, x30, %[stride]      \n\t"
                        :
                        : [ptr] "r"(row_ptr), [cnt] "r"(fx_count),
                          [stride] "r"((int32_t)channels)
                        : "x30"
]=] [=[
                        "blez   %[cnt], 2f               \n\t"
                        "mv     x29, %[cnt]              \n\t"
                        "1:                              \n\t"
                        "esp.vld.128.ip  q0, x30, 0      \n\t"
                        "esp.vmulas.s8.qacc q0, q7       \n\t"
                        "add    x30, x30, %[stride]      \n\t"
                        "addi   x29, x29, -1             \n\t"
                        "bnez   x29, 1b                  \n\t"
                        "2:                              \n\t"
                        :
                        : [ptr] "r"(row_ptr), [cnt] "r"(fx_count),
                          [stride] "r"((int32_t)channels)
                        : "x29", "x30"
]=] "esp_nn_avg_pool_s8_riscv_pie.c loop")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/pooling/esp_nn_avg_pool_s8_riscv_pie.c"
    CONTENT "${nn_avg_contents}" @ONLY)

# 2h. esp_nn_max_pool_s8_riscv_pie.c
set(nn_max_src "${esp_nn_dir}/src/pooling/esp_nn_max_pool_s8_riscv_pie.c")
file(READ "${nn_max_src}" nn_max_contents)
ainekio_pie_replace(nn_max_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_max_pool_s8_riscv_pie.c csrsi 0x7f2")
ainekio_pie_replace(nn_max_contents [=[
                        /* zero-overhead loop; end label ON last body insn */
                        "esp.lp.setup 0, %[cnt], 1f      \n\t"
                        "esp.vld.128.ip  q1, x30, 0      \n\t"
                        "esp.vmax.s8     q0, q0, q1      \n\t"
                        "1:                              \n\t"
                        "add    x30, x30, %[stride]      \n\t"
                        :
                        : [ptr] "r"(row_ptr), [cnt] "r"(fx_count),
                          [stride] "r"((int32_t)channels)
                        : "x30"
]=] [=[
                        "blez   %[cnt], 2f               \n\t"
                        "mv     x29, %[cnt]              \n\t"
                        "1:                              \n\t"
                        "esp.vld.128.ip  q1, x30, 0      \n\t"
                        "esp.vmax.s8     q0, q0, q1      \n\t"
                        "add    x30, x30, %[stride]      \n\t"
                        "addi   x29, x29, -1             \n\t"
                        "bnez   x29, 1b                  \n\t"
                        "2:                              \n\t"
                        :
                        : [ptr] "r"(row_ptr), [cnt] "r"(fx_count),
                          [stride] "r"((int32_t)channels)
                        : "x29", "x30"
]=] "esp_nn_max_pool_s8_riscv_pie.c loop")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/pooling/esp_nn_max_pool_s8_riscv_pie.c"
    CONTENT "${nn_max_contents}" @ONLY)

# 2i. esp_nn_softmax_s8_riscv_pie.c
set(nn_softmax_src "${esp_nn_dir}/src/softmax/esp_nn_softmax_s8_riscv_pie.c")
file(READ "${nn_softmax_src}" nn_softmax_contents)
ainekio_pie_replace(nn_softmax_contents
    "        \"csrsi  0x7f2, 0b01        \\n\\t\"\n"
    ""
    "esp_nn_softmax_s8_riscv_pie.c csrsi 0x7f2")
ainekio_pie_replace(nn_softmax_contents [=[
        if (width >= 16) {
]=] [=[
        if (width >= 16) {
            ESP_NN_PIE_ENABLE();
]=] "esp_nn_softmax_s8_riscv_pie.c PIE cfg")
ainekio_pie_replace(nn_softmax_contents [=[
                /* zero-overhead loop; end label ON last body insn */
                "esp.lp.setup 0, %[cnt], 1f      \n\t"
                "esp.vld.128.ip q1, x30, 16      \n\t"  /* load next 16, advance */
                "1:                              \n\t"
                "esp.vmax.s8    q0, q0, q1       \n\t"  /* running max */
]=] [=[
                "1:                              \n\t"
                "esp.vld.128.ip q1, x30, 16      \n\t"  /* load next 16, advance */
                "esp.vmax.s8    q0, q0, q1       \n\t"  /* running max */
                "addi   %[cnt], %[cnt], -1       \n\t"
                "bnez   %[cnt], 1b               \n\t"
]=] "esp_nn_softmax_s8_riscv_pie.c loop")
file(CONFIGURE OUTPUT "${esp_nn_copy}/src/softmax/esp_nn_softmax_s8_riscv_pie.c"
    CONTENT "${nn_softmax_contents}" @ONLY)

# Configure-time invariant check: no direct 0x7f2 writes or inline-asm esp.lp.setup remain.
set(nn_patched_files
    "${esp_nn_copy}/src/common/common_functions.h"
    "${esp_nn_copy}/src/common/esp_nn_multicore.c"
    "${esp_nn_copy}/src/common/esp_nn_mean_s8_riscv_pie.c"
    "${esp_nn_copy}/src/activation_functions/esp_nn_relu_s8_riscv_pie.c"
    "${esp_nn_copy}/src/convolution/esp_nn_depthwise_conv_riscv_pie.c"
    "${esp_nn_copy}/src/convolution/esp_nn_conv_riscv_pie.c"
    "${esp_nn_copy}/src/fully_connected/esp_nn_fully_connected_s8_riscv_pie.c"
    "${esp_nn_copy}/src/pooling/esp_nn_avg_pool_s8_riscv_pie.c"
    "${esp_nn_copy}/src/pooling/esp_nn_max_pool_s8_riscv_pie.c"
    "${esp_nn_copy}/src/softmax/esp_nn_softmax_s8_riscv_pie.c")

foreach(patched_file IN LISTS nn_patched_files)
    file(READ "${patched_file}" check_contents)
    if(check_contents MATCHES "0x7f2")
        message(FATAL_ERROR "idf_pie_coproc: residual 0x7f2 in ${patched_file}")
    endif()
    if(check_contents MATCHES "\"[ \t]*esp\\.lp\\.setup")
        message(FATAL_ERROR "idf_pie_coproc: residual esp.lp.setup in ${patched_file}")
    endif()
endforeach()

get_target_property(esp_nn_sources ${esp_nn_lib} SOURCES)
list(FILTER esp_nn_sources EXCLUDE REGEX
    "(^|/)src/(common/esp_nn_multicore|common/esp_nn_mean_s8_riscv_pie|activation_functions/esp_nn_relu_s8_riscv_pie|convolution/esp_nn_depthwise_conv_riscv_pie|convolution/esp_nn_conv_riscv_pie|fully_connected/esp_nn_fully_connected_s8_riscv_pie|pooling/esp_nn_avg_pool_s8_riscv_pie|pooling/esp_nn_max_pool_s8_riscv_pie|softmax/esp_nn_softmax_s8_riscv_pie)\\.c$")
set_property(TARGET ${esp_nn_lib} PROPERTY SOURCES "${esp_nn_sources}")
target_sources(${esp_nn_lib} PRIVATE
    "${esp_nn_copy}/src/common/esp_nn_multicore.c"
    "${esp_nn_copy}/src/common/esp_nn_mean_s8_riscv_pie.c"
    "${esp_nn_copy}/src/activation_functions/esp_nn_relu_s8_riscv_pie.c"
    "${esp_nn_copy}/src/convolution/esp_nn_depthwise_conv_riscv_pie.c"
    "${esp_nn_copy}/src/convolution/esp_nn_conv_riscv_pie.c"
    "${esp_nn_copy}/src/fully_connected/esp_nn_fully_connected_s8_riscv_pie.c"
    "${esp_nn_copy}/src/pooling/esp_nn_avg_pool_s8_riscv_pie.c"
    "${esp_nn_copy}/src/pooling/esp_nn_max_pool_s8_riscv_pie.c"
    "${esp_nn_copy}/src/softmax/esp_nn_softmax_s8_riscv_pie.c")

set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${rvruntime_source}"
    "${portasm_source}"
    "${nn_common_hdr}"
    "${nn_multicore_src}"
    "${nn_mean_src}"
    "${nn_relu_src}"
    "${nn_dw_src}"
    "${nn_conv_src}"
    "${nn_fc_src}"
    "${nn_avg_src}"
    "${nn_max_src}"
    "${nn_softmax_src}")

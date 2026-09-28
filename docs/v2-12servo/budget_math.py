"""Reproduce RESOURCE_BUDGET.md arithmetic; no hardware or network access.

Run: python3 docs/v2-12servo/budget_math.py
All future layouts are explicit scenarios, not measured complete allocations.
"""
import json
from pathlib import Path

KIB, MIB = 1024, 1024**2
J = 256 * KIB
ROOT = Path(__file__).resolve().parents[2]
geometry = json.loads((ROOT / 'Slave/software/models/v2-12servo/geometry.json').read_text())
run = json.loads((ROOT / 'Slave/software/models/v2-12servo/motions/run/config.json').read_text())

audio = {}
for rate, bits in [(16000,16),(24000,16),(48000,16),(48000,24),(96000,24),(96000,32)]:
    block = rate * bits // 8 // 50
    queues = 50*(block+4) + 8*(block+5)
    audio[f'{rate}/{bits}'] = {
        'block_bytes_20ms': block, 'duplex_mbps': rate*bits*2/1e6,
        'queues_bytes': queues, 'queues_kib': queues/KIB,
        'dma_payload_bytes_8_blocks': 8*block,
        'six_mic_arrays_bytes': 6*block,
    }

camera = {}
for name,w,h,fps in [('720p60',1280,720,60),('1080p30',1920,1080,30),('5MP15',2592,1944,15)]:
    raw = w*h*2
    # Specific future layout: two captures + one full-size working frame,
    # six compressed buffers, max model+arena, reference 170x320 double LCD,
    # 96k/24-bit queues plus 8 DMA, 6 mic and 1 speaker staging blocks.
    high_audio = audio['96000/24']
    counted = 3*raw+6*J+MIB+170*320*4+high_audio['queues_bytes']+15*high_audio['block_bytes_20ms']
    camera[name] = {
        'raw_rgb565_one_mib':raw/MIB,'raw_rgb565_three_mib':3*raw/MIB,
        'raw_rgb888_three_mib':w*h*3*3/MIB,
        'base_plus_jpeg_wake_mib':(3*raw+6*J+MIB)/MIB,
        'bulk_with_high_audio_and_reference_lcd_mib':counted/MIB,
        'remainder_before_unlisted_allocations_mib':32-counted/MIB,
        'capture_rgb565_MB_s':raw*fps/1e6,
    }

traffic = []
for kib in [64,128,192,256]:
    for fps in [15,30,60]:
        image_mbps=kib*KIB*fps*8/1e6
        traffic.append({'jpeg_kib':kib,'fps':fps,'image_mbps':image_mbps,
            'tx_with_96k24_mic_mbps':image_mbps+2.304,
            'rx_96k24_speaker_mbps':2.304,
            'tx_with_48k24_mic_mbps':image_mbps+1.152})

imu=[{'odr_hz':hz,'six_axis_B_s':hz*12,'i2c_400k_percent':hz*135/400000*100,'sample_period_ms':1000/hz} for hz in [104,208,416,833,1666]]
lcd=[{'w':w,'h':h,'rgb565_one_bytes':w*h*2,'rgb565_double_kib':w*h*4/KIB,'full_refresh_30_mbps':w*h*16*30/1e6,'full_refresh_60_mbps':w*h*16*60/1e6} for w,h in [(170,320),(240,320)]]
base=geometry['gait_controls']['base_cycle_seconds']
sweep=geometry['continuous_walk']['stance_sweep_100_mm']
duty=geometry['ground_contact_fraction']
walk=[]
for label,stride,rate in [('speed25',50,1),('speed50',100,1),('speed100',100,2),('stride100_rate3',100,3)]:
    walk.append({'setting':label,'cycle_s':base/rate,'frames_per_cycle':50*base/rate,'reference_mm_s':sweep*stride/100/duty*rate/base})

print(json.dumps({
    'units':'MiB=1048576 B; Mbit/s=1000000 bit/s; all transport excludes overhead',
    'camera':camera,'audio':audio,'traffic':traffic,'imu':imu,'lcd':lcd,'walk':walk,
    'run200_reference_mm_s':run['forward']['sweep_mm']/run['ground_contact_fraction']*(200/75)/run['base_cycle_seconds'],
    'app_remainder_bytes':8*MIB-2369264,
    'pca_wire_us':66*9/400000*1e6,
    'wifi_53_4_mbps_max_jpeg_kib_at30_with96k24':(53.4e6-2304000)/8/30/KIB,
    'servo_limit_per_unit_mA':[{'other_load_A':a,'mean_servo_limit_mA':(3-a)*1000/12} for a in [0,.25,.5,1,1.5]],
    'battery_ideal_ceiling_hours':[{'total_W':p,'hours':36/p} for p in [10,15,20,30]],
},indent=2))

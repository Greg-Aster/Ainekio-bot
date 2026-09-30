"""Create a clearly labelled reference model, not manufacturer-certified CAD.
All construction coordinates are millimetres. See README.txt for uncertainty.
"""
from pathlib import Path
import json, struct
import cadquery as cq

OUT = Path(__file__).resolve().parent
W, H = 29.0, 62.0
PCB_T = 1.6
LCD_W, LCD_H, LCD_T = 25.8, 49.72, 1.43
HOLE_D = 2.5  # Estimated: check against physical module
MOUNT_CENTRES = [(x,y) for x in (-12.5,12.5) for y in (-29,29)]
PIN_X = [(i-3.5)*2.54 for i in range(8)]
col = {
 'pcb': (0.018,0.13,0.30), 'metal': (0.65,0.69,0.72),
 'glass': (0.008,0.012,0.018), 'active': (0.015,0.027,0.038),
 'white': (0.91,0.90,0.83), 'black': (0.025,0.028,0.033),
 'flex': (0.55,0.25,0.045), 'gold': (0.76,0.48,0.13),
 'tan': (0.49,0.38,0.23), 'adhesive': (0.11,0.12,0.13)
}
parts=[]
def add(name,shape,color,certainty='estimated'):
    if isinstance(shape,cq.Workplane): shape=shape.val()
    assert shape.isValid(), name
    parts.append((name,shape,color,certainty))
    return shape
def box(w,h,t,x=0,y=0,z=0):
    return cq.Workplane('XY').box(w,h,t,centered=(True,True,False)).translate((x,y,z))
def ring(x,y,ro,ri,z,t=0.035):
    return cq.Workplane('XY',origin=(x,y,z)).circle(ro).circle(ri).extrude(t)
def text_top(s,x,y,z,size=0.7):
    return cq.Workplane('XY',origin=(x,y,z)).text(s,size,0.018,font='Liberation Sans',halign='center',valign='center',combine=False)

pcb=box(W,H,PCB_T).edges('|Z').fillet(0.7)
for x,y in MOUNT_CENTRES:
    pcb=pcb.cut(cq.Workplane('XY',origin=(x,y,-0.1)).circle(HOLE_D/2).extrude(PCB_T+0.2))
for x in PIN_X:
    pcb=pcb.cut(cq.Workplane('XY',origin=(x,29,-0.1)).circle(0.5).extrude(PCB_T+0.2))
pcb=pcb.cut(cq.Workplane('XY',origin=(0,-26.25,-0.1)).slot2D(22,1.35).extrude(PCB_T+0.2))
add('PCB_29x62_holes_ESTIMATED',pcb,'pcb','outline per listing photo; holes estimated')
for i,(x,y) in enumerate(MOUNT_CENTRES):
    add(f'Mount_pad_front_{i+1}',ring(x,y,1.87,HOLE_D/2,PCB_T),'metal')
    add(f'Mount_pad_back_{i+1}',ring(x,y,1.87,HOLE_D/2,-0.035),'metal')
for i,x in enumerate(PIN_X):
    add(f'Pin_pad_front_{i+1}',ring(x,29,0.85,0.5,PCB_T),'metal')
    add(f'Pin_pad_back_{i+1}',ring(x,29,0.85,0.5,-0.035),'metal')
    add(f'Pin_label_{i+1}',text_top(['GND','VCC','SCL','SDA','RES','DC','CS','BLK'][i],x,26.8,1.64),'white')

add('Adhesive_ESTIMATED',box(24.8,48.7,0.3,z=1.6),'adhesive')
add('LCD_package_base_representative_25p8x49p72',box(LCD_W,LCD_H,LCD_T-0.10,z=1.9),'white')
add('Glass_border',box(25.3,49.2,0.07,z=3.23),'glass')
add('Viewing_window_23p695x43p72',box(23.695,43.72,0.015,y=2.5,z=3.30),'black')
add('Active_area_22p695x42p72',box(22.695,42.72,0.015,y=2.5,z=3.315),'active','size from Amazon; offset estimated')
add('LCD_driver_strip_ESTIMATED',box(23.2,2.4,0.010,y=-22.3,z=3.30),'black')

# Folded flex and rear electronics: representative geometry from product photos.
poly=[(-7.8,7.4),(7.8,7.4),(7.8,-19.2),(10.1,-20.1),(10.1,-25.6),(-7.8,-25.6)]
add('Rear_flex_ESTIMATED',cq.Workplane('XY',origin=(0,0,-0.25)).polyline(poly).close().extrude(0.2),'flex')
add('Flex_through_slot_ESTIMATED',box(15.4,0.22,2.18,y=-26.15,z=-0.05),'flex')
add('Flex_front_fold_ESTIMATED',box(15.4,1.55,0.15,y=-25.47,z=1.95),'flex')
for i in range(26):
    add(f'Flex_trace_{i+1}',box(0.07,22.0,0.016,x=(i-12.5)*0.50,y=-4,z=-0.266),'gold')
add('Rear_FPC_connector_ESTIMATED',box(20.2,3.8,1.77,y=7.7,z=-1.77),'white')
add('FPC_latch_ESTIMATED',box(15.8,0.65,0.30,y=5.75,z=-1.72),'black')
for i in range(30):
    add(f'FPC_contact_{i+1}',box(0.22,1.0,0.20,x=(i-14.5)*0.5,y=10.1,z=-0.2),'metal')
for i,x in enumerate([-9.5,-7.9,-6.3,-4.7,0.4,2.0,3.6,8.3,10.0]):
    add(f'SMD_{i+1}_ESTIMATED',box(0.85,1.6,0.65,x=x,y=19.2,z=-0.65),'tan' if i%3 else 'black')
    for j,dy in enumerate([-0.9,0.9]):
        add(f'SMD_pad_{i+1}_{j}',box(1.0,0.45,0.10,x=x,y=19.2+dy,z=-0.10),'metal')
for i,x in enumerate([-2.3,6.0]):
    add(f'SOT23_{i+1}_ESTIMATED',box(2.5,1.3,1.0,x=x,y=19.2,z=-1.0),'black')
    for j,(dx,dy) in enumerate([(-0.8,-1.0),(0.8,-1.0),(0,1.0)]):
        add(f'SOT23_leg_{i+1}_{j}',box(0.4,0.8,0.15,x=x+dx,y=19.2+dy,z=-0.15),'metal')

def assembly(header=False):
    a=cq.Assembly(name='XIITIA_1p9_REFERENCE_NOT_FACTORY_CAD')
    for name,s,c,certainty in parts:a.add(s,name=name,color=cq.Color(*col[c]))
    if header:
        a.add(box(20.32,2.54,2.5,y=29,z=-2.5).val(),name='Header_plastic_ESTIMATED',color=cq.Color(*col['black']))
        for i,x in enumerate(PIN_X):
            a.add(box(.64,.64,10.35,x=x,y=29,z=-8.5).val(),name=f'Header_pin_{i+1}_ESTIMATED',color=cq.Color(*col['metal']))
    return a

def set_glb_metres(path):
    # OCCT emits the millimetre construction coordinates unchanged. glTF uses
    # metres, so add a single parent scale rather than guessing on import.
    raw=path.read_bytes()
    chunks=[]; offset=12
    while offset<len(raw):
        size,kind=struct.unpack_from('<II',raw,offset)
        chunks.append((kind,raw[offset+8:offset+8+size]));offset+=8+size
    doc=json.loads(chunks[0][1])
    for scene in doc['scenes']:
        root=len(doc['nodes'])
        doc['nodes'].append({'name':'Reference_model_metres_NOT_verified_factory_CAD',
                             'scale':[0.001,0.001,0.001],'children':scene['nodes']})
        scene['nodes']=[root]
    doc.setdefault('asset',{})['extras']={'status':'Reconstructed reference model',
         'mounting_holes':'Estimated; confirm on physical board','PCB_mm':[W,H]}
    data=json.dumps(doc,separators=(',',':')).encode()
    data+=b' '*((-len(data))%4)
    chunks[0]=(chunks[0][0],data)
    body=b''.join(struct.pack('<II',len(b),k)+b for k,b in chunks)
    path.write_bytes(struct.pack('<III',0x46546C67,2,len(body)+12)+body)

if __name__=='__main__':
    for header in (False,True):
        a=assembly(header)
        stem='XIITIA_1p9_reference_'+('with_header' if header else 'no_header')
        a.export(str(OUT/(stem+'.step')))
        a.export(str(OUT/(stem+'.glb')),tolerance=0.025,angularTolerance=0.15)
        set_glb_metres(OUT/(stem+'.glb'))
        bb=a.toCompound().BoundingBox()
        print(stem, 'CAD bbox mm:',bb.xlen,bb.ylen,bb.zlen)
    (OUT/'model_metadata.json').write_text(json.dumps({
        'status':'Reconstructed reference; not manufacturer CAD; no physical measurements',
        'asin':'B0DFWMC16W','pcb_mm':[W,H,PCB_T],
        'mounting_holes_estimated_mm':{'diameter':HOLE_D,'centers':MOUNT_CENTRES},
        'listing_length_conflict_mm':[62,57.9],
        'components':[{'name':n,'basis':q} for n,s,c,q in parts]
    },indent=2))

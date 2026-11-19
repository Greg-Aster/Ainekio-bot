"""Purple two-hole GY-LSM6DS3 reconstructed reference. All CAD units mm.
See README.txt: mounting coordinates and component placement are estimates.
"""
from pathlib import Path
import json,struct
import cadquery as cq

OUT=Path(__file__).resolve().parent
W,H,PCB_T=13.0,18.0,1.6
MOUNT_CENTRES=[(2.5,7.1),(2.5,-7.1)]
HOLE_D=3.0
LEFT=[(-5.08,7.62-i*2.54) for i in range(7)]
RIGHT=[(5.08,5.08-i*2.54) for i in range(5)]
PADS=LEFT+RIGHT
col={'pcb':(.30,.12,.39),'gold':(.79,.58,.23),'metal':(.69,.72,.73),
     'black':(.055,.060,.065),'white':(.91,.91,.88),'tan':(.53,.45,.32),
     'trace':(.39,.19,.37),'etch':(.28,.29,.28)}
parts=[]
def add(name,shape,color,basis='estimated from photos'):
    if isinstance(shape,cq.Workplane):shape=shape.val()
    assert shape.isValid(),name
    parts.append((name,shape,color,basis));return shape
def box(w,h,t,x=0,y=0,z=0):
    return cq.Workplane('XY').box(w,h,t,centered=(True,True,False)).translate((x,y,z))
def txt(s,x,y,z,size=.7,back=False):
    t=cq.Workplane('XY').text(s,size,.016,font='Liberation Sans',halign='center',valign='center',combine=False)
    if back:t=t.rotate((0,0,0),(0,1,0),180)
    return t.translate((x,y,z))
def ring(x,y,z):
    return cq.Workplane('XY',origin=(x,y,z)).circle(.9).circle(.5).extrude(.025)
def line(points,width=.10,z=1.602,color='trace',name='Trace'):
    shapes=[]
    for (x1,y1),(x2,y2) in zip(points,points[1:]):
        dx,dy=x2-x1,y2-y1
        from math import hypot,degrees,atan2
        s=box(hypot(dx,dy),width,.014).rotate((0,0,0),(0,0,1),degrees(atan2(dy,dx))).translate(((x1+x2)/2,(y1+y2)/2,z))
        shapes.extend(s.solids().vals())
    if shapes:add(name,cq.Compound.makeCompound(shapes),color,'decorative; not a circuit schematic')

pcb=box(W,H,PCB_T).edges('|Z').fillet(.45)
for x,y in MOUNT_CENTRES:
    pcb=pcb.cut(cq.Workplane('XY',origin=(x,y,-.1)).circle(HOLE_D/2).extrude(PCB_T+.2))
for x,y in PADS:
    pcb=pcb.cut(cq.Workplane('XY',origin=(x,y,-.1)).circle(.5).extrude(PCB_T+.2))
add('Purple_PCB_13x18_two_holes_ESTIMATED',pcb,'pcb','outline from listings; thickness and holes estimated')
for i,(x,y) in enumerate(PADS):
    add(f'Gold_pad_top_{i+1}',ring(x,y,PCB_T),'gold')
    add(f'Gold_pad_bottom_{i+1}',ring(x,y,-.025),'gold')
    add(f'Plated_barrel_{i+1}',cq.Workplane('XY',origin=(x,y,0)).circle(.50).circle(.475).extrude(PCB_T),'gold')

# Subtle representative copper routes under solder mask.
routes=[[(x,y),(x*.67,y),(x*.45,y*.6),(x*.26,y*.3)] for x,y in PADS]
for i,p in enumerate(routes):line(p,name=f'Decorative_trace_{i+1}')

# SOT-23-5 regulator on the upper left, matching the photo's placement.
add('Regulator_SOT23_5_ESTIMATED',box(1.6,2.9,1.1,x=-1.4,y=7.0,z=PCB_T),'black')
for i,(x,y) in enumerate([(-2.5,6.05),(-2.5,7),(-2.5,7.95),(-.3,6.05),(-.3,7.95)]):
    add(f'Regulator_lead_{i+1}',box(.75,.40,.20,x=x,y=y,z=PCB_T+.05),'metal')
add('Regulator_mark',txt('33',-1.4,7.0,PCB_T+1.105,.5),'etch')

def passive(name,x,y,vertical=True,resistor=False,mark=False):
    w,h=(.8,1.6) if vertical else (1.6,.8)
    add(name+'_body',box(w,h,.55,x=x,y=y,z=PCB_T+.10),'black' if resistor else 'tan')
    for i,d in enumerate([-.66,.66]):
        if vertical:
            terminal=box(.88,.35,.62,x=x,y=y+d,z=PCB_T+.04)
        else:terminal=box(.35,.88,.62,x=x+d,y=y,z=PCB_T+.04)
        add(name+f'_end_{i+1}',terminal,'metal')
    if mark:
        label=txt('103',0,0,0,.35)
        if vertical:label=label.rotate((0,0,0),(0,0,1),90)
        add(name+'_mark',label.translate((x,y,PCB_T+.655)),'white')

for i,y in enumerate([4.7,3.55,2.4]):passive(f'Capacitor_top_{i+1}',-1.4,y,False)
passive('Capacitor_right',2.7,-.1,True)
passive('Resistor_left_1',-3.0,.7,True,True,True)
passive('Resistor_left_2',-3.0,-1.85,True,True,True)
passive('Resistor_bottom_1',-1.2,-3.9,False,True,True)
passive('Resistor_bottom_2',-1.2,-5.2,False,True,True)

# LGA-14 package dimensions from the ST LSM6DS3 datasheet.
cx,cy=.0,-.35
for i,yy in enumerate([-1,-.5,0,.5,1]):
    for side in (-1,1):
        add(f'IMU_contact_side_{side}_{i}',box(.35,.24,.08,x=cx+side*1.23,y=cy+yy,z=PCB_T+.02),'metal')
for i,xx in enumerate([-.5,.5]):
    for side in (-1,1):add(f'IMU_contact_end_{side}_{i}',box(.24,.35,.08,x=cx+xx,y=cy+side*1.47,z=PCB_T+.02),'metal')
add('LSM6DS3_LGA14_2p5x3x0p83',box(2.5,3,.83,x=cx,y=cy,z=PCB_T+.05),'black','package size ST datasheet; board position estimated')
add('Chip_text_1',txt('LSM',cx,cy+.35,PCB_T+.885,.44),'etch')
add('Chip_text_2',txt('6DS3',cx,cy-.35,PCB_T+.885,.44),'etch')
add('Chip_pin1_dot',cq.Workplane('XY',origin=(-.90,cy+1.12,PCB_T+.885)).circle(.1).extrude(.012),'etch')
add('Board_name_1',txt('LSM',-1.1,-6.85,PCB_T+.03,1.0),'white')
add('Board_name_2',txt('6DS3',-1.1,-8.00,PCB_T+.03,1.0),'white')

# Cosmetic axis glyph copied in general placement, not a calibrated axes guide.
line([(1.0,-4.5),(3.9,-4.5)],.10,PCB_T+.03,'white','Axis_cosmetic_horizontal')
line([(2.65,-5.4),(2.65,-2.8)],.10,PCB_T+.03,'white','Axis_cosmetic_vertical')
line([(1.0,-4.5),(1.5,-4.2)],.10,PCB_T+.03,'white','Arrow_1')
line([(1.0,-4.5),(1.5,-4.8)],.10,PCB_T+.03,'white','Arrow_2')
line([(2.65,-2.8),(2.35,-3.3)],.10,PCB_T+.03,'white','Arrow_3')
add('Axis_glyph_X',txt('X',3.45,-2.75,PCB_T+.03,.65),'white')
add('Axis_glyph_Y',txt('Y',1.00,-3.5,PCB_T+.03,.65),'white')
add('Axis_glyph_Z',txt('Z',3.60,-5.4,PCB_T+.03,.65),'white')

# Back silkscreen, readable from the back. Pin names from Amazon's rear photo.
for (x,y),label in zip(LEFT,['VIN','3V3','GND','SCL','SDA','CS','SA0']):
    add('Rear_label_'+label,txt(label,-2.7,y,-.03,.72,True),'white')
for (x,y),label in zip(RIGHT,['OCS','INT2','INT1','SCX','SDX']):
    add('Rear_label_'+label,txt(label,2.65,y,-.03,.72,True),'white')

def assembly(header=False):
    a=cq.Assembly(name='GY_LSM6DS3_TWO_HOLE_REFERENCE')
    for name,s,c,basis in parts:a.add(s,name=name,color=cq.Color(*col[c]))
    if header:
        for side,x,n in [('left',-5.08,7),('right',5.08,5)]:
            a.add(box(2.54,n*2.54,2.5,x=x,z=-2.5).val(),name=f'Header_{side}_{n}pin_ESTIMATED',color=cq.Color(*col['black']))
        for i,(x,y) in enumerate(PADS):
            a.add(box(.64,.64,10.35,x=x,y=y,z=-8.5).val(),name=f'Header_pin_{i+1}_ESTIMATED',color=cq.Color(*col['metal']))
    return a

def set_glb_metres(path):
    raw=path.read_bytes();chunks=[];off=12
    while off<len(raw):
        sz,kind=struct.unpack_from('<II',raw,off);chunks.append((kind,raw[off+8:off+8+sz]));off+=sz+8
    doc=json.loads(chunks[0][1])
    for scene in doc['scenes']:
        root=len(doc['nodes']);doc['nodes'].append({'name':'Reference_model_metres','scale':[.001]*3,'children':scene['nodes']});scene['nodes']=[root]
    doc['asset']['extras']={'status':'Reconstructed; not manufacturer CAD','PCB_mm':[W,H],'mounting':'estimated'}
    data=json.dumps(doc,separators=(',',':')).encode();data+=b' '*((-len(data))%4);chunks[0]=(chunks[0][0],data)
    body=b''.join(struct.pack('<II',len(b),k)+b for k,b in chunks)
    path.write_bytes(struct.pack('<III',0x46546C67,2,len(body)+12)+body)

if __name__=='__main__':
    for header in (False,True):
        stem='GY_LSM6DS3_reference_'+('with_headers' if header else 'no_headers')
        a=assembly(header);a.export(str(OUT/(stem+'.step')))
        a.export(str(OUT/(stem+'.glb')),tolerance=.018,angularTolerance=.15)
        set_glb_metres(OUT/(stem+'.glb'))
        bb=a.toCompound().BoundingBox();print(stem,'mm:',bb.xlen,bb.ylen,bb.zlen)
    (OUT/'model_metadata.json').write_text(json.dumps({'type':'reconstructed reference',
        'pcb_mm':[W,H,PCB_T],'mount_holes_estimated_mm':{'diameter':HOLE_D,'centers':MOUNT_CENTRES},
        'pads':PADS,'parts':[{'name':n,'basis':b} for n,s,c,b in parts]},indent=2))

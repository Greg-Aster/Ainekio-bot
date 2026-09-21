"""Monotone position/velocity-continuous curve writer for the existing rig."""
copied=set()
def animate(ob,path,index,values,constant=False):
    if ob.name not in copied:
        if ob.animation_data and ob.animation_data.action:
            old=ob.animation_data.action;old.use_fake_user=True
            ob.animation_data.action=old.copy();ob.animation_data.action.name=command+' | '+ob.name
            ob.animation_data.action_slot=ob.animation_data.action.slots[0]
        copied.add(ob.name)
    ob.keyframe_insert(data_path=path,index=index,frame=frames[0])
    ad=ob.animation_data;fc=next(f for f in ad.action.layers[0].strips[0].channelbag(ad.action_slot).fcurves if f.data_path==path and f.array_index==(0 if index<0 else index))
    values=np.array(values,float);delta=np.diff(values)/np.diff(times);deriv=np.zeros(len(times))
    same=delta[:-1]*delta[1:]>0;middle=np.zeros(len(times)-2)
    middle[same]=2*delta[:-1][same]*delta[1:][same]/(delta[:-1][same]+delta[1:][same]);deriv[1:-1]=middle
    if False:
        deriv[0]=deriv[-1]=2*delta[0]*delta[-1]/(delta[0]+delta[-1])
    for modifier in list(fc.modifiers):
        if modifier.type=='CYCLES':fc.modifiers.remove(modifier)
    fc.keyframe_points.clear();fc.keyframe_points.add(len(frames))
    fc.keyframe_points.foreach_set('co',np.column_stack([frames,values]).ravel())
    dt=1/cfg['sample_hz'];df=scene.render.fps*dt
    for i,k in enumerate(fc.keyframe_points):
        k.interpolation='CONSTANT' if constant else 'BEZIER'
        if not constant:
            k.handle_left_type='FREE';k.handle_right_type='FREE'
            k.handle_left=(frames[i]-df/3,values[i]-deriv[i]*dt/3)
            k.handle_right=(frames[i]+df/3,values[i]+deriv[i]*dt/3)
    fc.update()
    if False:
        modifier=fc.modifiers.new('CYCLES');modifier.mode_before='NONE'
        modifier.mode_after='REPEAT_OFFSET' if abs(values[-1]-values[0])>1e-7 else 'REPEAT'

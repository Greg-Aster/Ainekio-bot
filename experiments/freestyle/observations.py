"""Exact sensor arithmetic for model input; no recovery policy or thresholds."""
import math


def enrich(value):
    """Keep supplied evidence and add explicit angle/error measurements."""
    if isinstance(value,list):
        result=[enrich(item) for item in value]
        previous=None
        for item in result:
            if not isinstance(item,dict):continue
            orientation=(item.get('imu') or {}).get('derived_orientation')
            if orientation is not None:
                if previous is not None:
                    orientation['tilt_change_degrees']=orientation['tilt_degrees']-previous
                previous=orientation['tilt_degrees']
        return result
    if not isinstance(value,dict):return value
    result={key:enrich(item) for key,item in value.items()}
    quaternion=value.get('orientation_wxyz')
    if quaternion is not None and len(quaternion)==4:
        length=math.sqrt(sum(n*n for n in quaternion))
        if length:
            w,x,y,z=[n/length for n in quaternion]
            result['derived_orientation']={
                'roll_degrees':math.degrees(math.atan2(2*(w*x+y*z),1-2*(x*x+y*y))),
                'pitch_degrees':math.degrees(math.asin(max(-1,min(1,2*(w*y-z*x))))),
                'tilt_degrees':math.degrees(math.acos(max(-1,min(1,1-2*(x*x+y*y))))) }
    measured,target=value.get('model_deg'),value.get('commanded_model_deg')
    if measured is not None and target is not None:
        result['tracking_error_deg']=target-measured
    return result

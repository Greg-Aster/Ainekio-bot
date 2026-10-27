"""Exact sensor arithmetic for model input; no recovery policy or thresholds."""
import math


def feedback_geometry(mapping, joint, feedback):
    """Express the body's existing feedback calibration in model coordinates.

    This is a measurement domain, not a mechanical travel limit. Neither the
    compiler nor the executor clips targets to it. Keep extrapolated readings
    visible and separately report whether the body can use them for arrival.
    """
    result = {}
    points = joint.get('points', [])
    if joint.get('calibrated') and points and all(p is not None for p in points):
        direction = -1 if mapping['invert'] else 1
        result['feedback_range_deg'] = sorted([
            mapping['home_cd']/100 + direction*(p['pulse_us']-mapping['home_us'])/mapping['us_per_degree']
            for p in (points[0], points[-1])])
    if 'arrival_tolerance_us' in feedback:
        result['arrival_tolerance_deg'] = feedback['arrival_tolerance_us']/mapping['us_per_degree']
    health = feedback.get('health')
    if health is not None:
        bit = 1 << joint['id']
        result['feedback_faults'] = [name for name in (
            'unavailable', 'clipped', 'below_calibration', 'above_calibration')
            if health.get(name+'_mask', 0) & bit]
        result['feedback_usable'] = bool(health.get('enabled') and
            health.get('calibrated_mask', 0) & bit and not result['feedback_faults'])
    return result


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
    if 'model_deg' in value or 'commanded_model_deg' in value:
        result.pop('tracking_error_deg',None)
        result.pop('within_arrival_tolerance',None)
    if isinstance(measured,(int,float)) and isinstance(target,(int,float)):
        result['tracking_error_deg']=target-measured
        tolerance=value.get('arrival_tolerance_deg')
        if tolerance is not None:
            # Compare only with the body's configured tolerance; this is not
            # a new acceptance threshold or a decision to end a task.
            result['within_arrival_tolerance']=abs(target-measured)<=tolerance
    elif isinstance(measured,list) and isinstance(target,list):
        # The compact contract stores the same measurements in joint columns.
        result['tracking_error_deg']=[b-a if isinstance(a,(int,float)) and isinstance(b,(int,float))
                                      else None for a,b in zip(measured,target)]
    joints=result.get('joints')
    if isinstance(joints,dict) and joints and all(isinstance(v,dict) for v in joints.values()):
        # Exact aggregation of the supplied measurements. This says nothing
        # about whether a gesture is finished or whether feet contact ground.
        result['shaft_tracking']={
            'within_arrival_tolerance':[j for j,v in joints.items() if v.get('within_arrival_tolerance') is True],
            'outside_arrival_tolerance':[j for j,v in joints.items() if v.get('within_arrival_tolerance') is False],
            'unknown_arrival_tolerance':[j for j,v in joints.items() if 'within_arrival_tolerance' not in v],
            'unusable_feedback':[j for j,v in joints.items() if v.get('feedback_usable') is False],
            'unknown_feedback_usability':[j for j,v in joints.items() if v.get('feedback_usable') is None]}
    if 'request' in result and 'observation' in result:
        # Preserve every field and history sample; put present evidence after
        # historical evidence in the causal model's input.
        result={**{k:v for k,v in result.items() if k!='observation'},'observation':result['observation']}
    return result

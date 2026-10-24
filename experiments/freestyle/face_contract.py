"""Face operation derived from the existing P4 renderer/gateway vocabulary."""
import copy
import json
import re
from pathlib import Path

from .runtime import compact

FACE_SOURCE=Path(__file__).resolve().parents[2]/'Slave/software/faces/faces.def'


def available_faces():
    return re.findall(r'^FACE\(([a-z0-9_]+),',FACE_SOURCE.read_text(),re.MULTILINE)


def face_tool():
    return {'name':'face','description':'Show an existing robot face immediately. Gesture cues animate during the current program, then the normal body face resumes. A face-only program uses the normal face selection lifetime until replacement or a body motion revision. This operation does not move joints or wait.',
            'parameters':{'type':'object','properties':{'expr':{'type':'string','enum':available_faces()}},
                          'required':['expr'],'additionalProperties':False}}


def extend_contract(system,tools):
    tools=[copy.deepcopy(t) for t in tools if t['name']!='face']+[face_tool()]
    marker='Tools: '
    if marker in system:
        start=system.index(marker)+len(marker)
        _,end=json.JSONDecoder().raw_decode(system[start:])
        system=system[:start]+compact(tools)+system[start+end:]
    else:system+='\nTools: '+compact(tools)+'\n'
    system+=('\nCoordinate appropriate face expressions with expressive motions using face calls. '
             'Face changes do not insert a pause. Respect an explicitly requested expression and ending; '
             'a face-only request needs no body movement.\n')
    return system,tools

"""Compact inherited display expressions before Blender's 255-character limit."""
import bpy,json,ast,math
from pathlib import Path
P=Path(__file__).resolve().parent
class Compact(ast.NodeTransformer):
 def visit_BoolOp(self,node):
  node=self.generic_visit(node)
  if not isinstance(node.op,ast.Or):return node
  values=[]
  for v in node.values:values.extend(v.values if isinstance(v,ast.BoolOp) and isinstance(v.op,ast.Or) else [v])
  cutoffs=[];other=[]
  for v in values:
   if isinstance(v,ast.Compare) and isinstance(v.left,ast.Name) and v.left.id=='frame' and len(v.ops)==1 and isinstance(v.ops[0],ast.GtE) and isinstance(v.comparators[0],ast.Constant) and isinstance(v.comparators[0].value,(int,float)):cutoffs.append(v.comparators[0].value)
   elif ast.dump(v) not in {ast.dump(x) for x in other}:other.append(v)
  if cutoffs:other.append(ast.parse(f'frame >= {min(cutoffs)}',mode='eval').body)
  return other[0] if len(other)==1 else ast.BoolOp(op=ast.Or(),values=other)
records=json.loads((P/'prior-display-drivers.json').read_text());count=0
for r in records:
 ob=bpy.data.objects.get(r['object'])
 if ob is None:continue
 original=r['expression'];tree=ast.parse(f'({original}) or frame >= 3109',mode='eval');new=ast.unparse(ast.fix_missing_locations(Compact().visit(tree)))
 assert len(new)<255
 oldcode=compile(original,'<original>','eval');newcode=compile(new,'<compact>','eval')
 for f in range(1,3109):
  env=dict(frame=f,int=int,floor=math.floor,min=min,abs=abs)
  assert bool(eval(oldcode,{'__builtins__':{}},env))==bool(eval(newcode,{'__builtins__':{}},env)),r['object']
 fc=next(fc for fc in ob.animation_data.drivers if fc.data_path==r['path']);fc.driver.expression=new;count+=1
report=dict(repaired_display_drivers=count,earlier_integer_frame_visibility_preserved_through=3108,maximum_expression_length=max(len(fc.driver.expression) for o in bpy.data.objects if o.animation_data for fc in o.animation_data.drivers),model_geometry_modified=False)
(P/'display-driver-review.json').write_text(json.dumps(report,indent=2)+'\n');print(report)

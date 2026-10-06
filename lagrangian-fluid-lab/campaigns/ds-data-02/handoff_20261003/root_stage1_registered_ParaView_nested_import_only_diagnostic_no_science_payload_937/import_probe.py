import json,sys,traceback
result={'science_payload_IO':False}
try:
 import numpy
 from PIL import Image,ImageDraw
 from paraview import servermanager
 from paraview.simple import GetAnimationScene,GetParaViewVersion,Render,SaveScreenshot,SaveState,XDMFReader
 from vtkmodules.util.numpy_support import vtk_to_numpy
 result.update(status='imports_pass',paraview_version=str(GetParaViewVersion()),python_version=sys.version)
except BaseException:
 result.update(status='imports_failed',traceback=traceback.format_exc())
print(json.dumps(result),flush=True)
raise SystemExit(0 if result['status']=='imports_pass' else 1)

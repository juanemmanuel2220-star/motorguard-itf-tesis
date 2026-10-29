import sys, os, math
sys.path.insert(0, '/tmp/claude-1000/-home-luna/b6437c26-0f05-4c91-8ee8-1400b33559a8/scratchpad')
sys.argv=['x']
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import explora_post_hoc as X
for th in (30, 35, 40):
    print(f"pares A + angulo<={th}:", X.det_pares('F1', .40, 3, X.rel(th), minbloques=3))
print("pares A:", X.det_pares('F1', .40, 3, X.sin, minbloques=3))

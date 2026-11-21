import cv2, numpy as np, sys
vid, out = sys.argv[1], sys.argv[2]
cap = cv2.VideoCapture(vid); F=[]
while True:
    ok,f=cap.read()
    if not ok: break
    F.append(cv2.cvtColor(f,cv2.COLOR_BGR2GRAY).astype(np.float32))
F=np.stack(F)
def err(dy):
    # per-pixel match error between frame t+1 and frame t shifted by dy, using only nearby rows (no wrap issues)
    e=np.zeros(F.shape[1:],np.float32)
    for t in range(len(F)-1):
        e+=np.abs(F[t+1]-np.roll(F[t],(dy,0),axis=(0,1)))
    return e/(len(F)-1)
up=err(-3); down=err(3)
score=down-up   # >0 where content moves up
for k in (0,3):
    s=cv2.GaussianBlur(score,(0,0),k) if k else score
    s=np.clip((s-np.percentile(s,1))/(np.percentile(s,99)-np.percentile(s,1)),0,1)
    cv2.imwrite(f"{out}/score_blur{k}.png",(s*255).astype(np.uint8))
# window-based: classify per frame-pair to see if text changes over time
T=len(F)-1; W=30
for w0 in range(0,T,W):
    u=np.zeros(F.shape[1:],np.float32); d=np.zeros_like(u)
    for t in range(w0,min(T,w0+W)):
        u+=np.abs(F[t+1]-np.roll(F[t],(-3,0),axis=(0,1))); d+=np.abs(F[t+1]-np.roll(F[t],(3,0),axis=(0,1)))
    s=cv2.GaussianBlur(d-u,(0,0),2)
    s=np.clip((s-np.percentile(s,1))/(np.percentile(s,99)-np.percentile(s,1)+1e-6),0,1)
    cv2.imwrite(f"{out}/win_{w0:03d}.png",cv2.resize((s*255).astype(np.uint8),None,fx=0.5,fy=0.5))
print("ok")

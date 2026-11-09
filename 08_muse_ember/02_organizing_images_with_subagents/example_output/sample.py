import os, base64, io, json, urllib.request
from PIL import Image
base=os.environ['MODEL_API_BASE']; key=os.environ['MODEL_API_KEY']; model=os.environ['EMBER_MODEL']
def datauri(p):
    im=Image.open(p).convert('RGB'); im.thumbnail((512,512))
    b=io.BytesIO(); im.save(b,'JPEG',quality=80)
    return "data:image/jpeg;base64,"+base64.b64encode(b.getvalue()).decode()
files=sorted(os.listdir("Photos/Inbox"))
sample=[files[i] for i in range(0,len(files),312)][:32]
print(sample)
for s in range(0,len(sample),8):
    batch=sample[s:s+8]
    content=[{"type":"text","text":"Caption each image in one short sentence. Reply ONLY JSON array of strings in order."}]
    for f in batch: content.append({"type":"image_url","image_url":{"url":datauri(f"Photos/Inbox/{f}")}})
    payload={"model":model,"reasoning_effort":"minimal","messages":[{"role":"user","content":content}],"max_tokens":800}
    req=urllib.request.Request(base+"/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: d=json.load(r)
    caps=json.loads(d['choices'][0]['message']['content'])
    for f,c in zip(batch,caps): print(f, "|", c)

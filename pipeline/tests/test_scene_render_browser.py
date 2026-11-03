"""Rendering joins must remain opaque under fractional display transforms."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,handler
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


@unittest.skipIf(sync_playwright is None,'Playwright unavailable')
class SceneRenderBrowser(unittest.TestCase):
    def test_pixel_partition_join_survives_zoom_scale_pan_and_cache_changes(self):
        with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Panel(Path(tmp))))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page()
                fixture=Image.new('RGBA',(96,64));draw=ImageDraw.Draw(fixture)
                for y in range(64):
                    x=16+(y//4)%4
                    draw.line((x,y,x+31,y),fill='#657566' if y<20 else '#eedebc')
                stream=BytesIO();fixture.save(stream,'PNG')
                page.route('**/render-fixture.png',lambda route:route.fulfill(body=stream.getvalue(),content_type='image/png'))
                page.goto('http://127.0.0.1:%s/module-scenes.html'%server.server_port)
                result=page.evaluate('''async()=>{
                 const canvas=(w=300,h=150)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return c;};
                 const image=new Image();image.src='/render-fixture.png';await image.decode();
                 const renderer=new StudioSceneRenderer(),checks=[];
                 for(const scale of [1,.65])for(const zoom of [1,.37,.73,.87]){
                  const items=Array.from({length:4},(_,i)=>({image,x:12.3+i*32*scale,y:7.7,scale}));
                  const actual=canvas(),ctx=actual.getContext('2d');ctx.translate(.27,.61);ctx.scale(zoom,zoom);renderer.draw(ctx,items);
                  const native=canvas(192,64),n=native.getContext('2d');for(let i=0;i<4;i++)n.drawImage(image,i*32,0);
                  const expected=canvas(),e=expected.getContext('2d');e.translate(.27,.61);e.scale(zoom,zoom);e.drawImage(native,12.3,7.7,192*scale,64*scale);
                  const a=ctx.getImageData(0,0,300,150).data,b=e.getImageData(0,0,300,150).data;
                  checks.push(a.every((v,i)=>v===b[i]));
                 }
                 // A moved instance must rebuild the cached composite.
                 const moved=canvas(),m=moved.getContext('2d');renderer.draw(m,[{image,x:0,y:0,scale:1},{image,x:32,y:0,scale:1}]);
                 m.clearRect(0,0,300,150);renderer.draw(m,[{image,x:0,y:0,scale:1},{image,x:96,y:0,scale:1}]);
                 checks.push(m.getImageData(60,30,1,1).data[3]===0,m.getImageData(120,30,1,1).data[3]===255);
                 // Different scales keep source-over ordering and do not force alignment.
                 const mixed=canvas(),mc=mixed.getContext('2d'),reference=canvas(),rc=reference.getContext('2d');
                 const items=[{image,x:0,y:0,scale:1},{image,x:19.2,y:4.5,scale:.65}];
                 renderer.draw(mc,items);for(const v of items)rc.drawImage(image,v.x,v.y,96*v.scale,64*v.scale);
                 const a=mc.getImageData(0,0,300,150).data,b=rc.getImageData(0,0,300,150).data;checks.push(a.every((v,i)=>v===b[i]));
                 return checks;
                }''')
                self.assertTrue(all(result),result)
            finally:
                browser.close();server.shutdown();server.server_close();thread.join()

"""Local read-only progress UI. Does not expose project files or credentials."""
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = Path(__file__).resolve().parent.parent
PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Studio 任务进度</title>
<style>body{margin:0;background:#10151d;color:#e9eef6;font:16px system-ui;line-height:1.6}main{max-width:1000px;margin:auto;padding:36px 24px}h1{font-size:28px;margin:0}small,.muted{color:#a5b3c5}.card{background:#192332;border:1px solid #304056;border-radius:16px;padding:24px;margin:24px 0}.status{font-size:22px;font-weight:650;margin:18px 0 4px}.steps{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}.step{padding:7px 12px;border-radius:8px;background:#253145;color:#b2c0d1}.current{background:#245fd3;color:white}.done{background:#19483e;color:#a5f1d2}.error{color:#ffb2a5}.log{max-height:320px;overflow:auto;font:14px ui-monospace,monospace}.event{border-top:1px solid #304056;padding:8px 0}.path{word-break:break-all;white-space:pre-wrap;background:#101923;padding:12px;border-radius:8px}.badge{color:#9de4bd}.failed{color:#ffb2a5}button{background:#304f7d;color:white;border:0;padding:8px 14px;border-radius:8px;cursor:pointer}</style>
<main><h1>Pixel Studio · 任务进度</h1><small>每 2 秒刷新 · 时间按本机时区显示</small><p id="connection" class="muted">连接中…</p><div id="tasks"></div></main>
<script>
const labels={reconstruction:'原画重建',prepare:'贴图准备',rig:'人工绑定',download:'动作下载',import:'Godot 导入',render:'图集渲染',validate:'输出检查',complete:'完成'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function render(data){const root=document.getElementById('tasks');root.replaceChildren();if(!data.tasks.length)root.append(el('p','暂无任务；运行 Studio 后会显示阶段与结果。'));
for(const task of data.tasks){const card=el('section',undefined,'card');card.append(el('strong',task.character));
const phase=el('div',task.stage_label+' · '+({running:'进行中',waiting:'等待人工操作',complete:'已完成',failed:'失败'}[task.status]||task.status),'status '+(task.status==='failed'?'error':''));card.append(phase,el('p',task.message));
const steps=el('div',undefined,'steps');const keys=Object.keys(labels),current=keys.indexOf(task.stage);
for(const [key,label]of Object.entries(labels)){const seen=task.events.some(e=>e.stage===key);steps.append(el('span',label,'step '+(key===task.stage?'current':seen&&keys.indexOf(key)<current?'done':'')));}card.append(steps);
card.append(el('small','状态更新时间：'+new Date(task.updated_at).toLocaleString()));
for(const [key,label]of [['action','当前动作'],['batch','动作批次'],['job','任务日志目录'],['output','输出目录']]){if(task[key]){card.append(el('p',label+':'),el('div',task[key],'path'));}}
const details=el('details');details.open=task.status==='failed';details.append(el('summary','阶段记录'));const log=el('div',undefined,'log');for(const event of [...task.events].reverse()){log.append(el('div',new Date(event.time).toLocaleTimeString()+' · '+(labels[event.stage]||event.stage)+' · '+event.message,'event'));}details.append(log);card.append(details);root.append(card);}}
async function refresh(){try{const response=await fetch('/api/progress',{cache:'no-store'});if(!response.ok)throw Error(response.status);render(await response.json());document.getElementById('connection').textContent='已连接 · 最后刷新 '+new Date().toLocaleTimeString();}catch(e){document.getElementById('connection').textContent='连接中断，请检查 Studio 进度服务是否运行。';}}
refresh();setInterval(refresh,2000);
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            body, kind = PAGE.encode(), 'text/html; charset=utf-8'
        elif self.path == '/api/progress':
            directory = BASE_DIR / '.local/progress'
            tasks = []
            for path in directory.glob('*.json'):
                try:
                    tasks.append(json.loads(path.read_text()))
                except (OSError, json.JSONDecodeError):
                    continue
            body, kind = json.dumps({'tasks': sorted(tasks, key=lambda t:t['updated_at'], reverse=True)}, ensure_ascii=False).encode(), 'application/json; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = f'http://127.0.0.1:{server.server_port}/'
    config = BASE_DIR / '.local/monitor.json'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({'url': url}) + '\n')
    print(f'Studio 进度页面：{url}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    serve()
